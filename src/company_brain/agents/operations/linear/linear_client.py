"""Linear connection layer for the operations department.

Supports three paths (first match wins for issue creation):

1. **GraphQL API** (default) — ``LINEAR_API_KEY`` or ``LINEAR_OAUTH_ACCESS_TOKEN``
   against ``https://api.linear.app/graphql``. Best for deterministic agents
   (inbox_task, team_on_it) with no extra dependencies.
2. **Official MCP** (optional) — HTTP at ``https://mcp.linear.app/mcp`` with the
   same API key as ``Authorization: Bearer …`` for Claude Agent SDK agents.
3. **Community CLI** (optional) — when ``LINEAR_USE_CLI=1`` and a ``linear``
   binary is on ``PATH`` (e.g. joa23/linear-cli), delegate create/update via
   subprocess with ``--output json``.

Docs: https://linear.app/llms.txt · MCP: https://linear.app/docs/mcp.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import requests

LINEAR_SERVER_NAME = "linear"
API_URL = "https://api.linear.app/graphql"
MCP_URL = "https://mcp.linear.app/mcp"

_ISSUE_CREATE = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier url title }
  }
}
"""

_TEAMS = """
query Teams {
  teams { nodes { id key name } }
}
"""


class LinearAPIError(RuntimeError):
    def __init__(self, message: str, *, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


def linear_api_key() -> str:
    return (
        os.getenv("LINEAR_API_KEY", "").strip()
        or os.getenv("LINEAR_OAUTH_ACCESS_TOKEN", "").strip()
    )


def linear_is_configured() -> bool:
    return bool(linear_api_key()) or shutil.which("linear") is not None


def use_cli() -> bool:
    return os.getenv("LINEAR_USE_CLI", "").strip().lower() in ("1", "true", "yes")


def linear_mcp_servers() -> dict[str, Any]:
    """Return ``mcp_servers`` mapping for ClaudeAgentOptions."""
    server: dict[str, Any] = {"type": "http", "url": MCP_URL}
    key = linear_api_key()
    if key:
        server["headers"] = {"Authorization": f"Bearer {key}"}
    return {LINEAR_SERVER_NAME: server}


def linear_allowed_tools() -> list[str]:
    return [f"mcp__{LINEAR_SERVER_NAME}"]


def _auth_header() -> dict[str, str]:
    key = linear_api_key()
    if not key:
        raise RuntimeError("LINEAR_API_KEY not set — see project_install.md")
    if key.startswith("lin_"):
        return {"Authorization": key}
    return {"Authorization": f"Bearer {key}"}


def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = requests.post(
        API_URL,
        headers={**_auth_header(), "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    if resp.status_code >= 400:
        raise LinearAPIError(f"Linear HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    if data.get("errors"):
        raise LinearAPIError("Linear GraphQL error", errors=data["errors"])
    return data.get("data") or {}


def resolve_team_id(*, team_id: str | None = None, team_key: str | None = None) -> str:
    if team_id:
        return team_id
    key = (team_key or "").strip()
    if not key:
        raise RuntimeError("linear.team_id or linear.team_key required in config/operations.yaml")
    data = graphql(_TEAMS)
    for team in data.get("teams", {}).get("nodes") or []:
        if team.get("key", "").lower() == key.lower():
            return team["id"]
    raise LinearAPIError(f"Linear team key '{key}' not found")


def create_issue(
    *,
    title: str,
    description: str,
    team_id: str | None = None,
    team_key: str | None = None,
    priority: int | None = None,
    label_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Linear issue; returns ``{id, identifier, url, title}``."""
    if use_cli() and shutil.which("linear"):
        return _create_issue_cli(title=title, description=description, team_key=team_key)
    tid = resolve_team_id(team_id=team_id, team_key=team_key)
    issue_input: dict[str, Any] = {
        "title": title[:255],
        "description": description,
        "teamId": tid,
    }
    if priority is not None:
        issue_input["priority"] = priority
    if label_ids:
        issue_input["labelIds"] = label_ids
    data = graphql(_ISSUE_CREATE, {"input": issue_input})
    payload = data.get("issueCreate") or {}
    if not payload.get("success"):
        raise LinearAPIError("issueCreate returned success=false")
    issue = payload.get("issue") or {}
    return {
        "id": issue.get("id", ""),
        "identifier": issue.get("identifier", ""),
        "url": issue.get("url", ""),
        "title": issue.get("title", title),
    }


def _create_issue_cli(*, title: str, description: str, team_key: str | None) -> dict[str, Any]:
    cmd = ["linear", "issues", "create", title, "--output", "json", "--no-input"]
    if team_key:
        cmd.extend(["--team", team_key])
    if description:
        cmd.extend(["--description", description])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise LinearAPIError(f"linear CLI failed: {result.stderr[:400] or result.stdout[:400]}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise LinearAPIError(f"linear CLI returned non-JSON: {result.stdout[:200]}") from e
    ident = data.get("identifier") or data.get("id") or ""
    return {
        "id": data.get("id", ""),
        "identifier": ident,
        "url": data.get("url", ""),
        "title": data.get("title", title),
    }
