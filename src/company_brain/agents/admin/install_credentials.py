"""Profile-scoped credential / OAuth checklist for guided install."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from company_brain.agents.admin.install_profile import InstallProfile, load_install_profile


@dataclass(frozen=True)
class CredentialItem:
    key: str
    kind: str  # env | cli_login | oauth | repo
    label: str
    platforms: tuple[str, ...]
    required: bool = True
    hint: str = ""

    def present(self) -> bool:
        if self.kind == "env":
            return bool(os.getenv(self.key, "").strip())
        if self.kind == "cli_login":
            # Presence of the CLI binary / shallow check is done in foundation verify.
            return True
        if self.kind == "repo":
            return bool(self.key.strip())
        return False


# Always needed for a working install (LLM + wiki volume).
_CORE: tuple[CredentialItem, ...] = (
    CredentialItem(
        "COMPANY_BRAIN_LLM_PROVIDER",
        "env",
        "LLM provider knob",
        (),
        required=False,
        hint="anthropic | openai | glm (default anthropic)",
    ),
    CredentialItem(
        "ANTHROPIC_API_KEY",
        "env",
        "Anthropic API key",
        (),
        required=False,
        hint="Required when COMPANY_BRAIN_LLM_PROVIDER=anthropic",
    ),
    CredentialItem(
        "OPENAI_API_KEY",
        "env",
        "OpenAI API key",
        (),
        required=False,
        hint="Required when provider=openai or Weave Codex builder",
    ),
)

_BY_PLATFORM: dict[str, tuple[CredentialItem, ...]] = {
    "notion": (
        CredentialItem(
            "ntn",
            "cli_login",
            "Notion CLI login (`ntn login`)",
            ("notion",),
            hint="install ntn, then ntn login; run company-brain init",
        ),
    ),
    "github": (
        CredentialItem(
            "gh",
            "cli_login",
            "GitHub CLI auth (`gh auth login`)",
            ("github",),
            hint="install gh; authenticate against the org that owns product repos",
        ),
    ),
    "linear": (
        CredentialItem(
            "LINEAR_API_KEY",
            "env",
            "Linear API key",
            ("linear",),
            hint="Linear → Settings → Security & Access",
        ),
    ),
    "slack": (
        CredentialItem(
            "SLACK_WIKI_BOT_TOKEN",
            "env",
            "Slack wiki bot token",
            ("slack",),
            hint="xoxb-… for @wiki; optional SLACK_WIKI_APP_TOKEN for Socket Mode",
        ),
    ),
    "gmail": (
        CredentialItem(
            "GMAIL_OAUTH_ACCESS_TOKEN",
            "oauth",
            "Gmail OAuth access token",
            ("gmail",),
            hint="Also set GMAIL_OAUTH_CLIENT_ID/SECRET; see project_install.md",
        ),
        CredentialItem(
            "GMAIL_OAUTH_CLIENT_ID",
            "env",
            "Gmail OAuth client id",
            ("gmail",),
        ),
        CredentialItem(
            "GMAIL_OAUTH_CLIENT_SECRET",
            "env",
            "Gmail OAuth client secret",
            ("gmail",),
        ),
    ),
    "granola": (
        CredentialItem(
            "GRANOLA_API_KEY",
            "env",
            "Granola API key (enterprise) or GRANOLA_MEMBER_KEYS",
            ("granola",),
            required=False,
            hint="Business: GRANOLA_MEMBER_KEYS=alice:grn_…; Enterprise: GRANOLA_API_KEY",
        ),
    ),
    "posthog": (
        CredentialItem(
            "POSTHOG_API_KEY",
            "env",
            "PostHog personal/API key",
            ("posthog",),
            hint="Also set POSTHOG_HOST / POSTHOG_PROJECT_ID per product.yaml",
        ),
        CredentialItem(
            "POSTHOG_PROJECT_ID",
            "env",
            "PostHog project id",
            ("posthog",),
            required=False,
        ),
    ),
    "google_ads": (
        CredentialItem(
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "env",
            "Google Ads developer token",
            ("google_ads",),
            hint="See growth.yaml google_ads + project_install.md",
        ),
        CredentialItem(
            "GOOGLE_ADS_CUSTOMER_ID",
            "env",
            "Google Ads customer id",
            ("google_ads",),
            required=False,
        ),
    ),
    "discord": (
        CredentialItem(
            "DISCORD_BOT_TOKEN",
            "env",
            "Discord bot token",
            ("discord",),
        ),
    ),
    "mercury": (
        CredentialItem(
            "MERCURY_TOKEN",
            "env",
            "Mercury read-only token",
            ("mercury",),
        ),
    ),
    "ramp": (
        CredentialItem(
            "RAMP_TOKEN",
            "env",
            "Ramp read-scoped token",
            ("ramp",),
        ),
    ),
}


def _repo_items(profile: InstallProfile) -> list[CredentialItem]:
    items = [
        CredentialItem(
            profile.brain_repo_url,
            "repo",
            "Private 4r7a (brain) repo URL",
            (),
            required=True,
            hint="Admin creates the private clone; paste HTTPS/SSH URL into install profile",
        ),
        CredentialItem(
            profile.wiki_repo_url,
            "repo",
            "Private company-wiki repo URL",
            (),
            required=bool(profile.wiki_git_backup),
            hint="Empty private repo for wiki_commit backup",
        ),
    ]
    if profile.wiki_git_backup:
        items.append(
            CredentialItem(
                "COMPANY_BRAIN_WIKI_GIT_TOKEN",
                "env",
                "Wiki git token (company-wiki only)",
                (),
                hint="contents:write on company-wiki; never grant 4r7a agent-repo access",
            )
        )
    return items


def _llm_required(profile: InstallProfile) -> list[CredentialItem]:
    provider = (os.getenv("COMPANY_BRAIN_LLM_PROVIDER") or "anthropic").strip().lower()
    if provider == "openai":
        return [
            CredentialItem(
                "OPENAI_API_KEY",
                "env",
                "OpenAI API key",
                (),
                hint="COMPANY_BRAIN_LLM_PROVIDER=openai",
            )
        ]
    if provider == "glm":
        return [
            CredentialItem(
                "GLM_BASE_URL",
                "env",
                "GLM OpenAI-compatible base URL",
                (),
                hint="e.g. http://localhost:11434/v1",
            )
        ]
    return [
        CredentialItem(
            "ANTHROPIC_API_KEY",
            "env",
            "Anthropic API key",
            (),
            hint="COMPANY_BRAIN_LLM_PROVIDER=anthropic (default)",
        )
    ]


def credential_checklist(
    profile: InstallProfile | None = None,
) -> list[CredentialItem]:
    """Return checklist items for enabled platforms only (no secrets values)."""
    profile = profile or load_install_profile()
    seen: set[tuple[str, str]] = set()
    items: list[CredentialItem] = []

    def add(item: CredentialItem) -> None:
        key = (item.kind, item.key if item.kind != "repo" else item.label)
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    for item in _repo_items(profile):
        add(item)
    for item in _llm_required(profile):
        add(item)

    for platform in profile.enabled_platforms():
        for item in _BY_PLATFORM.get(platform, ()):
            add(item)

    if profile.bridge:
        add(
            CredentialItem(
                "bridge",
                "cli_login",
                "Bridge MCP (deferred) — skip unless you are wiring bridge",
                (),
                required=False,
                hint="See access-control.mdc; company-brain bridge issue-token",
            )
        )

    return items


def checklist_rows(profile: InstallProfile | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in credential_checklist(profile):
        if item.kind == "env":
            ready = bool(os.getenv(item.key, "").strip())
        elif item.kind == "repo":
            ready = bool(item.key.strip())
        elif item.kind == "oauth":
            ready = bool(os.getenv(item.key, "").strip())
        else:
            ready = None  # cli_login — verify in foundation
        rows.append(
            {
                "key": item.key if item.kind != "repo" else item.label,
                "kind": item.kind,
                "label": item.label,
                "platforms": list(item.platforms),
                "required": item.required,
                "hint": item.hint,
                "ready": ready,
            }
        )
    return rows


def format_checklist(profile: InstallProfile | None = None) -> str:
    lines = ["# Install credentials checklist", ""]
    lines.append("Fill `.env` / complete OAuth/CLI logins. Secrets never go in YAML or wiki.")
    lines.append("")
    for row in checklist_rows(profile):
        if row["ready"] is True:
            mark = "[x]"
        elif row["ready"] is False:
            mark = "[ ]"
        else:
            mark = "[?]"
        req = "required" if row["required"] else "optional"
        plat = ",".join(row["platforms"]) or "core"
        lines.append(f"- {mark} ({req}) {row['label']} `{row['key']}` [{plat}]")
        if row["hint"]:
            lines.append(f"    hint: {row['hint']}")
    lines.append("")
    return "\n".join(lines)
