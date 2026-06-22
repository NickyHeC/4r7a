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
            "number,title,url,author,createdAt,updatedAt,headRefName,baseRefName,"
            "labels,reviewDecision"]
    if repo:
        args.extend(["--repo", repo])
    return gh_json(args)


def default_branch(repo: str) -> str:
    """Return the repo's default branch name (best-effort, 'main' fallback)."""
    try:
        data = gh_json(["repo", "view", repo, "--json", "defaultBranchRef"])
        return (data or {}).get("defaultBranchRef", {}).get("name", "main")
    except GitHubCLIError:
        return "main"


def list_branches(repo: str) -> list[dict[str, Any]]:
    """List branches with their head commit sha (read-only)."""
    try:
        return gh_json(["api", f"repos/{repo}/branches", "--paginate"]) or []
    except GitHubCLIError:
        return []


def compare_branches(repo: str, base: str, head: str) -> dict[str, Any]:
    """Compare two refs. Returns {ahead_by, behind_by, status} or {} on failure.

    ``ahead_by`` = commits ``head`` is ahead of ``base``; ``behind_by`` = commits
    ``head`` is behind ``base``.
    """
    try:
        data = gh_json(["api", f"repos/{repo}/compare/{base}...{head}"])
        if isinstance(data, dict):
            return {
                "ahead_by": data.get("ahead_by", 0),
                "behind_by": data.get("behind_by", 0),
                "status": data.get("status", ""),
            }
    except GitHubCLIError:
        pass
    return {}


def list_deployments(repo: str) -> list[dict[str, Any]]:
    """List recent deployments (best-effort; empty if none/unconfigured)."""
    try:
        return gh_json(["api", f"repos/{repo}/deployments", "--paginate"]) or []
    except GitHubCLIError:
        return []


def list_recent_commits(repo: str | None = None, since: str | None = None) -> list[dict[str, Any]]:
    """List recent commits on the default branch."""
    if not repo:
        return []
    query = f"repos/{repo}/commits"
    if since:
        query += f"?since={since}"
    return gh_json(["api", query, "--paginate"])


def list_repos(org: str | None = None) -> list[dict[str, Any]]:
    """List repositories for the authenticated user or an org."""
    args = ["repo", "list", "--json", "name,url,description,pushedAt,isPrivate"]
    if org:
        args.insert(2, org)
    args.extend(["--limit", "200"])
    return gh_json(args)
