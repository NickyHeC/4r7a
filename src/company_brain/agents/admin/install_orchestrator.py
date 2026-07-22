"""Install orchestrator — foundation-aware department onboarding sequence.

Dispatches existing platform onboarding agents via ``get_runtime().run``.
Does not provision external resources. Cleanup never deletes without confirm.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from company_brain.agents.admin.install_foundation import (
    format_foundation_report,
    run_foundation_checks,
)
from company_brain.agents.admin.install_profile import (
    DEPARTMENT_ORDER,
    FOUNDATION_PLATFORMS,
    InstallProfile,
    load_install_profile,
)
from company_brain.agents.base import BaseAgent
from company_brain.agents.gates import StateStore
from company_brain.runtime import get_runtime
from company_brain.wiki.publish import UPDATE, write_wiki_page

PROGRESS_PATH = "admin/install-progress.md"
PROGRESS_TITLE = "Install Progress"
WRITE_MODE = UPDATE

# department -> ordered platform keys for onboarding (excluding foundation notion)
ONBOARD_SEQUENCE: dict[str, tuple[str, ...]] = {
    "engineering": ("github", "linear"),
    "operations": ("slack", "gmail", "granola"),
    "product": ("posthog", "product_workstreams"),
    "growth": ("google_ads", "discord", "growth_workstreams"),
    "finance": ("mercury",),
    "hr": ("linkedin",),
}


def _configured_check(platform: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means skip as not_configured."""
    try:
        if platform == "github":
            import shutil

            return (shutil.which("gh") is not None, "gh missing")
        if platform == "linear":
            from company_brain.agents.engineering.linear import linear_client as linear

            return (linear.linear_is_configured(), "LINEAR_API_KEY unset")
        if platform == "slack":
            from company_brain.agents.operations.slack.slack_config import slack_is_configured

            return (slack_is_configured(), "Slack wiki bot token unset")
        if platform == "gmail":
            from company_brain.agents.operations.gmail import gmail_client as gmail

            return (gmail.gmail_is_configured(), "Gmail OAuth unset")
        if platform == "granola":
            from company_brain.agents.operations.shared import granola_config as granola

            return (granola.granola_is_configured(), "Granola keys unset")
        if platform == "posthog":
            from company_brain.agents.product.posthog import posthog_client as ph_client
            from company_brain.agents.product.posthog import posthog_config as ph_cfg

            if not ph_cfg.enabled():
                return (False, "posthog disabled in product.yaml")
            return (ph_client.posthog_is_configured(), "POSTHOG_* unset")
        if platform == "google_ads":
            from company_brain.agents.growth.google_ads.google_ads_client import (
                google_ads_is_configured,
            )

            return (google_ads_is_configured(), "Google Ads not configured")
        if platform == "discord":
            from company_brain.agents.growth.discord.discord_client import (
                discord_is_configured,
            )

            return (discord_is_configured(), "Discord not configured")
        if platform == "mercury":
            import os

            return (bool(os.getenv("MERCURY_TOKEN", "").strip()), "MERCURY_TOKEN unset")
        if platform in ("product_workstreams", "growth_workstreams", "linkedin", "ramp"):
            return (True, "")
    except Exception as exc:
        return (False, f"config check failed: {exc}")
    return (True, "")


def _onboarding_runner(platform: str) -> Callable[..., Any] | None:
    """Return a callable(config, **kwargs) -> result dict using runtime.run."""

    def _run(agent_cls: type, config: Any, **kwargs: Any) -> Any:
        return get_runtime().run(agent_cls, config, **kwargs)

    mapping: dict[str, Callable[[Any], Any]] = {}

    def github(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.engineering.github.github_onboarding import (
            GitHubOnboardingAgent,
        )

        return _run(
            GitHubOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def linear(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.engineering.linear.linear_onboarding import (
            LinearOnboardingAgent,
        )

        return _run(
            LinearOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def slack(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.operations.slack.slack_onboarding import SlackOnboardingAgent

        return _run(
            SlackOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def gmail(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.operations.gmail.gmail_onboarding import GmailOnboardingAgent

        return _run(
            GmailOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def granola(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.operations.granola.granola_onboarding import (
            GranolaOnboardingAgent,
        )

        return _run(
            GranolaOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def posthog(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.product.posthog.posthog_onboarding import (
            PosthogOnboardingAgent,
        )

        return _run(
            PosthogOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def product_workstreams(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.product.product_onboarding import ProductOnboardingAgent

        return _run(
            ProductOnboardingAgent,
            config,
            start_managers=kwargs.get("start_manager", True),
        )

    def google_ads(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.growth.google_ads.google_ads_onboarding import (
            GoogleAdsOnboardingAgent,
        )

        return _run(
            GoogleAdsOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def discord(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.growth.discord.discord_onboarding import (
            DiscordOnboardingAgent,
        )

        return _run(
            DiscordOnboardingAgent,
            config,
            start_manager=kwargs.get("start_manager", True),
        )

    def growth_workstreams(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.growth.growth_onboarding import GrowthOnboardingAgent

        return _run(
            GrowthOnboardingAgent,
            config,
            start_managers=kwargs.get("start_manager", True),
        )

    def mercury(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.finance.finance_onboarding import FinanceOnboardingAgent

        return _run(
            FinanceOnboardingAgent,
            config,
            start_managers=kwargs.get("start_manager", True),
        )

    def linkedin(config: Any, **kwargs: Any) -> Any:
        from company_brain.agents.hr.hr_onboarding import HrOnboardingAgent

        return _run(
            HrOnboardingAgent,
            config,
            seed=True,
            start_manager=kwargs.get("start_manager", True),
        )

    mapping = {
        "github": github,
        "linear": linear,
        "slack": slack,
        "gmail": gmail,
        "granola": granola,
        "posthog": posthog,
        "product_workstreams": product_workstreams,
        "google_ads": google_ads,
        "discord": discord,
        "growth_workstreams": growth_workstreams,
        "mercury": mercury,
        "linkedin": linkedin,
    }
    return mapping.get(platform)


def _state_key(phase: str, platform: str) -> str:
    return f"install:{phase}:{platform}"


def record_install_state(phase: str, platform: str, status: str, detail: str = "") -> None:
    store = StateStore()
    store.set(
        _state_key(phase, platform),
        {
            "status": status,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )


def read_install_states() -> dict[str, Any]:
    store = StateStore()
    out: dict[str, Any] = {}
    for key in store.keys():
        if str(key).startswith("install:"):
            out[str(key)] = store.get(key)
    return out


def cleanup_checklist(profile: InstallProfile | None = None) -> str:
    """Human/coding-agent checklist — never auto-deletes."""
    profile = profile or load_install_profile()
    disabled = profile.disabled_platforms()
    lines = [
        "# Post-install cleanup checklist",
        "",
        "Nothing below is deleted automatically. Confirm each step with the admin.",
        "",
        "## Disabled platforms (skip only unless admin confirms removal)",
        "",
    ]
    if not disabled:
        lines.append("- (none — all known platforms enabled)")
    else:
        for name in disabled:
            lines.append(f"- [ ] Confirm keep-disabled vs remove from private fork: `{name}`")
        lines.extend(
            [
                "",
                "If admin confirms removal from **this company's private fork**:",
                "1. List packages under `src/company_brain/agents/<dept>/<platform>/`",
                "2. Remove handbook rows + CLI registration + Smolfile hosts for that platform",
                "3. Run `ruff check .`, `pytest -q`, `company-brain doctor code`",
                "4. Do **not** push destructive cleanup to public upstream without a PR review",
            ]
        )
    lines.extend(
        [
            "",
            "## Steady-state starts (when enabled)",
            "",
            "- [ ] `company-brain admin wiki-commit --loop` (if wiki_git_backup)",
            "- [ ] `company-brain admin manager --loop`",
            "- [ ] `company-brain slack events` (if Slack enabled)",
            "- [ ] `company-brain discord gateway` (if Discord enabled)",
            "- [ ] `company-brain catalog`",
            "- [ ] `company-brain doctor all`",
            "",
        ]
    )
    return "\n".join(lines)


class InstallOrchestratorAgent(BaseAgent):
    """One-shot department onboarding sequencer driven by install_profile."""

    name = "install_orchestrator"
    WRITE_MODE = WRITE_MODE
    track_duration = False

    def run(
        self,
        *,
        strict: bool = False,
        start_managers: bool = True,
        skip_foundation_check: bool = False,
        departments: list[str] | None = None,
        confirm_cleanup: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        profile = load_install_profile()
        results: list[dict[str, Any]] = []

        if not skip_foundation_check:
            foundation = run_foundation_checks(profile)
            if not foundation.ok:
                body = format_foundation_report(foundation)
                self._write_progress(body, results=[])
                if strict:
                    return {
                        "status": "foundation_failed",
                        "foundation": foundation.to_dict(),
                        "results": [],
                    }
                results.append(
                    {
                        "phase": "foundation",
                        "platform": "foundation",
                        "status": "warn",
                        "detail": "foundation checks incomplete; continuing",
                    }
                )

        # Optional Notion foundation onboard when enabled and not already done
        if profile.platform_enabled("notion"):
            results.append(self._run_notion_foundation(start_managers=start_managers))

        dept_list = departments or profile.department_onboarding_order()
        for dept in DEPARTMENT_ORDER:
            if dept not in dept_list:
                continue
            if not profile.department_enabled(dept):
                results.append(
                    {
                        "phase": "department",
                        "platform": dept,
                        "status": "skipped",
                        "detail": "department disabled",
                    }
                )
                continue
            for platform in ONBOARD_SEQUENCE.get(dept, ()):
                if platform in FOUNDATION_PLATFORMS:
                    continue
                if not profile.platform_enabled(platform):
                    record_install_state("onboard", platform, "skipped", "disabled in profile")
                    results.append(
                        {
                            "phase": "onboard",
                            "platform": platform,
                            "status": "skipped",
                            "detail": "disabled in profile",
                        }
                    )
                    continue
                ok, reason = _configured_check(platform)
                if not ok:
                    record_install_state("onboard", platform, "skipped", reason)
                    results.append(
                        {
                            "phase": "onboard",
                            "platform": platform,
                            "status": "skipped",
                            "detail": reason,
                        }
                    )
                    continue
                runner = _onboarding_runner(platform)
                if runner is None:
                    results.append(
                        {
                            "phase": "onboard",
                            "platform": platform,
                            "status": "skipped",
                            "detail": "no onboarding runner",
                        }
                    )
                    continue
                try:
                    out = runner(self.config, start_manager=start_managers)
                    status = "ok"
                    if isinstance(out, dict):
                        status = str(out.get("status") or "ok")
                    record_install_state("onboard", platform, status, str(out)[:500])
                    results.append(
                        {
                            "phase": "onboard",
                            "platform": platform,
                            "status": status,
                            "detail": out if isinstance(out, dict) else {"result": out},
                        }
                    )
                    if strict and status in {"error", "failed", "not_configured"}:
                        self._write_progress("", results=results)
                        return {
                            "status": "stopped",
                            "strict": True,
                            "failed_platform": platform,
                            "results": results,
                        }
                except Exception as exc:
                    record_install_state("onboard", platform, "error", str(exc))
                    results.append(
                        {
                            "phase": "onboard",
                            "platform": platform,
                            "status": "error",
                            "detail": str(exc),
                        }
                    )
                    if strict:
                        self._write_progress("", results=results)
                        return {
                            "status": "stopped",
                            "strict": True,
                            "failed_platform": platform,
                            "results": results,
                        }

        cleanup = cleanup_checklist(profile)
        if confirm_cleanup:
            cleanup_note = (
                "Admin confirmed cleanup review — follow checklist; "
                "still no automatic file deletion."
            )
        else:
            cleanup_note = (
                "Cleanup not confirmed. Re-run with --confirm-cleanup after admin approval "
                "before removing unused platforms/departments from a private fork."
            )
        self._write_progress(cleanup + "\n\n_" + cleanup_note + "_\n", results=results)
        return {
            "status": "ok",
            "results": results,
            "cleanup_confirmed": bool(confirm_cleanup),
            "wiki_path": PROGRESS_PATH,
        }

    def _run_notion_foundation(self, *, start_managers: bool) -> dict[str, Any]:
        try:
            from company_brain.agents.operations.notion.notion_onboarding import (
                NotionOnboardingAgent,
            )

            out = get_runtime().run(
                NotionOnboardingAgent,
                self.config,
                start_manager=start_managers,
                confirm_mirror=True,
            )
            status = str(out.get("status") if isinstance(out, dict) else "ok")
            record_install_state("foundation", "notion", status)
            return {
                "phase": "foundation",
                "platform": "notion",
                "status": status,
                "detail": out if isinstance(out, dict) else {},
            }
        except Exception as exc:
            record_install_state("foundation", "notion", "error", str(exc))
            return {
                "phase": "foundation",
                "platform": "notion",
                "status": "error",
                "detail": str(exc),
            }

    def _write_progress(self, cleanup_md: str, *, results: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# {PROGRESS_TITLE}",
            "",
            f"_Updated {now}_",
            "",
            "## Onboarding results",
            "",
            "| Phase | Platform | Status | Detail |",
            "|-------|----------|--------|--------|",
        ]
        for row in results:
            detail = row.get("detail")
            if isinstance(detail, dict):
                detail_s = str(detail.get("status") or detail)[:80]
            else:
                detail_s = str(detail)[:80].replace("|", "/")
            lines.append(
                f"| {row.get('phase')} | {row.get('platform')} | {row.get('status')} | {detail_s} |"
            )
        lines.append("")
        if cleanup_md:
            lines.append(cleanup_md)
        body = "\n".join(lines)
        write_wiki_page(
            PROGRESS_PATH,
            PROGRESS_TITLE,
            body,
            mode=WRITE_MODE,
            section="admin",
            type_="page",
            extra_frontmatter={"sync": "admin_only"},
            sync=False,
        )
