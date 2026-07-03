"""Shared $0 heuristics for CRM inbound priority scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from company_brain.crm.config import crm_cfg, reputable_domains
from company_brain.crm.registry import RegistryEntry

_EMAIL_IN_FROM = re.compile(r"<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")

FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
    }
)

GENERIC_OUTREACH = (
    "quick question",
    "reaching out",
    "intro call",
    "book a demo",
    "hope this email finds you",
    "touch base",
)

TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "press-podcast": (
        "podcast",
        "press",
        "media",
        "interview",
        "journalist",
        "reporter",
        "broadcast",
        "tv",
        "newsletter feature",
    ),
    "event-invitation": (
        "conference",
        "summit",
        "event",
        "sponsor",
        "co-host",
        "cohost",
        "booth",
        "exhibit",
        "keynote",
        "invite you to speak",
    ),
    "partnership": (
        "strategic",
        "integration",
        "api",
        "enterprise",
        "revenue",
        "distribution",
        "co-marketing",
        "platform",
        "ecosystem",
        "b2b",
        "saas",
        "partnership",
    ),
    "founder-networking": (
        "founder",
        "network",
        "peer",
        "coffee",
        "connect founders",
    ),
    "investor-interest": (
        "investor",
        "vc",
        "capital",
        "fund",
        "term sheet",
        "raise",
    ),
    "candidate": (
        "application",
        "resume",
        "cv",
        "job",
        "role at",
        "open position",
    ),
}

SLACK_ALERT_TYPES = frozenset({"press-podcast", "event-invitation"})


@dataclass
class ScoreResult:
    score: int
    reasons: list[str] = field(default_factory=list)


def score_inbound(
    inbound_type: str,
    *,
    subject: str,
    from_hdr: str,
    body: str,
    registry_entry: RegistryEntry | None = None,
) -> ScoreResult:
    """Score an inbound opportunity (higher = more relevant)."""
    blob = f"{subject} {body}".lower()
    from_lower = from_hdr.lower()
    result = ScoreResult(score=0)

    domain = _domain_from_from(from_lower)
    reputable = reputable_domains()
    press_domains = _domain_set("press_domains")
    event_domains = _domain_set("event_domains")

    if domain and domain in reputable:
        _add(result, 4, f"reputable_domain:{domain}")
    if inbound_type == "press-podcast" and domain in press_domains:
        _add(result, 3, f"press_domain:{domain}")
    if inbound_type == "event-invitation" and domain in event_domains:
        _add(result, 3, f"event_domain:{domain}")

    if registry_entry and registry_entry.segment in {"connection", "customer"}:
        _add(result, 2, f"known_{registry_entry.segment}")

    for kw in TYPE_KEYWORDS.get(inbound_type, ()):
        if kw in blob or kw in from_lower:
            _add(result, 2 if len(kw) > 6 else 1, f"keyword:{kw}")

    if domain in FREE_EMAIL_DOMAINS:
        _add(result, -2, f"free_email:{domain}")

    for phrase in GENERIC_OUTREACH:
        if phrase in blob:
            _add(result, -1, f"generic:{phrase}")

    return result


def should_slack_alert(inbound_type: str, result: ScoreResult) -> bool:
    from company_brain.crm.config import slack_score_threshold

    if inbound_type not in SLACK_ALERT_TYPES:
        return False
    return result.score >= slack_score_threshold()


def _domain_set(key: str) -> set[str]:
    return {str(d).lower() for d in (crm_cfg().get(key) or [])}


def _domain_from_from(from_hdr: str) -> str:
    for match in _EMAIL_IN_FROM.finditer(from_hdr):
        email = (match.group(1) or match.group(2) or "").lower()
        if "@" in email:
            return email.rsplit("@", 1)[-1]
    return ""


def _add(result: ScoreResult, points: int, reason: str) -> None:
    result.score += points
    result.reasons.append(reason)
