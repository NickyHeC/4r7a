"""Gmail service profiles — EA vs employee vs service-account setups.

``gmail_manager`` runs for every connected account. ``inbox_triage`` label
taxonomy and specialist dispatch are scoped by profile (see
``config/operations.yaml`` → ``gmail.profiles``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from company_brain.agents.operations.shared.gmail_config import gmail_cfg, label_defs, mailbox_id

# Specialist keys (match agent modules / routing handled keys).
ALL_GMAIL_AGENTS = frozenset(
    {
        "inbox_triage",
        "thread_watcher",
        "inbox_sweep",
        "draft_reply",
        "decision_propagate",
        "ingest",
        "ingest_queue_review",
        "attachment_router",
        "investor_tracker",
        "customer_support",
        "customer_crm",
        "growth_inbound",
        "vendor_tracker",
        "connection",
        "recruiting_inbound",
        "partnership_digest",
        "inbox_task",
        "team_on_it",
        "duplicate_across_mailboxes",
        "receipt_router",
        "ext_meeting_scheduler",
    }
)

MANAGER_DISPATCH_ORDER = [
    "duplicate_across_mailboxes",
    "inbox_task",
    "team_on_it",
    "draft_reply",
    "ext_meeting_scheduler",
    "ingest",
    "attachment_router",
    "investor_tracker",
    "customer_support",
    "customer_crm",
    "growth_inbound",
    "vendor_tracker",
    "connection",
    "recruiting_inbound",
    "ingest_queue_review",
    "partnership_digest",
    "receipt_router",
]

WEEKLY_DISPATCH = {
    "ingest_queue_review",
    "partnership_digest",
    "receipt_router",
}

# CRM wiki seed keys (see wiki_crm.CRM_SEEDS).
CRM_SEED_KEYS = frozenset(
    {
        "investor",
        "investor_interest",
        "customer",
        "media_promotion",
        "connection",
        "inbound_candidate",
    }
)


@dataclass
class ProfileSpec:
    name: str
    description: str = ""
    attention: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    cold_inbound_nested: bool = True
    newsletters_nested: bool = True
    investor: bool = True
    warm_intro: bool = True
    agents: set[str] = field(default_factory=set)
    all_agents: bool = False

    def allows_domain(self, tag: str) -> bool:
        if self.all_agents:
            return True
        if tag in self.domain:
            return True
        parent = label_defs().get("cold_inbound_parent", "Cold Inbound")
        nl = label_defs().get("newsletters_parent", "Newsletters")
        if not self.cold_inbound_nested and tag == parent:
            return parent in self.domain
        if not self.newsletters_nested and tag == nl:
            return nl in self.domain
        if self.cold_inbound_nested and tag.startswith(f"{parent}/"):
            return True
        if self.newsletters_nested and tag.startswith(f"{nl}/"):
            return True
        return False

    def agent_enabled(self, key: str) -> bool:
        if self.all_agents:
            return key in ALL_GMAIL_AGENTS
        return key in self.agents


def _default_profile_name() -> str:
    return str(gmail_cfg().get("profile", "executive_assistant"))


def resolve_profile_name(mailbox: str | None = None) -> str:
    mb = mailbox or mailbox_id()
    env = os.getenv("GMAIL_PROFILE", "").strip()
    if env:
        return env
    overrides = gmail_cfg().get("mailbox_profiles") or {}
    entry = overrides.get(mb)
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and entry.get("profile"):
        return str(entry["profile"])
    return _default_profile_name()


def _profile_raw(name: str) -> dict[str, Any]:
    profiles = gmail_cfg().get("profiles") or {}
    if name not in profiles:
        return profiles.get("executive_assistant") or {}
    return profiles[name] or {}


def _merge_dict(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], val)
        else:
            out[key] = val
    return out


def profile_spec(mailbox: str | None = None) -> ProfileSpec:
    mb = mailbox or mailbox_id()
    name = resolve_profile_name(mb)
    raw = _profile_raw(name)
    overrides = gmail_cfg().get("mailbox_profiles") or {}
    entry = overrides.get(mb)
    if isinstance(entry, dict):
        raw = _merge_dict(raw, {k: v for k, v in entry.items() if k != "profile"})

    labels = raw.get("labels") or {}
    agents_raw = raw.get("agents")
    use_full = bool(raw.get("use_full_labels"))

    if use_full:
        attention = [e["name"] for e in label_defs().get("attention") or []]
        domain = [e["name"] for e in label_defs().get("domain") or []]
        cold_nested = True
        nl_nested = True
        investor = True
        warm_intro = True
    else:
        attention = list(labels.get("attention") or [])
        domain = list(labels.get("domain") or [])
        cold_nested = bool(labels.get("cold_inbound_nested", True))
        nl_nested = bool(labels.get("newsletters_nested", True))
        investor = bool(labels.get("investor", True))
        warm_intro = bool(labels.get("warm_intro", True))

    all_agents = agents_raw == "all" or raw.get("all_agents") is True
    if isinstance(agents_raw, list):
        agents = {str(a) for a in agents_raw}
    elif all_agents:
        agents = set(ALL_GMAIL_AGENTS)
    else:
        agents = set()

    return ProfileSpec(
        name=name,
        description=str(raw.get("description", "")),
        attention=attention,
        domain=domain,
        cold_inbound_nested=cold_nested,
        newsletters_nested=nl_nested,
        investor=investor,
        warm_intro=warm_intro,
        agents=agents,
        all_agents=all_agents,
    )


def agent_enabled(agent_key: str, mailbox: str | None = None) -> bool:
    return profile_spec(mailbox).agent_enabled(agent_key)


def normalize_domain_tags(tags: list[str], *, mailbox: str | None = None) -> list[str]:
    """Flatten or strip tags according to the mailbox profile."""
    spec = profile_spec(mailbox)
    parent = label_defs().get("cold_inbound_parent", "Cold Inbound")
    nl = label_defs().get("newsletters_parent", "Newsletters")
    out: list[str] = []

    had_cold = False
    had_nl = False
    for tag in tags:
        if tag == "Investor" and not spec.investor:
            continue
        if tag == "Warm intro" and not spec.warm_intro:
            continue
        if not spec.cold_inbound_nested and tag.startswith(f"{parent}/"):
            had_cold = True
            continue
        if not spec.newsletters_nested and tag.startswith(f"{nl}/"):
            had_nl = True
            continue
        if spec.domain and not spec.all_agents and tag not in spec.domain:
            if not (spec.cold_inbound_nested and tag.startswith(f"{parent}/")):
                if not (spec.newsletters_nested and tag.startswith(f"{nl}/")):
                    if tag not in spec.domain:
                        continue
        out.append(tag)

    if had_cold and parent in spec.domain and parent not in out:
        out.append(parent)
    if had_nl and nl in spec.domain and nl not in out:
        out.append(nl)
    return out


def normalize_attention(attention: str | None, *, mailbox: str | None = None) -> str | None:
    spec = profile_spec(mailbox)
    if attention and attention not in spec.attention:
        return None
    return attention


def crm_seed_keys_for_profile(mailbox: str | None = None) -> set[str]:
    """Which CRM wiki seed pages to create for this profile."""
    spec = profile_spec(mailbox)
    keys: set[str] = set()
    if spec.agent_enabled("investor_tracker"):
        keys.add("investor")
        keys.add("investor_interest")
    if spec.agent_enabled("customer_crm"):
        keys.add("customer")
    if spec.agent_enabled("growth_inbound"):
        keys.add("media_promotion")
    if spec.agent_enabled("connection"):
        keys.add("connection")
    if spec.agent_enabled("recruiting_inbound"):
        keys.add("inbound_candidate")
    return keys
