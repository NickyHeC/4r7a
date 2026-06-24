"""Linear connection layer for the engineering department.

Supports three paths (CLI preferred when ``LINEAR_USE_CLI=1`` and the binary is
on ``PATH``; otherwise GraphQL is default):

1. **GraphQL API** (default) — ``LINEAR_API_KEY`` or ``LINEAR_OAUTH_ACCESS_TOKEN``
   against ``https://api.linear.app/graphql``. Best for deterministic agents.
2. **Official MCP** (optional) — HTTP at ``https://mcp.linear.app/mcp`` with the
   same API key as ``Authorization: Bearer …`` for Claude Agent SDK agents.
3. **Community CLI** (optional) — when ``LINEAR_USE_CLI=1`` and a ``linear``
   binary is on ``PATH`` (e.g. [joa23/linear-cli](https://github.com/joa23/linear-cli)),
   delegate reads/writes via subprocess with ``--output json``.

Docs index: https://linear.app/llms.txt · GraphQL: https://linear.app/developers/graphql
· MCP: https://linear.app/docs/mcp.md
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

_VIEWER = """
query Viewer {
  viewer { id name email }
}
"""

_TEAMS = """
query Teams {
  teams { nodes { id key name } }
}
"""

_ISSUES = """
query Issues($filter: IssueFilter, $first: Int) {
  issues(filter: $filter, first: $first) {
    nodes { id identifier url title state { name } priority priorityLabel updatedAt }
  }
}
"""

_ISSUE = """
query Issue($id: String!) {
  issue(id: $id) {
    id identifier url title description
    state { name } priority priorityLabel updatedAt
  }
}
"""

_ISSUE_CREATE = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier url title }
  }
}
"""


class LinearAPIError(RuntimeError):
    def __init__(self, message: str, *, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class LinearCLIError(RuntimeError):
    pass


def linear_api_key() -> str:
    return (
        os.getenv("LINEAR_API_KEY", "").strip()
        or os.getenv("LINEAR_OAUTH_ACCESS_TOKEN", "").strip()
    )


def cli_available() -> bool:
    return shutil.which("linear") is not None


def linear_is_configured() -> bool:
    return bool(linear_api_key()) or cli_available()


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


def check_connection() -> bool:
    """Best-effort connectivity check for ``doctor`` (GraphQL viewer or CLI teams)."""
    if use_cli() and cli_available():
        try:
            _run_cli(["teams", "list", "--output", "json"])
            return True
        except LinearCLIError:
            pass
    if not linear_api_key():
        return False
    try:
        viewer()
        return True
    except (LinearAPIError, RuntimeError):
        return False


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


def _run_cli(args: list[str], *, timeout: int = 120) -> Any:
    cmd = ["linear", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise LinearCLIError(
            f"linear CLI failed ({result.returncode}): "
            f"{result.stderr[:400] or result.stdout[:400]}"
        )
    out = result.stdout.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def viewer() -> dict[str, Any]:
    """Return the authenticated Linear user (GraphQL only)."""
    data = graphql(_VIEWER)
    return data.get("viewer") or {}


def list_teams() -> list[dict[str, Any]]:
    """List workspace teams (CLI when enabled, else GraphQL)."""
    if use_cli() and cli_available():
        data = _run_cli(["teams", "list", "--output", "json"])
        if isinstance(data, list):
            return data
        return data.get("teams") or data.get("nodes") or []
    data = graphql(_TEAMS)
    return data.get("teams", {}).get("nodes") or []


def resolve_team_id(*, team_id: str | None = None, team_key: str | None = None) -> str:
    if team_id:
        return team_id
    key = (team_key or "").strip()
    if not key:
        raise RuntimeError("linear.team_id or linear.team_key required in config/engineering.yaml")
    for team in list_teams():
        if team.get("key", "").lower() == key.lower():
            return team["id"]
    raise LinearAPIError(f"Linear team key '{key}' not found")


def list_issues(
    *,
    team_id: str | None = None,
    team_key: str | None = None,
    first: int = 50,
) -> list[dict[str, Any]]:
    """List issues for a team (GraphQL; read-only)."""
    if use_cli() and cli_available():
        args = ["issues", "list", "--output", "json", "--limit", str(first)]
        if team_key:
            args.extend(["--team", team_key])
        data = _run_cli(args)
        if isinstance(data, list):
            return data
        return data.get("issues") or data.get("nodes") or []
    tid = resolve_team_id(team_id=team_id, team_key=team_key) if (team_id or team_key) else None
    issue_filter: dict[str, Any] = {}
    if tid:
        issue_filter["team"] = {"id": {"eq": tid}}
    data = graphql(_ISSUES, {"filter": issue_filter or None, "first": first})
    return data.get("issues", {}).get("nodes") or []


def get_issue(issue_id: str) -> dict[str, Any]:
    """Fetch one issue by UUID or identifier (e.g. ENG-123). GraphQL only."""
    data = graphql(_ISSUE, {"id": issue_id})
    issue = data.get("issue")
    if not issue:
        raise LinearAPIError(f"Issue '{issue_id}' not found")
    return issue


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
    if use_cli() and cli_available():
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
    cmd = ["issues", "create", title, "--output", "json", "--no-input"]
    if team_key:
        cmd.extend(["--team", team_key])
    if description:
        cmd.extend(["--description", description])
    data = _run_cli(cmd)
    if isinstance(data, dict):
        ident = data.get("identifier") or data.get("id") or ""
        return {
            "id": data.get("id", ""),
            "identifier": ident,
            "url": data.get("url", ""),
            "title": data.get("title", title),
        }
    raise LinearAPIError(f"linear CLI returned unexpected payload: {data!r}")
