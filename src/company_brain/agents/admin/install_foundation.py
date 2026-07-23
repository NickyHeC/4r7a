"""Foundation checks for guided install (repos, Notion, wiki_git)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from company_brain.agents.admin.install_profile import (
    InstallProfile,
    load_install_profile,
    save_install_profile,
)
from company_brain.config import load_notion_config


@dataclass
class FoundationCheck:
    check_id: str
    ok: bool
    message: str
    hint: str = ""
    required: bool = True


@dataclass
class FoundationReport:
    checks: list[FoundationCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {
                    "id": c.check_id,
                    "ok": c.ok,
                    "message": c.message,
                    "hint": c.hint,
                    "required": c.required,
                }
                for c in self.checks
            ],
        }


def _gh_auth_ok() -> bool:
    if not shutil.which("gh"):
        return False
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def github_owner_repo(url: str) -> str | None:
    url = (url or "").strip().rstrip("/").removesuffix(".git")
    if "github.com/" not in url:
        return None
    part = url.split("github.com/", 1)[1]
    bits = [b for b in part.split("/") if b]
    if len(bits) < 2:
        return None
    return f"{bits[0]}/{bits[1]}"


def github_owner(url: str) -> str | None:
    slug = github_owner_repo(url)
    return slug.split("/", 1)[0] if slug else None


def _repo_accessible(url: str) -> bool:
    """Best-effort: prefer ``gh`` view for github.com URLs; else non-empty URL."""
    url = (url or "").strip()
    if not url:
        return False
    if "github.com" in url and shutil.which("gh"):
        owner_repo = github_owner_repo(url)
        if owner_repo:
            try:
                proc = subprocess.run(
                    ["gh", "repo", "view", owner_repo, "--json", "name"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                return proc.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                return False
    return True


def ensure_wiki_repo(
    profile: InstallProfile,
    *,
    create: bool = True,
) -> tuple[InstallProfile, FoundationCheck]:
    """Ensure ``wiki_repo_url`` exists; optionally ``gh repo create`` when missing.

    Never overwrites an existing reachable remote. Name defaults to
    ``profile.wiki_repo_name`` (``company-wiki``).
    """
    if not profile.wiki_git_backup:
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            True,
            "wiki_git_backup disabled — skip wiki repo ensure",
            required=False,
        )

    name = (profile.wiki_repo_name or "company-wiki").strip() or "company-wiki"
    url = (profile.wiki_repo_url or "").strip()
    if url and _repo_accessible(url):
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            True,
            f"company-wiki already reachable ({url})",
            required=False,
        )

    owner = github_owner(profile.brain_repo_url) or github_owner(url or "")
    if not owner:
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            False,
            "cannot derive GitHub org/user for company-wiki create",
            hint="set brain_repo_url (or wiki_repo_url) to a github.com URL",
            required=bool(create),
        )

    target = f"{owner}/{name}"
    target_url = f"https://github.com/{target}"

    if _repo_accessible(target_url):
        profile.wiki_repo_url = target_url
        save_install_profile(profile)
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            True,
            f"found existing {target}; wrote wiki_repo_url",
            required=False,
        )

    if not create:
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            False,
            f"{target} missing and create disabled",
            hint="re-run with create enabled or `gh repo create` manually",
            required=True,
        )

    if not _gh_auth_ok():
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            False,
            f"{target} missing; gh auth required to create",
            hint="gh auth login then company-brain install foundation",
            required=True,
        )

    try:
        proc = subprocess.run(
            [
                "gh",
                "repo",
                "create",
                target,
                "--private",
                "--description",
                "company-brain MD wiki backup (admin-only)",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            False,
            f"failed to create {target}: {exc}",
            required=True,
        )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        return profile, FoundationCheck(
            "wiki_repo_ensure",
            False,
            f"gh repo create {target} failed: {err}",
            hint="create the empty private repo manually and set wiki_repo_url",
            required=True,
        )

    profile.wiki_repo_url = target_url
    save_install_profile(profile)
    return profile, FoundationCheck(
        "wiki_repo_ensure",
        True,
        f"created empty private repo {target}",
        required=False,
    )


def run_foundation_checks(
    profile: InstallProfile | None = None,
    *,
    create_wiki_repo: bool = True,
) -> FoundationReport:
    profile = profile or load_install_profile()
    report = FoundationReport()

    def add(
        check_id: str,
        ok: bool,
        message: str,
        hint: str = "",
        *,
        required: bool = True,
    ) -> None:
        report.checks.append(FoundationCheck(check_id, ok, message, hint=hint, required=required))

    add(
        "brain_repo_url",
        bool(profile.brain_repo_url.strip()),
        "Brain (4r7a) repo URL set in install profile",
        "company-brain install profile --brain-repo-url …",
    )
    if profile.brain_repo_url.strip():
        add(
            "brain_repo_access",
            _repo_accessible(profile.brain_repo_url),
            "Brain repo reachable via gh (or URL recorded)",
            "gh auth login; ensure you can view the private 4r7a clone",
            required=False,
        )

    if profile.wiki_git_backup:
        profile, ensure_check = ensure_wiki_repo(profile, create=create_wiki_repo)
        report.checks.append(ensure_check)
        add(
            "wiki_repo_url",
            bool(profile.wiki_repo_url.strip()),
            "company-wiki repo URL set in install profile",
            "set --wiki-repo-url or allow foundation to create company-wiki",
        )
        if profile.wiki_repo_url.strip():
            add(
                "wiki_repo_access",
                _repo_accessible(profile.wiki_repo_url),
                "company-wiki reachable via gh (or URL recorded)",
                "grant COMPANY_BRAIN_WIKI_GIT_TOKEN contents:write on company-wiki only",
                required=False,
            )
        add(
            "wiki_git_token",
            bool(os.getenv("COMPANY_BRAIN_WIKI_GIT_TOKEN", "").strip()),
            "COMPANY_BRAIN_WIKI_GIT_TOKEN set",
            "set token with write access to company-wiki only",
        )
    else:
        add(
            "wiki_git_backup",
            True,
            "wiki_git_backup disabled in profile",
            required=False,
        )

    if profile.platform_enabled("notion") or profile.notion_sync:
        # Keep Notion client imports out of agents/ (wiki doctor: MD-first). Auth
        # depth is covered by `company-brain doctor connect` / `install verify`.
        add(
            "notion_cli_present",
            shutil.which("ntn") is not None,
            "Notion CLI (ntn) installed",
            "install ntn + run ntn login; then company-brain doctor connect",
        )
        notion = load_notion_config()
        add(
            "notion_initialized",
            bool(notion.is_initialized),
            "Wiki initialized (notion.yaml root_page_id)",
            "run company-brain init",
            required=profile.notion_sync,
        )
        teamspaces = getattr(notion, "teamspaces", None) or {}
        if isinstance(teamspaces, dict):
            admin_parent = str(teamspaces.get("admin") or "").strip()
            company_parent = str(teamspaces.get("company") or "").strip()
        else:
            admin_parent = company_parent = ""
        add(
            "notion_teamspaces",
            bool(admin_parent or company_parent or not profile.notion_sync),
            "Notion teamspace parents configured (or sync off)",
            "set config/notion.yaml teamspaces.admin / teamspaces.company",
            required=False,
        )
    else:
        add("notion", True, "Notion disabled in profile", required=False)

    if profile.platform_enabled("github"):
        add(
            "gh_cli",
            shutil.which("gh") is not None,
            "GitHub CLI (gh) installed",
            "install gh from https://cli.github.com/",
        )
        add(
            "gh_auth",
            _gh_auth_ok(),
            "gh auth status ok",
            "gh auth login",
            required=False,
        )

    from company_brain.config import resolve_wiki_dir

    try:
        wiki_dir = resolve_wiki_dir()
        wiki_ok = wiki_dir is not None
    except Exception:
        wiki_ok = False
    add(
        "wiki_dir",
        wiki_ok,
        "Wiki directory resolved",
        "set COMPANY_BRAIN_WIKI_DIR if needed",
        required=False,
    )

    return report


def format_foundation_report(report: FoundationReport) -> str:
    lines = ["# Foundation checks", f"overall: {'ok' if report.ok else 'needs attention'}", ""]
    for c in report.checks:
        mark = "PASS" if c.ok else "FAIL"
        req = "required" if c.required else "optional"
        lines.append(f"- [{mark}] ({req}) {c.check_id}: {c.message}")
        if c.hint and not c.ok:
            lines.append(f"    hint: {c.hint}")
    lines.append("")
    return "\n".join(lines)
