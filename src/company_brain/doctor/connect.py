"""Connectivity doctor — env, tokens, platform auth."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from company_brain.config import load_config, resolve_llm_provider
from company_brain.doctor.types import CheckResult, DoctorReport

if TYPE_CHECKING:
    from company_brain.agents.admin.install_profile import InstallProfile


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


def run_connect_doctor(profile: InstallProfile | None = None) -> DoctorReport:
    """Run connect checks.

    When ``profile`` is provided, platforms disabled in the install profile are
    treated as optional so unused stacks do not fail the score.
    """
    report = DoctorReport(name="connect")

    def enabled(platform: str) -> bool:
        if profile is None:
            return True
        return profile.platform_enabled(platform)

    def add(
        check_id: str,
        ok: bool,
        message: str,
        hint: str = "",
        *,
        optional: bool = False,
    ) -> None:
        if optional and not ok:
            status = "pass"
            if " configured" in message:
                msg = message.replace(" configured", " not configured (optional)")
            elif " set" in message:
                msg = message.replace(" set", " not set (optional)")
            elif " installed" in message:
                msg = message.replace(" installed", " not installed (optional)")
            else:
                msg = f"{message} unavailable (optional)"
        else:
            status = "pass" if ok else "warn"
            msg = message
        report.checks.append(CheckResult(check_id, status, msg, hint))

    notion_ok = False
    if shutil.which("ntn"):
        try:
            from company_brain.notion.client import NotionClient

            notion_ok = NotionClient().check_auth()
        except Exception:
            notion_ok = False
    add(
        "notion_cli_auth",
        notion_ok,
        "Notion CLI (ntn) authenticated",
        "install ntn + run 'ntn login', then 'company-brain init'",
        optional=not enabled("notion"),
    )

    add(
        "gh_cli",
        shutil.which("gh") is not None,
        "GitHub CLI (gh) installed",
        "install gh",
        optional=not enabled("github"),
    )
    add(
        "gh_auth",
        _gh_auth_ok(),
        "gh auth status ok",
        "gh auth login",
        optional=not enabled("github"),
    )
    add(
        "mercury_token",
        bool(os.getenv("MERCURY_TOKEN")),
        "Mercury token set",
        "set MERCURY_TOKEN",
        optional=not enabled("mercury"),
    )
    add(
        "ramp_token",
        bool(os.getenv("RAMP_TOKEN")),
        "Ramp token set",
        "set RAMP_TOKEN",
        optional=not enabled("ramp"),
    )
    add(
        "slack_token",
        bool(
            os.getenv("SLACK_WIKI_BOT_TOKEN", "").strip()
            or os.getenv("SLACK_BOT_TOKEN", "").strip()
        ),
        "Slack wiki bot token set",
        "set SLACK_WIKI_BOT_TOKEN (legacy: SLACK_BOT_TOKEN)",
        optional=not enabled("slack"),
    )
    add(
        "slack_weave_token",
        bool(os.getenv("SLACK_WEAVE_BOT_TOKEN", "").strip()),
        "Slack Weave bot token set (optional add-on)",
        "set SLACK_WEAVE_BOT_TOKEN + SLACK_WEAVE_APP_TOKEN for @weave",
        optional=True,
    )

    provider = resolve_llm_provider()
    if provider == "glm":
        add(
            "llm_glm",
            bool(os.getenv("GLM_BASE_URL")),
            "GLM-5 endpoint configured",
            "set GLM_BASE_URL",
        )
    elif provider == "openai":
        add(
            "llm_openai",
            bool(os.getenv("OPENAI_API_KEY")),
            "OpenAI API key set",
            "set OPENAI_API_KEY",
        )
    else:
        add(
            "llm_anthropic",
            bool(os.getenv("ANTHROPIC_API_KEY")),
            "Anthropic API key set",
            "set ANTHROPIC_API_KEY",
        )

    try:
        from company_brain.agents.operations.gmail import gmail_client as gmail

        gmail_ok = gmail.gmail_is_configured()
        gmail_provider = gmail.gmail_provider()
    except Exception:
        gmail_ok, gmail_provider = False, "official"
    add(
        "gmail_connection",
        gmail_ok,
        f"Gmail connection configured ({gmail_provider})",
        "see project_install.md",
        optional=not enabled("gmail"),
    )

    try:
        from company_brain.agents.engineering.linear import linear_client as linear

        linear_ok = linear.check_connection() if linear.linear_is_configured() else False
    except Exception:
        linear_ok = False
    add(
        "linear_connection",
        linear_ok,
        "Linear connection configured",
        "set LINEAR_API_KEY — see project_install.md",
        optional=not enabled("linear"),
    )

    try:
        from company_brain.agents.operations.granola import granola_client as granola_api
        from company_brain.agents.operations.shared import granola_config as granola

        if granola.granola_is_configured():
            granola_ok = granola_api.check_connection()
            granola_mode = granola.granola_mode()
            add(
                "granola_connection",
                granola_ok,
                f"Granola meeting notes ({granola_mode})",
                "set GRANOLA_API_KEY or GRANOLA_MEMBER_KEYS",
                optional=not enabled("granola"),
            )
        else:
            add(
                "granola_connection",
                False,
                "Granola configured",
                optional=True,
            )
    except Exception:
        add(
            "granola_connection",
            False,
            "Granola check failed",
            "see project_install.md",
            optional=not enabled("granola"),
        )

    try:
        from company_brain.agents.operations.gcal import gcal_rest as gcal_api
        from company_brain.agents.operations.shared import gcal_config as gcal

        if gcal.gcal_is_configured():
            add(
                "gcal_connection",
                gcal_api.check_connection(),
                "Google Calendar connection",
                "add calendar scopes to OAuth token",
            )
        else:
            add(
                "gcal_connection",
                False,
                "Google Calendar configured",
                optional=True,
            )
    except Exception:
        add("gcal_connection", False, "Google Calendar check failed", "see project_install.md")

    # Newly covered platforms (profile-aware optionality)
    try:
        from company_brain.agents.product.posthog.posthog_client import posthog_is_configured

        add(
            "posthog_connection",
            posthog_is_configured(),
            "PostHog configured",
            "set POSTHOG_API_KEY / project — see project_install.md",
            optional=not enabled("posthog"),
        )
    except Exception:
        add(
            "posthog_connection",
            False,
            "PostHog check failed",
            optional=not enabled("posthog"),
        )

    try:
        from company_brain.agents.growth.discord.discord_client import discord_is_configured

        add(
            "discord_connection",
            discord_is_configured(),
            "Discord configured",
            "set DISCORD_BOT_TOKEN — see project_install.md",
            optional=not enabled("discord"),
        )
    except Exception:
        add(
            "discord_connection",
            False,
            "Discord check failed",
            optional=not enabled("discord"),
        )

    try:
        from company_brain.agents.growth.google_ads.google_ads_client import (
            google_ads_is_configured,
        )

        add(
            "google_ads_connection",
            google_ads_is_configured(),
            "Google Ads configured",
            "set GOOGLE_ADS_* — see project_install.md",
            optional=not enabled("google_ads"),
        )
    except Exception:
        add(
            "google_ads_connection",
            False,
            "Google Ads check failed",
            optional=not enabled("google_ads"),
        )

    wiki_git_needed = True
    if profile is not None:
        wiki_git_needed = bool(profile.wiki_git_backup)
    add(
        "wiki_git_token",
        bool(os.getenv("COMPANY_BRAIN_WIKI_GIT_TOKEN", "").strip()),
        "COMPANY_BRAIN_WIKI_GIT_TOKEN set",
        "token with contents:write on company-wiki only",
        optional=not wiki_git_needed,
    )

    config = load_config()
    add(
        "wiki_initialized",
        config.notion.is_initialized,
        "Wiki initialized in Notion",
        "run 'company-brain init'",
        optional=profile is not None and not profile.notion_sync,
    )

    lsearch_ok = bool(shutil.which("lsearch") or shutil.which("local-search"))
    add(
        "lsearch_cli",
        lsearch_ok,
        "local-search CLI (lsearch) installed — default web search",
        "cargo install local-search && lsearch launch — see project_install.md",
        optional=True,
    )

    return report
