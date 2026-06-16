"""Ramp MCP connection configuration for finance agents — READ ONLY.

Ramp agents only read (transactions, bills, merchants, accounting categories);
they never issue cards, approve/pay bills, or change limits. Agent-driven writes
to a card platform are high-risk and immature, while read-only data already
unlocks the analysis value. Use a read-scoped ``RAMP_TOKEN`` and only allow read
tools from the MCP server.

Per project convention, Ramp is accessed through the Ramp MCP server rather
than direct REST. This module builds the ``mcp_servers`` mapping passed to the
Claude Agent SDK so a Ramp-touching agent can call Ramp tools.

Configuration (environment only — never hardcode company data):
  - ``RAMP_TOKEN``        Ramp developer API token (passed to the MCP server)
  - ``RAMP_MCP_COMMAND``  command to launch the stdio MCP server (default ``uvx``)
  - ``RAMP_MCP_ARGS``     space-separated args (default ``ramp-mcp``)
  - ``RAMP_MCP_URL``      optional URL for a hosted/HTTP Ramp MCP server

Docs: https://docs.ramp.com/developer-api/v1/ramp-mcp
"""

from __future__ import annotations

import os
from typing import Any

RAMP_SERVER_NAME = "ramp"


def ramp_mcp_servers() -> dict[str, Any]:
    """Return the ``mcp_servers`` mapping for ClaudeAgentOptions.

    Prefers a hosted URL if ``RAMP_MCP_URL`` is set; otherwise launches a local
    stdio MCP server via the configured command, passing ``RAMP_TOKEN`` through
    the environment.
    """
    url = os.getenv("RAMP_MCP_URL", "").strip()
    if url:
        return {RAMP_SERVER_NAME: {"type": "http", "url": url}}

    command = os.getenv("RAMP_MCP_COMMAND", "uvx")
    args = os.getenv("RAMP_MCP_ARGS", "ramp-mcp").split()
    token = os.getenv("RAMP_TOKEN", "")
    return {
        RAMP_SERVER_NAME: {
            "command": command,
            "args": args,
            "env": {"RAMP_TOKEN": token},
        }
    }


def ramp_allowed_tools() -> list[str]:
    """Tool names to pre-approve for the Ramp MCP server.

    The Claude Agent SDK namespaces MCP tools as ``mcp__<server>__<tool>``. We
    allow the whole Ramp server namespace so the agent can list transactions,
    bills, and merchants without per-call approval.
    """
    return [f"mcp__{RAMP_SERVER_NAME}"]
