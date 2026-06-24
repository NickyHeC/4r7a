"""Google Calendar MCP connection layer (operations department).

Mirrors ``gmail_client``: official Google-hosted Calendar MCP at
``https://calendarmcp.googleapis.com/mcp/v1`` with OAuth 2.0.

Docs: https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server
"""

from __future__ import annotations

import logging
import os
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config
from company_brain.agents.operations.shared.gcal_config import oauth_access_token

logger = logging.getLogger(__name__)

GCAL_SERVER_NAME = "calendar"
OFFICIAL = "official"
DEFAULT_OFFICIAL_URL = "https://calendarmcp.googleapis.com/mcp/v1"

GCAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def gcal_provider() -> str:
    env = os.getenv("GCAL_MCP_PROVIDER", "").strip().lower()
    if env:
        return env
    cfg = (load_operations_config().get("gcal") or {})
    return str(cfg.get("provider", OFFICIAL)).strip().lower()


def gcal_mcp_servers() -> dict[str, Any]:
    if gcal_provider() != OFFICIAL:
        raise ValueError(f"Unknown GCAL_MCP_PROVIDER '{gcal_provider()}'")
    url = os.getenv("GCAL_MCP_URL", "").strip() or DEFAULT_OFFICIAL_URL
    server: dict[str, Any] = {"type": "http", "url": url}
    token = oauth_access_token()
    if token:
        server["headers"] = {"Authorization": f"Bearer {token}"}
    else:
        logger.warning(
            "GCAL/Gmail OAuth access token not set; Calendar MCP needs OAuth "
            "(calendar scopes) — see project_install.md."
        )
    return {GCAL_SERVER_NAME: server}


def gcal_allowed_tools() -> list[str]:
    return [f"mcp__{GCAL_SERVER_NAME}"]


def gcal_is_configured() -> bool:
    from company_brain.agents.operations.shared.gcal_config import gcal_is_configured as configured

    return configured()
