"""Deep research batch → CRM contacts (lead segment, CRM-first dedupe).

SDK: Neither for v1 identity parse + CRM write. Skips weak identity rows.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.growth.leads.queue import mark_job
from company_brain.agents.growth.shared.growth_slack import growth_notifier
from company_brain.crm.contacts import read_contact, write_contact
from company_brain.crm.registry import load_registry, rebuild_registry
from company_brain.crm.schema import ContactEntity
from company_brain.crm.slug import slug_from_email
from company_brain.notify import ACTIONABLE, Signal
from company_brain.wiki.publish import UPDATE, write_wiki_page

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
RELATIONSHIP_SEGMENTS = frozenset({"connection", "customer", "investor"})
WRITE_MODE = UPDATE


class LeadResearchAgent(BaseAgent):
    """Process one lead research job into CRM contacts."""

    name = "lead_research"
    WRITE_MODE = WRITE_MODE

    def should_run(self, **kwargs: Any) -> bool:
        return bool(kwargs.get("job") or kwargs.get("job_id"))

    def run(
        self,
        *,
        job: dict[str, Any] | None = None,
        notify: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not job:
            return {"status": "no_job"}
        job_id = str(job.get("id") or "")
        source = str(job.get("source") or "")
        payload = dict(job.get("payload") or {})
        rows: list[dict[str, str]] = []
        skips: list[str] = []

        if source == "attendee_csv":
            rows, skips = _parse_attendee_csv(str(payload.get("csv_text") or ""))
        elif source == "github_stargazers":
            rows, skips = _fetch_stargazers(str(payload.get("repo") or ""))
        elif source == "uploaded_list":
            rows, skips = _parse_attendee_csv(str(payload.get("csv_text") or ""))
        else:
            skips.append(f"unsupported_source:{source}")

        created = 0
        updated = 0
        high_priority = 0
        for row in rows:
            outcome = _upsert_lead(row, source_label=str(job.get("label") or source))
            if outcome == "created":
                created += 1
            elif outcome == "updated":
                updated += 1
            if outcome in {"created", "updated"} and int(row.get("priority") or 5) >= 8:
                high_priority += 1

        rebuild_registry()
        result = {
            "status": "ok",
            "created": created,
            "updated": updated,
            "skipped": skips,
            "rows": len(rows),
        }
        if job_id:
            mark_job(job_id, status="done", result=result)
        if notify and high_priority:
            try:
                growth_notifier().emit(
                    Signal(
                        text=(
                            f"Lead research: {high_priority} high-priority contact(s) "
                            f"from {job.get('label')}"
                        ),
                        severity=ACTIONABLE,
                    )
                )
            except Exception as exc:
                self.logger.warning("growth notify skipped: %s", exc)
        return result


def _parse_attendee_csv(text: str) -> tuple[list[dict[str, str]], list[str]]:
    skips: list[str] = []
    rows: list[dict[str, str]] = []
    if not text.strip():
        return rows, ["empty_csv"]
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        # bare emails, one per line
        for line in text.splitlines():
            email = _EMAIL_RE.search(line)
            if email:
                rows.append({"email": email.group(0).lower(), "name": "", "priority": "5"})
            elif line.strip():
                skips.append(f"no_email:{line.strip()[:40]}")
        return rows, skips

    fields = {f.lower(): f for f in reader.fieldnames}
    email_key = fields.get("email") or fields.get("e-mail") or fields.get("mail")
    name_key = fields.get("name") or fields.get("full name") or fields.get("attendee")
    for raw in reader:
        email = ""
        if email_key:
            email = str(raw.get(email_key) or "").strip().lower()
        if email and "@" not in email:
            email = ""
        if not email:
            blob = " ".join(str(v) for v in raw.values() if v)
            match = _EMAIL_RE.search(blob)
            email = match.group(0).lower() if match else ""
        name = str(raw.get(name_key) or "").strip() if name_key else ""
        if not email or "@" not in email:
            skips.append(f"no_email:{name or list(raw.values())[:1]}")
            continue
        company = ""
        for key in ("company", "organization", "org"):
            if key in fields:
                company = str(raw.get(fields[key]) or "").strip()
                break
        priority = "7" if company else "5"
        rows.append({"email": email, "name": name, "company": company, "priority": priority})
    return rows, skips


def _fetch_stargazers(repo: str) -> tuple[list[dict[str, str]], list[str]]:
    skips: list[str] = []
    rows: list[dict[str, str]] = []
    if not repo.strip():
        return rows, ["empty_repo"]
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{repo}/stargazers", "--paginate", "-q", ".[].login"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return rows, [f"gh_error:{exc}"]
    if proc.returncode != 0:
        return rows, [f"gh_failed:{proc.stderr.strip()[:120]}"]
    for login in proc.stdout.splitlines():
        handle = login.strip()
        if not handle:
            continue
        # Username-only — skip unless we can resolve a public email (rare).
        skips.append(f"username_only:{handle}")
    return rows, skips


def _upsert_lead(row: dict[str, str], *, source_label: str) -> str:
    email = row["email"]
    existing_entry = load_registry().lookup_email(email)
    priority = int(row.get("priority") or 5)
    name = row.get("name") or email.split("@", 1)[0]
    note = f"- Source `{source_label}`" + (f" @ {row['company']}" if row.get("company") else "")

    if existing_entry:
        entity = read_contact(existing_entry.slug)
        if entity is None:
            return "skipped"
        if entity.segment in RELATIONSHIP_SEGMENTS:
            body = entity.body.rstrip() + f"\n\n## Lead research note\n\n{note}\n"
            entity.body = body
            if entity.priority is None or priority > entity.priority:
                entity.priority = priority
            if source_label not in entity.sources:
                entity.sources = list(entity.sources) + [source_label]
            write_contact(entity, rebuild=False)
            return "updated"
        # already a lead — refresh
        entity.priority = max(entity.priority or 0, priority) or priority
        if source_label not in entity.sources:
            entity.sources = list(entity.sources) + [source_label]
        entity.body = entity.body.rstrip() + f"\n\n## Lead research note\n\n{note}\n"
        write_contact(entity, rebuild=False)
        return "updated"

    entity = ContactEntity(
        slug=slug_from_email(email),
        title=name,
        segment="lead",
        canonical_email=email,
        priority=priority,
        sources=[source_label],
        body=f"## Notes\n\n{note}\n\n## Interactions\n\n",
    )
    write_contact(entity, rebuild=False)
    # keep lead index in sync lightly
    _append_lead_index(email)
    return "created"


def _append_lead_index(email: str) -> None:
    from company_brain.crm.config import lead_index_path
    from company_brain.wiki.store import LocalWikiStore

    store = LocalWikiStore()
    rel = lead_index_path()
    line = f"- {email}"
    if store.exists(rel):
        doc = store.read(rel)
        if email.lower() in doc.body.lower():
            return
        body = doc.body.rstrip() + "\n" + line + "\n"
        title = str(doc.frontmatter.get("title") or "Leads")
    else:
        body = f"# Leads\n\n{line}\n"
        title = "Leads"
    write_wiki_page(rel, title, body, mode=WRITE_MODE, section="crm", sync=False)
