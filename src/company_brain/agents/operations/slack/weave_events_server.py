"""Weave Slack Events API listeners — Socket Mode and HTTP."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from company_brain.agents.operations.slack import slack_client
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.agents.operations.slack.weave_events_router import WeaveEventsRouter
from company_brain.config import AppConfig, load_config

logger = logging.getLogger(__name__)


def serve_weave_events(*, http: bool = False, host: str = "0.0.0.0", port: int = 3001) -> None:
    config = load_config()
    if http or cfg.weave_events_mode() == "http":
        _serve_http(config, host=host, port=port)
    else:
        _serve_socket(config)


def _serve_socket(config: AppConfig) -> None:
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse

    if not slack_client.weave_socket_mode_configured():
        raise RuntimeError("SLACK_WEAVE_BOT_TOKEN and SLACK_WEAVE_APP_TOKEN required")

    router = WeaveEventsRouter(config)

    def _process(client: SocketModeClient, req: SocketModeRequest) -> None:
        if req.type != "events_api":
            return
        payload = req.payload or {}
        result = router.handle_payload(payload)
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        logger.debug("Weave event result: %s", result)

    client = SocketModeClient(
        app_token=slack_client.weave_app_token(),
        web_client=slack_client.client(app="weave"),
    )
    client.socket_mode_request_listeners.append(_process)
    logger.info("Slack weave events listening (Socket Mode)")
    client.connect()
    try:
        from threading import Event

        Event().wait()
    except KeyboardInterrupt:
        client.close()


def _serve_http(config: AppConfig, *, host: str, port: int) -> None:
    router = WeaveEventsRouter(config)
    path = cfg.weave_events_http_path()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != path:
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            timestamp = self.headers.get("X-Slack-Request-Timestamp") or ""
            signature = self.headers.get("X-Slack-Signature") or ""
            if not slack_client.verify_http_signature(
                body,
                timestamp,
                signature,
                signing_secret=slack_client.weave_signing_secret(),
            ):
                self.send_response(401)
                self.end_headers()
                return
            payload = json.loads(body.decode("utf-8"))
            result = router.handle_payload(payload)
            if "challenge" in result:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(str(result["challenge"]).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

    logger.info("Slack weave events listening (HTTP %s:%s%s)", host, port, path)
    HTTPServer((host, port), Handler).serve_forever()
