"""Phase-1 triage classifiers (deterministic heuristics, $0)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from company_brain.agents.operations.gmail import gmail_rest as rest
from company_brain.agents.operations.shared.contact_lists import load_contacts, matches_contact
from company_brain.agents.operations.shared.gmail_config import (
    auto_archive_cold_tags,
    customers_wiki_path,
    investors_crm_path,
    label_defs,
)


@dataclass
class TriageResult:
    attention: str | None = None
    domain_tags: list[str] = field(default_factory=list)
    contact_type: str | None = None
    mark_read: bool = False
    archive_now: bool = False
    newsletter_name: str | None = None
    extracted: dict[str, Any] = field(default_factory=dict)


AI_MEETING_SENDERS = (
    "granola", "otter.ai", "fathom", "read.ai", "fireflies", "tl;dv",
)
RECEIPT_HINTS = ("receipt", "invoice", "payment confirmation", "order confirmation", "your receipt")
NEWSLETTER_HINTS = ("newsletter", "unsubscribe", "view in browser")
SALES_HINTS = ("quick question", "partnership opportunity", "reaching out", "intro call", "book a demo")
JOB_HINTS = ("application received", "job alert", "linkedin", "greenhouse", "lever.co", "ashbyhq")


def classify_message(message: dict[str, Any], *, mailbox: str = "me") -> TriageResult:
    headers = rest.header_map(message)
    subject = (headers.get("subject") or "").lower()
    from_hdr = (headers.get("from") or "").lower()
    snippet = rest.snippet(message).lower()
    list_unsub = headers.get("list-unsubscribe") or headers.get("list-unsubscribe-post")

    result = TriageResult(
        extracted={
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "date": rest.message_date(message),
        }
    )

    # AI meeting notes
    if any(s in from_hdr for s in AI_MEETING_SENDERS) or "meeting notes" in subject:
        result.domain_tags.append("AI Meeting Notes")
        result.mark_read = True
        result.archive_now = True
        return result

    # Receipts
    if any(h in subject for h in RECEIPT_HINTS) or "receipt" in snippet[:200]:
        result.domain_tags.append("Receipts")
        result.mark_read = True
        return result

    # Newsletters
    if list_unsub or any(h in subject for h in NEWSLETTER_HINTS):
        name = _newsletter_name(headers.get("from", ""), subject)
        result.domain_tags.append(f"Newsletters/{name}")
        result.newsletter_name = name
        result.mark_read = True
        return result

    # Meeting invites
    if "invite.ics" in str(message.get("payload", {})) or "calendar.google.com" in snippet:
        if "meeting request" in subject or "schedule" in subject:
            result.domain_tags.append("Meeting Request")
        else:
            result.domain_tags.append("Meeting")
        return result

    # Confirmed investor (wiki list) before cold inbound
    if _is_confirmed_investor(from_hdr):
        result.domain_tags.append("Investor")
        result.contact_type = "investor"
        result.attention = result.attention or "2. Reply"
        return result

    # Cold inbound
    cold = _classify_cold(from_hdr, subject, snippet)
    if cold:
        parent = label_defs().get("cold_inbound_parent", "Cold Inbound")
        result.domain_tags.append(f"{parent}/{cold}")
        if cold in auto_archive_cold_tags():
            result.mark_read = True
            result.archive_now = True
        return result

    # Customer (active — wiki CRM list)
    if _is_customer(from_hdr):
        result.domain_tags.append("Customer")
        result.attention = result.attention or "2. Reply"
        return result

    # Vendor renewals / billing
    if _is_vendor(from_hdr, subject, snippet):
        result.domain_tags.append("Vendor")
        result.attention = result.attention or "3. FYI"
        return result

    # People (non-investor connections)
    if _is_people(from_hdr, subject, snippet):
        result.domain_tags.append("People")
        return result

    # Attention heuristics
    if "?" in subject or "?" in snippet[:120]:
        result.attention = "2. Reply"
        return result
    if any(w in subject for w in ("action required", "signature required", "please sign", "deadline")):
        result.attention = "1. Action"
        return result
    if subject.startswith("fyi") or "fyi:" in subject:
        result.attention = "3. FYI"
        return result

    # Default: FYI if nothing else
    result.attention = "3. FYI"
    return result


def _newsletter_name(from_hdr: str, subject: str) -> str:
    m = re.search(r"from ([^<]+)<", from_hdr, re.I)
    if m:
        return m.group(1).strip()[:40]
    if "<" in from_hdr:
        return from_hdr.split("<")[0].strip()[:40] or "Unknown"
    return (subject[:40] or "Unknown").strip()


def _classify_cold(from_hdr: str, subject: str, snippet: str) -> str | None:
    blob = f"{from_hdr} {subject} {snippet}"
    if any(h in blob for h in JOB_HINTS):
        return "Job Seekers"
    if any(h in blob for h in SALES_HINTS) or "sales@" in from_hdr:
        return "Sales Outreach"
    if "investor" in blob or "vc@" in from_hdr or "capital" in from_hdr:
        return "Investor Interest"
    if "podcast" in blob or "press" in blob or "media" in subject:
        return "Press & Podcast"
    if "hackathon" in blob or "sponsor" in blob or "event" in subject:
        return "Event Invitations"
    if "partnership" in blob:
        return "Partnership"
    if "founder" in blob and "intro" in blob:
        return "Founder Networking"
    return None


def _is_confirmed_investor(from_hdr: str) -> bool:
    emails, domains = load_contacts(investors_crm_path())
    return matches_contact(from_hdr, emails, domains)


def _is_customer(from_hdr: str) -> bool:
    emails, domains = load_contacts(customers_wiki_path())
    return matches_contact(from_hdr, emails, domains)


def _is_vendor(from_hdr: str, subject: str, snippet: str) -> bool:
    blob = f"{from_hdr} {subject} {snippet}"
    if "billing@" in from_hdr or "accounts@" in from_hdr or "invoices@" in from_hdr:
        return True
    return any(w in blob for w in ("subscription renewal", "renewal notice", "your plan", "invoice #"))


def _is_people(from_hdr: str, subject: str, snippet: str) -> bool:
    blob = f"{subject} {snippet}".lower()
    if "investor" in from_hdr.lower():
        return False
    return any(w in blob for w in ("nice to meet", "connect you with", "introducing", "pleasure meeting"))
