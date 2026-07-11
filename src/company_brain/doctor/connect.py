"""Connectivity doctor — env, tokens, platform auth."""

from __future__ import annotations

import os
import shutil

from company_brain.config import load_config, resolve_llm_provider
from company_brain.doctor.types import CheckResult, DoctorReport


def run_connect_doctor() -> DoctorReport:
    report = DoctorReport(name="connect")

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
            msg = message.replace(" configured", " not configured (optional)")
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
    )

    add("gh_cli", shutil.which("gh") is not None, "GitHub CLI (gh) installed", "install gh")
    add("mercury_token", bool(os.getenv("MERCURY_TOKEN")), "Mercury token set", "set MERCURY_TOKEN")
    add("ramp_token", bool(os.getenv("RAMP_TOKEN")), "Ramp token set", "set RAMP_TOKEN")
    add(
        "slack_token",
        bool(
            os.getenv("SLACK_WIKI_BOT_TOKEN", "").strip()
            or os.getenv("SLACK_BOT_TOKEN", "").strip()
        ),
        "Slack wiki bot token set",
        "set SLACK_WIKI_BOT_TOKEN (legacy: SLACK_BOT_TOKEN)",
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
            )
        else:
            add(
                "granola_connection",
                False,
                "Granola not configured (optional)",
                optional=True,
            )
    except Exception:
        add("granola_connection", False, "Granola check failed", "see project_install.md")

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
                "Google Calendar not configured (optional)",
                optional=True,
            )
    except Exception:
        add("gcal_connection", False, "Google Calendar check failed", "see project_install.md")

    config = load_config()
    add(
        "wiki_initialized",
        config.notion.is_initialized,
        "Wiki initialized in Notion",
        "run 'company-brain init'",
    )

    return report
