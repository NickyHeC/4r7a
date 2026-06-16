"""Thin wrapper around the GitHub CLI for read-only operations."""

from __future__ import annotations

import json
import subprocess
from typing import Any


class GitHubCLIError(Exception):
    pass


def gh_json(args: list[str]) -> Any:
    """Run a `gh` command and return parsed JSON output.

    All calls are read-only. Never pass flags that mutate state.
    """
    cmd = ["gh", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitHubCLIError(f"gh failed ({result.returncode}): {result.stderr.strip()}")
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def list_open_prs(repo: str | None = None) -> list[dict[str, Any]]:
    """List open pull requests with key metadata."""
    args = ["pr", "list", "--state", "open", "--json",
            "number,title,url,author,createdAt,headRefName,labels,reviewDecision"]
    if repo:
        args.extend(["--repo", repo])
    return gh_json(args)


def list_recent_commits(repo: str | None = None, since: str | None = None) -> list[dict[str, Any]]:
    """List recent commits on the default branch."""
    args = ["api", f"repos/{repo}/commits" if repo else "repos/{owner}/{repo}/commits"]
    if repo:
        args = ["api", f"repos/{repo}/commits", "--paginate", "--jq", ".[]"]
        endpoint = f"repos/{repo}/commits"
        params = []
        if since:
            params.append(f"since={since}")
        query = f"{endpoint}{'?' + '&'.join(params) if params else ''}"
        return gh_json(["api", query, "--paginate"])
    return []


def list_repos(org: str | None = None) -> list[dict[str, Any]]:
    """List repositories for the authenticated user or an org."""
    args = ["repo", "list", "--json", "name,url,description,pushedAt,isPrivate"]
    if org:
        args.insert(2, org)
    args.extend(["--limit", "200"])
    return gh_json(args)
