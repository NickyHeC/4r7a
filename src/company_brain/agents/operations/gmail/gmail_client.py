"""Gmail MCP connection layer for the operations department.

Gmail is accessed through the Model Context Protocol. Two connection paths are
supported; select with ``GMAIL_MCP_PROVIDER`` (or ``gmail.provider`` in
``config/operations.yaml``):

1. ``official`` (default) — Google's official, Google-hosted Gmail MCP server
   (Workspace Developer Preview). HTTP transport at
   ``https://gmailmcp.googleapis.com/mcp/v1`` with OAuth 2.0 (scopes
   ``gmail.readonly`` + ``gmail.compose`` (+ ``gmail.modify`` for REST label/archive
   via ``gmail_rest.py``). Best fit for an open-source project:
   each admin connects their own Google Cloud project / OAuth client, so the
   trust burden stays with them. Setup: enable ``gmail.googleapis.com`` +
   ``gmailmcp.googleapis.com`` in the project, configure the OAuth consent
   screen with the two scopes, create an OAuth client, and complete the consent
   flow to obtain an access token.
   Docs: https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server

2. ``composio`` — Composio's hosted Gmail MCP (Tool Router). HTTP transport with
   an ``x-api-key`` header; Composio manages OAuth and token refresh. Less
   developer setup ("works immediately") at the cost of a vendor dependency.
   Docs: https://composio.dev/toolkits/gmail

Write posture: **read + labels + DRAFT compose only**. Gmail agents must NEVER
send email — they create drafts that a human reviews and sends. The OAuth scopes
are ``gmail.readonly`` + ``gmail.compose``; per-agent tool allowlists (added when
the agents are built) must exclude any send tool. ``GMAIL_SEND_FORBIDDEN`` and
``send_allowed()`` make this policy explicit for callers.

This mirrors ``ramp_client``: it builds the ``mcp_servers`` mapping passed to the
Claude Agent SDK so a Gmail-touching agent can call Gmail tools. Configuration is
environment-only (never hardcode company data or secrets).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from company_brain.agents.operations.shared.config import load_operations_config

logger = logging.getLogger(__name__)

GMAIL_SERVER_NAME = "gmail"

OFFICIAL = "official"
COMPOSIO = "composio"

DEFAULT_OFFICIAL_URL = "https://gmailmcp.googleapis.com/mcp/v1"

# Read + labels + draft compose. Never send.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

# Sending email is forbidden by policy regardless of connection path: agents
# propose drafts a human sends. Keep this True unless a human explicitly opts in.
GMAIL_SEND_FORBIDDEN = True


def gmail_provider() -> str:
    """Resolve the connection provider: env wins, then config, then ``official``."""
    env = os.getenv("GMAIL_MCP_PROVIDER", "").strip().lower()
    if env:
        return env
    cfg = (load_operations_config().get("gmail") or {})
    return str(cfg.get("provider", OFFICIAL)).strip().lower()


def send_allowed() -> bool:
    """Whether Gmail agents may send email. Forbidden by default (drafts only).

    A human can opt in by setting ``gmail.allow_send: true`` in
    ``config/operations.yaml`` AND ``GMAIL_ALLOW_SEND=1`` in the environment.
    """
    if GMAIL_SEND_FORBIDDEN and os.getenv("GMAIL_ALLOW_SEND", "").strip() not in ("1", "true", "yes"):
        return False
    cfg = (load_operations_config().get("gmail") or {})
    return bool(cfg.get("allow_send", False))


def gmail_mcp_servers() -> dict[str, Any]:
    """Return the ``mcp_servers`` mapping for ClaudeAgentOptions (HTTP transport)."""
    provider = gmail_provider()
    if provider == COMPOSIO:
        return _composio_servers()
    if provider == OFFICIAL:
        return _official_servers()
    raise ValueError(
        f"Unknown GMAIL_MCP_PROVIDER '{provider}' (expected '{OFFICIAL}' or '{COMPOSIO}')"
    )


def gmail_allowed_tools() -> list[str]:
    """Tool names to pre-approve for the Gmail MCP server.

    The Claude Agent SDK namespaces MCP tools as ``mcp__<server>__<tool>``. We
    allow the Gmail server namespace so an agent can search, read, label, and
    draft without per-call approval. Agents that compose MUST still avoid send
    tools (see ``send_allowed``); enforce that in the agent's prompt/logic.
    """
    return [f"mcp__{GMAIL_SERVER_NAME}"]


def gmail_is_configured() -> bool:
    """Cheap check for ``company-brain doctor``: are credentials present?"""
    provider = gmail_provider()
    if provider == COMPOSIO:
        return bool(os.getenv("COMPOSIO_API_KEY", "").strip()) and bool(_composio_url())
    if provider == OFFICIAL:
        # Either a ready access token, or an OAuth client to complete the flow.
        return bool(
            os.getenv("GMAIL_OAUTH_ACCESS_TOKEN", "").strip()
            or os.getenv("GMAIL_OAUTH_CLIENT_ID", "").strip()
        )
    return False


# -- official (Google-hosted) ---------------------------------------------------

def _official_servers() -> dict[str, Any]:
    url = os.getenv("GMAIL_MCP_URL", "").strip() or DEFAULT_OFFICIAL_URL
    server: dict[str, Any] = {"type": "http", "url": url}

    token = os.getenv("GMAIL_OAUTH_ACCESS_TOKEN", "").strip()
    if token:
        server["headers"] = {"Authorization": f"Bearer {token}"}
    else:
        logger.warning(
            "GMAIL_OAUTH_ACCESS_TOKEN not set; the official Gmail MCP server needs "
            "an OAuth access token (scopes: gmail.readonly + gmail.compose). "
            "Complete the OAuth flow during setup — see project_install.md."
        )
    return {GMAIL_SERVER_NAME: server}


# -- composio (hosted) ----------------------------------------------------------

def _composio_url() -> str:
    """Return the Composio Gmail MCP URL (explicit env, else mint a session)."""
    url = os.getenv("COMPOSIO_GMAIL_MCP_URL", "").strip()
    if url:
        return url
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        return ""
    return _composio_session_url(api_key)


def _composio_servers() -> dict[str, Any]:
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    url = _composio_url()
    if not url:
        logger.warning(
            "Composio Gmail MCP not configured; set COMPOSIO_API_KEY (+ optionally "
            "COMPOSIO_GMAIL_MCP_URL) — see project_install.md."
        )
    server: dict[str, Any] = {"type": "http", "url": url}
    if api_key:
        server["headers"] = {"x-api-key": api_key}
    return {GMAIL_SERVER_NAME: server}


def _composio_session_url(api_key: str) -> str:
    """Mint a Composio Tool Router session URL scoped to the Gmail toolkit."""
    try:
        from composio import Composio
    except ImportError:
        logger.warning(
            "composio SDK not installed and COMPOSIO_GMAIL_MCP_URL unset; cannot "
            "build a Composio Gmail MCP URL. Set COMPOSIO_GMAIL_MCP_URL or "
            "`pip install composio`."
        )
        return ""
    user_id = os.getenv("COMPOSIO_USER_ID", "company-brain")
    try:
        session = Composio(api_key=api_key).create(user_id=user_id, toolkits=["gmail"])
        return session.mcp.url
    except Exception:
        logger.exception("Failed to mint a Composio Gmail Tool Router session")
        return ""
