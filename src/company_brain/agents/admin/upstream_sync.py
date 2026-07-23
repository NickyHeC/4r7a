"""Upstream Sync — monthly filtered PR from public 4r7a into the private company fork.

Fetches the public upstream, keeps always-safe core paths plus paths for platforms
enabled in ``install_profile.yaml``, and opens a **draft** PR for admin review.
Never auto-merges. Weave never targets the public upstream.

SDK: Neither (git + gh orchestration).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.agents.admin.install_profile import InstallProfile, load_install_profile
from company_brain.agents.admin.llm_ops_config import load_operations_raw
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.config import PROJECT_ROOT

STATE_MONTH_KEY = "admin_manager:upstream_sync:{month}"

DEFAULT_UPSTREAM = "https://github.com/4r7a/4r7a.git"

# Paths always considered for upstream sync (shared runtime / wiki core).
ALWAYS_SAFE_PREFIXES: tuple[str, ...] = (
    "src/company_brain/runtime/",
    "src/company_brain/wiki/",
    "src/company_brain/agents/base.py",
    "src/company_brain/agents/gates.py",
    "src/company_brain/agents/result.py",
    "src/company_brain/config.py",
    "src/company_brain/notify/",
    "src/company_brain/llm/",
    "docs/design_process.md",
    "docs/hygiene_checklist.md",
    "docs/doc_style.md",
    ".cursor/rules/",
)

# Platform key → path prefixes to include when that platform is enabled.
PLATFORM_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "github": ("src/company_brain/agents/engineering/github/",),
    "linear": ("src/company_brain/agents/engineering/linear/",),
    "notion": (
        "src/company_brain/agents/operations/notion/",
        "src/company_brain/notion/",
    ),
    "slack": ("src/company_brain/agents/operations/slack/",),
    "gmail": ("src/company_brain/agents/operations/gmail/",),
    "granola": ("src/company_brain/agents/operations/granola/",),
    "posthog": ("src/company_brain/agents/product/posthog/",),
    "product_workstreams": (
        "src/company_brain/agents/product/update/",
        "src/company_brain/agents/product/use_case/",
        "src/company_brain/agents/product/docs/",
        "src/company_brain/agents/product/progress/",
        "src/company_brain/agents/product/attribution/",
    ),
    "google_ads": ("src/company_brain/agents/growth/google_ads/",),
    "discord": ("src/company_brain/agents/growth/discord/",),
    "growth_workstreams": (
        "src/company_brain/agents/growth/activity/",
        "src/company_brain/agents/growth/content/",
        "src/company_brain/agents/growth/competitor/",
        "src/company_brain/agents/growth/leads/",
    ),
    "mercury": ("src/company_brain/agents/finance/mercury/",),
    "ramp": ("src/company_brain/agents/finance/ramp/",),
    "linkedin": ("src/company_brain/agents/hr/linkedin/",),
}


def upstream_sync_config() -> dict[str, Any]:
    raw = (load_operations_raw().get("admin") or {}).get("upstream_sync") or {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "day": int(raw.get("day") or 15),
        "time": str(raw.get("time") or "10:00"),
        "upstream_repo": str(raw.get("upstream_repo") or DEFAULT_UPSTREAM).strip(),
        "draft": bool(raw.get("draft", True)),
        "always_safe_paths": list(raw.get("always_safe_paths") or ALWAYS_SAFE_PREFIXES),
    }


def github_slug_from_url(url: str) -> str | None:
    url = (url or "").strip().rstrip("/").removesuffix(".git")
    if "github.com/" not in url:
        return None
    part = url.split("github.com/", 1)[1]
    bits = [b for b in part.split("/") if b]
    if len(bits) < 2:
        return None
    return f"{bits[0]}/{bits[1]}"


def allowed_path_prefixes(
    profile: InstallProfile | None = None,
    *,
    always_safe: list[str] | None = None,
) -> list[str]:
    profile = profile or load_install_profile()
    prefixes = list(always_safe or ALWAYS_SAFE_PREFIXES)
    for platform in profile.enabled_platforms():
        prefixes.extend(PLATFORM_PATH_PREFIXES.get(platform) or ())
    # Dedup preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in prefixes:
        p = p.replace("\\", "/").lstrip("./")
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def path_allowed(path: str, prefixes: list[str]) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    for pref in prefixes:
        if path == pref.rstrip("/") or path.startswith(pref):
            return True
    return False


def filter_changed_paths(paths: list[str], prefixes: list[str]) -> list[str]:
    return sorted({p for p in paths if path_allowed(p, prefixes)})


def _run(cmd: list[str], *, cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


class UpstreamSyncAgent(BaseAgent):
    """Open a draft PR with platform-filtered upstream changes."""

    name = "upstream_sync"
    track_duration = True

    def run(self, *, force: bool = False, **kwargs: Any) -> dict[str, Any]:
        cfg = upstream_sync_config()
        if not cfg["enabled"] and not force:
            return {"status": "skipped", "reason": "disabled"}

        month = _month_key()
        store = StateStore()
        key = STATE_MONTH_KEY.format(month=month)
        if store.get(key) and not force:
            return {"status": "skipped", "reason": "already_ran", "month": month}

        profile = load_install_profile()
        brain_url = (profile.brain_repo_url or "").strip() or os.getenv("WEAVE_GITHUB_REPO", "")
        # WEAVE_GITHUB_REPO may already be owner/repo
        target_slug = github_slug_from_url(brain_url) if "github.com" in brain_url else None
        if not target_slug and "/" in brain_url and "://" not in brain_url:
            target_slug = brain_url.strip()
        if not target_slug:
            # Fall back to current checkout remote
            target_slug = _origin_slug(PROJECT_ROOT)
        if not target_slug:
            return {
                "status": "failed",
                "reason": "no_brain_repo",
                "hint": "set install_profile.brain_repo_url or WEAVE_GITHUB_REPO",
            }

        prefixes = allowed_path_prefixes(
            profile,
            always_safe=[str(p) for p in cfg["always_safe_paths"]],
        )
        upstream = cfg["upstream_repo"]

        with tempfile.TemporaryDirectory(prefix="upstream_sync_") as tmp:
            work = Path(tmp) / "repo"
            clone = _run(
                ["gh", "repo", "clone", target_slug, str(work), "--", "--depth", "1"],
                cwd=Path(tmp),
            )
            if clone.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "clone_failed",
                    "stderr": (clone.stderr or "")[:500],
                }

            _run(["git", "remote", "add", "upstream", upstream], cwd=work)
            fetch = _run(["git", "fetch", "upstream", "--depth", "1"], cwd=work)
            if fetch.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "fetch_upstream_failed",
                    "stderr": (fetch.stderr or "")[:500],
                }

            base = _default_branch(work, target_slug)
            diff = _run(
                ["git", "diff", "--name-only", f"origin/{base}", "upstream/HEAD"],
                cwd=work,
            )
            if diff.returncode != 0:
                # shallow clone may lack origin/base — try HEAD vs upstream
                diff = _run(
                    ["git", "diff", "--name-only", "HEAD", "upstream/HEAD"],
                    cwd=work,
                )
            all_paths = [p.strip() for p in (diff.stdout or "").splitlines() if p.strip()]
            selected = filter_changed_paths(all_paths, prefixes)
            if not selected:
                store.set(key, {"at": datetime.now(timezone.utc).isoformat(), "paths": 0})
                return {
                    "status": "ok",
                    "action": "noop",
                    "month": month,
                    "changed_upstream": len(all_paths),
                    "selected": 0,
                }

            branch = f"upstream-sync/{month}-{datetime.now(timezone.utc).strftime('%d%H%M')}"
            _run(["git", "checkout", "-b", branch], cwd=work)
            # Checkout selected paths from upstream
            checkout = _run(["git", "checkout", "upstream/HEAD", "--", *selected], cwd=work)
            if checkout.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "checkout_paths_failed",
                    "stderr": (checkout.stderr or "")[:500],
                    "selected": selected,
                }
            _run(["git", "add", "-A"], cwd=work)
            commit = _run(
                [
                    "git",
                    "-c",
                    "user.email=upstream-sync@4r7a.local",
                    "-c",
                    "user.name=upstream_sync",
                    "commit",
                    "-m",
                    f"chore: upstream sync {month} (filtered)",
                ],
                cwd=work,
            )
            if commit.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "commit_failed",
                    "stderr": (commit.stderr or "")[:500],
                }
            push = _run(["git", "push", "-u", "origin", branch], cwd=work)
            if push.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "push_failed",
                    "stderr": (push.stderr or "")[:500],
                }

            from company_brain.agents.engineering.github.gh import create_pull_request

            body = (
                "## Upstream sync (filtered)\n\n"
                f"Month: `{month}`\n"
                f"Upstream: `{upstream}`\n"
                f"Selected paths ({len(selected)}):\n\n"
                + "\n".join(f"- `{p}`" for p in selected[:80])
                + ("\n- …" if len(selected) > 80 else "")
                + "\n\nAdmin: resolve conflicts, review relevance, merge when ready. "
                "Never auto-merged.\n"
            )
            try:
                pr = create_pull_request(
                    title=f"Upstream sync {month}",
                    body=body,
                    head=branch,
                    base=base,
                    repo=target_slug,
                    draft=bool(cfg["draft"]),
                )
                pr_url = str((pr or {}).get("url") or "")
            except Exception as exc:
                return {
                    "status": "failed",
                    "reason": "pr_failed",
                    "error": str(exc)[:300],
                    "branch": branch,
                    "selected": selected,
                }

        store.set(
            key,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "paths": len(selected),
                "pr_url": pr_url,
            },
        )
        return {
            "status": "ok",
            "action": "pr_opened",
            "month": month,
            "pr_url": pr_url,
            "branch": branch,
            "selected": selected,
            "changed_upstream": len(all_paths),
        }


def _origin_slug(repo_root: Path) -> str | None:
    proc = _run(["git", "remote", "get-url", "origin"], cwd=repo_root)
    if proc.returncode != 0:
        return None
    return github_slug_from_url((proc.stdout or "").strip())


def _default_branch(work: Path, slug: str) -> str:
    from company_brain.agents.engineering.github.gh import default_branch

    try:
        return default_branch(slug)
    except Exception:
        proc = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=work)
        name = (proc.stdout or "").strip()
        return name if name and name != "HEAD" else "main"


def sanitize_branch_component(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._/-]+", "-", raw).strip("-") or "sync"
