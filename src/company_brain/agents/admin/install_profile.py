"""Install profile — machine-readable scope for guided 4r7a setup.

Pointers and toggles only. Secrets stay in ``.env``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from company_brain.config import CONFIG_DIR, load_yaml_config, save_yaml_config

PROFILE_NAME = "install_profile"

DEPARTMENT_ORDER: tuple[str, ...] = (
    "engineering",
    "operations",
    "product",
    "growth",
    "finance",
    "hr",
)

# Platforms run during foundation (before department onboarding sequence).
FOUNDATION_PLATFORMS: frozenset[str] = frozenset({"notion"})

DEFAULT_PLATFORMS: dict[str, dict[str, Any]] = {
    "github": {"enabled": True, "department": "engineering"},
    "linear": {"enabled": True, "department": "engineering"},
    "notion": {"enabled": True, "department": "operations"},
    "slack": {"enabled": True, "department": "operations"},
    "gmail": {"enabled": True, "department": "operations"},
    "granola": {"enabled": True, "department": "operations"},
    "posthog": {"enabled": True, "department": "product"},
    "product_workstreams": {"enabled": True, "department": "product"},
    "google_ads": {"enabled": True, "department": "growth"},
    "discord": {"enabled": True, "department": "growth"},
    "growth_workstreams": {"enabled": True, "department": "growth"},
    "mercury": {"enabled": True, "department": "finance"},
    "ramp": {"enabled": True, "department": "finance"},
    "linkedin": {"enabled": True, "department": "hr"},
}

DEFAULT_PROFILE: dict[str, Any] = {
    "runtime": "local",
    "brain_repo_url": "",
    "wiki_repo_url": "",
    "notion_sync": True,
    "employee_wiki": True,
    "wiki_git_backup": True,
    "bridge": False,
    "notify": {"admin_channel": "#wiki-admin"},
    "departments": {d: True for d in DEPARTMENT_ORDER},
    "platforms": deepcopy(DEFAULT_PLATFORMS),
}


@dataclass
class InstallProfile:
    """Typed view over ``config/install_profile.yaml``."""

    runtime: str = "local"
    brain_repo_url: str = ""
    wiki_repo_url: str = ""
    notion_sync: bool = True
    employee_wiki: bool = True
    wiki_git_backup: bool = True
    bridge: bool = False
    notify: dict[str, Any] = field(default_factory=lambda: {"admin_channel": "#wiki-admin"})
    departments: dict[str, bool] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "brain_repo_url": self.brain_repo_url,
            "wiki_repo_url": self.wiki_repo_url,
            "notion_sync": self.notion_sync,
            "employee_wiki": self.employee_wiki,
            "wiki_git_backup": self.wiki_git_backup,
            "bridge": self.bridge,
            "notify": dict(self.notify),
            "departments": dict(self.departments),
            "platforms": {k: dict(v) for k, v in self.platforms.items()},
        }

    def department_enabled(self, department: str) -> bool:
        return bool(self.departments.get(department, False))

    def platform_enabled(self, platform: str) -> bool:
        block = self.platforms.get(platform) or {}
        if not bool(block.get("enabled", False)):
            return False
        dept = str(block.get("department") or "")
        if dept and not self.department_enabled(dept):
            return False
        return True

    def enabled_platforms(self, *, department: str | None = None) -> list[str]:
        names: list[str] = []
        for name, block in self.platforms.items():
            if not self.platform_enabled(name):
                continue
            if department and str(block.get("department") or "") != department:
                continue
            names.append(name)
        return names

    def disabled_platforms(self) -> list[str]:
        return [name for name in self.platforms if not self.platform_enabled(name)]

    def department_onboarding_order(self) -> list[str]:
        return [d for d in DEPARTMENT_ORDER if self.department_enabled(d)]


def default_profile_dict() -> dict[str, Any]:
    return deepcopy(DEFAULT_PROFILE)


def _merge_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_profile_dict()
    if not raw:
        return base
    out = deepcopy(base)
    for key in (
        "runtime",
        "brain_repo_url",
        "wiki_repo_url",
        "notion_sync",
        "employee_wiki",
        "wiki_git_backup",
        "bridge",
    ):
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    if isinstance(raw.get("notify"), dict):
        out["notify"].update(raw["notify"])
    if isinstance(raw.get("departments"), dict):
        for dept, enabled in raw["departments"].items():
            out["departments"][str(dept)] = bool(enabled)
    if isinstance(raw.get("platforms"), dict):
        for name, block in raw["platforms"].items():
            key = str(name)
            if not isinstance(block, dict):
                continue
            merged = dict(out["platforms"].get(key) or {"enabled": True, "department": ""})
            merged.update({k: v for k, v in block.items() if v is not None})
            out["platforms"][key] = merged
    return out


def profile_from_dict(data: dict[str, Any]) -> InstallProfile:
    merged = _merge_defaults(data)
    return InstallProfile(
        runtime=str(merged.get("runtime") or "local"),
        brain_repo_url=str(merged.get("brain_repo_url") or ""),
        wiki_repo_url=str(merged.get("wiki_repo_url") or ""),
        notion_sync=bool(merged.get("notion_sync", True)),
        employee_wiki=bool(merged.get("employee_wiki", True)),
        wiki_git_backup=bool(merged.get("wiki_git_backup", True)),
        bridge=bool(merged.get("bridge", False)),
        notify=dict(merged.get("notify") or {}),
        departments={str(k): bool(v) for k, v in (merged.get("departments") or {}).items()},
        platforms={
            str(k): dict(v) if isinstance(v, dict) else {"enabled": bool(v)}
            for k, v in (merged.get("platforms") or {}).items()
        },
    )


def load_install_profile(config_dir: Path | None = None) -> InstallProfile:
    raw = load_yaml_config(PROFILE_NAME, config_dir)
    return profile_from_dict(raw)


def save_install_profile(profile: InstallProfile, config_dir: Path | None = None) -> Path:
    path = (config_dir or CONFIG_DIR) / f"{PROFILE_NAME}.yaml"
    save_yaml_config(PROFILE_NAME, profile.to_dict(), config_dir)
    return path


def set_platform_enabled(
    profile: InstallProfile,
    platform: str,
    enabled: bool,
) -> InstallProfile:
    platforms = dict(profile.platforms)
    block = dict(platforms.get(platform) or DEFAULT_PLATFORMS.get(platform) or {})
    block["enabled"] = enabled
    if "department" not in block and platform in DEFAULT_PLATFORMS:
        block["department"] = DEFAULT_PLATFORMS[platform]["department"]
    platforms[platform] = block
    profile.platforms = platforms
    return profile


def set_department_enabled(
    profile: InstallProfile,
    department: str,
    enabled: bool,
) -> InstallProfile:
    depts = dict(profile.departments)
    depts[department] = enabled
    profile.departments = depts
    return profile


def prompt_profile(*, config_dir: Path | None = None) -> InstallProfile:
    """Interactive best-practice defaults; admin can override."""
    import click

    profile = load_install_profile(config_dir)
    click.echo("\n4r7a install profile (best-practice defaults; override as needed)\n")

    runtime = (
        click.prompt(
            "Runtime [local/cloud]",
            default=profile.runtime or "local",
        )
        .strip()
        .lower()
    )
    profile.runtime = "cloud" if runtime == "cloud" else "local"

    profile.brain_repo_url = click.prompt(
        "Private 4r7a (brain) repo URL",
        default=profile.brain_repo_url or "",
        show_default=bool(profile.brain_repo_url),
    ).strip()
    profile.wiki_repo_url = click.prompt(
        "Private company-wiki repo URL",
        default=profile.wiki_repo_url or "",
        show_default=bool(profile.wiki_repo_url),
    ).strip()

    profile.notion_sync = click.confirm("Enable Notion sync?", default=profile.notion_sync)
    profile.employee_wiki = click.confirm(
        "Enable employee wiki buildings?",
        default=profile.employee_wiki,
    )
    profile.wiki_git_backup = click.confirm(
        "Enable daily wiki_commit GitHub backup?",
        default=profile.wiki_git_backup,
    )
    profile.bridge = click.confirm(
        "Enable member bridge MCP? (usually no until wired)",
        default=profile.bridge,
    )

    click.echo(
        "\nDepartments (order after foundation: eng → ops → product → growth → finance → hr)"
    )
    for dept in DEPARTMENT_ORDER:
        enabled = click.confirm(
            f"  Include {dept}?",
            default=profile.department_enabled(dept),
        )
        set_department_enabled(profile, dept, enabled)

    click.echo("\nPlatforms (disabled platforms are skipped — not deleted)")
    for name in sorted(profile.platforms.keys()):
        block = profile.platforms[name]
        dept = block.get("department") or "?"
        if not profile.department_enabled(str(dept)) and name not in FOUNDATION_PLATFORMS:
            set_platform_enabled(profile, name, False)
            click.echo(f"  {name}: skipped (department {dept} disabled)")
            continue
        enabled = click.confirm(
            f"  Enable {name} ({dept})?",
            default=bool(block.get("enabled", True)),
        )
        set_platform_enabled(profile, name, enabled)

    path = save_install_profile(profile, config_dir)
    click.secho(f"Wrote {path}", fg="green")
    return profile


def apply_profile_flags(
    *,
    runtime: str | None = None,
    brain_repo_url: str | None = None,
    wiki_repo_url: str | None = None,
    disable_department: tuple[str, ...] = (),
    enable_department: tuple[str, ...] = (),
    disable_platform: tuple[str, ...] = (),
    enable_platform: tuple[str, ...] = (),
    notion_sync: bool | None = None,
    employee_wiki: bool | None = None,
    wiki_git_backup: bool | None = None,
    bridge: bool | None = None,
    config_dir: Path | None = None,
) -> InstallProfile:
    """Non-interactive profile updates (for coding agents / CI)."""
    profile = load_install_profile(config_dir)
    if runtime:
        profile.runtime = "cloud" if runtime.strip().lower() == "cloud" else "local"
    if brain_repo_url is not None:
        profile.brain_repo_url = brain_repo_url.strip()
    if wiki_repo_url is not None:
        profile.wiki_repo_url = wiki_repo_url.strip()
    if notion_sync is not None:
        profile.notion_sync = notion_sync
    if employee_wiki is not None:
        profile.employee_wiki = employee_wiki
    if wiki_git_backup is not None:
        profile.wiki_git_backup = wiki_git_backup
    if bridge is not None:
        profile.bridge = bridge
    for dept in enable_department:
        set_department_enabled(profile, dept, True)
    for dept in disable_department:
        set_department_enabled(profile, dept, False)
    for plat in enable_platform:
        set_platform_enabled(profile, plat, True)
    for plat in disable_platform:
        set_platform_enabled(profile, plat, False)
    save_install_profile(profile, config_dir)
    return profile


def profile_summary(profile: InstallProfile) -> str:
    lines = [
        f"runtime: {profile.runtime}",
        f"brain_repo_url: {profile.brain_repo_url or '(unset)'}",
        f"wiki_repo_url: {profile.wiki_repo_url or '(unset)'}",
        f"notion_sync: {profile.notion_sync}",
        f"employee_wiki: {profile.employee_wiki}",
        f"wiki_git_backup: {profile.wiki_git_backup}",
        f"bridge: {profile.bridge}",
        "departments: "
        + ", ".join(
            f"{d}={'on' if profile.department_enabled(d) else 'off'}" for d in DEPARTMENT_ORDER
        ),
        "enabled_platforms: " + (", ".join(profile.enabled_platforms()) or "(none)"),
        "disabled_platforms: " + (", ".join(profile.disabled_platforms()) or "(none)"),
    ]
    return "\n".join(lines)
