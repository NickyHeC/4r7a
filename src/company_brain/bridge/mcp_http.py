"""HTTP MCP server (JSON-RPC 2.0) for member bridge tools."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from company_brain.bridge.config import BridgeConfig, load_bridge_config
from company_brain.bridge.tokens import BridgeTokenStore
from company_brain.bridge.tools import ToolContext, dispatch_tool

logger = logging.getLogger(__name__)

SERVER_NAME = "company-brain-bridge"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "report_blocker",
        "description": "Report an engineering blocker (structured fields only).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "area": {"type": "string"},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "blocked_since": {"type": "string"},
                "evidence": {"type": "string"},
                "suggested_owner": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["title", "area", "severity"],
        },
    },
    {
        "name": "get_priority",
        "description": "Company blocker rollup and lead focus master table.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_practices",
        "description": "Search department practice pages visible to your token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_skills",
        "description": "List shared skills for your department(s).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_skill",
        "description": "Load one shared skill by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "department": {"type": "string"},
            },
            "required": ["id"],
        },
    },
]


def _extract_bearer(header: str) -> str:
    if not header:
        return ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def handle_jsonrpc(
    req: dict[str, Any],
    *,
    member: str,
    bridge_cfg: BridgeConfig | None = None,
) -> dict[str, Any]:
    bridge_cfg = bridge_cfg or load_bridge_config()
    req_id = req.get("id")
    method = str(req.get("method") or "")
    params = req.get("params") or {}

    def reply(result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error:
            out["error"] = error
        else:
            out["result"] = result
        return out

    try:
        if method == "initialize":
            return reply(
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                }
            )
        if method == "notifications/initialized":
            return reply({})
        if method == "tools/list":
            return reply({"tools": TOOLS})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = dict(params.get("arguments") or {})
            ctx = ToolContext.for_member(member)
            data = dispatch_tool(ctx, name, arguments)
            return reply(_tool_result(data))
        return reply(error={"code": -32601, "message": f"Method not found: {method}"})
    except PermissionError as exc:
        return reply(error={"code": -32001, "message": str(exc)})
    except ValueError as exc:
        return reply(error={"code": -32602, "message": str(exc)})
    except Exception as exc:
        logger.exception("bridge tool error")
        return reply(error={"code": -32000, "message": str(exc)})


class BridgeMCPHandler(BaseHTTPRequestHandler):
    bridge_cfg: BridgeConfig = load_bridge_config()
    token_store: BridgeTokenStore = BridgeTokenStore()

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/mcp", "/"):
            _json_response(self, 404, {"error": "not found"})
            return

        token = _extract_bearer(self.headers.get("Authorization", ""))
        member = self.token_store.verify(token)
        if not member:
            _json_response(self, 401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        if isinstance(req, list):
            resp = [
                handle_jsonrpc(item, member=member, bridge_cfg=self.bridge_cfg)
                for item in req
                if isinstance(item, dict)
            ]
        elif isinstance(req, dict):
            resp = handle_jsonrpc(req, member=member, bridge_cfg=self.bridge_cfg)
        else:
            _json_response(self, 400, {"error": "invalid request"})
            return

        _json_response(self, 200, resp)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _json_response(self, 200, {"status": "ok", "service": SERVER_NAME})
            return
        _json_response(self, 404, {"error": "not found"})


def serve(host: str | None = None, port: int | None = None) -> None:
    cfg = load_bridge_config()
    bind_host = host or cfg.serve.host
    bind_port = port or cfg.serve.port
    server = ThreadingHTTPServer((bind_host, bind_port), BridgeMCPHandler)
    logger.info("Bridge MCP listening on http://%s:%s/mcp", bind_host, bind_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge MCP stopped")
        server.server_close()
