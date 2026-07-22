"""Pluggable signup feeds for attribution (wiki CRM default; stubs for others)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from company_brain.agents.product.shared.workstream_config import signup_source_cfg
from company_brain.wiki.store import LocalWikiStore


@dataclass
class SignupEvent:
    key: str
    when: date
    label: str = ""


def load_signups(*, days: int = 30) -> list[SignupEvent]:
    cfg = signup_source_cfg()
    kind = str(cfg.get("type") or "wiki_crm").strip().lower()
    if kind in {"", "none"}:
        return []
    if kind == "wiki_crm":
        return _from_wiki_crm(days=days)
    if kind == "csv_path":
        path = str(cfg.get("csv_path") or "").strip()
        return _from_csv(path, days=days) if path else []
    if kind == "http_json":
        url = str(cfg.get("http_json") or "").strip()
        return _from_http_json(url, days=days) if url else []
    return []


def signup_source_signature() -> str:
    events = load_signups(days=30)
    return f"{len(events)}:" + ",".join(sorted(e.key for e in events[-50:]))


def _cutoff(days: int) -> date:
    return date.fromordinal(date.today().toordinal() - max(1, days))


def _parse_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _from_wiki_crm(*, days: int) -> list[SignupEvent]:
    store = LocalWikiStore()
    cutoff = _cutoff(days)
    out: list[SignupEvent] = []
    for rel in store.list("crm/contact/"):
        if not rel.endswith(".md"):
            continue
        doc = store.read(rel)
        fm = doc.frontmatter or {}
        if str(fm.get("segment") or "").lower() != "customer":
            continue
        when = (
            _parse_date(fm.get("signup_date"))
            or _parse_date(fm.get("created"))
            or _parse_date(fm.get("last_updated"))
        )
        if when is None or when < cutoff:
            continue
        slug = rel.rsplit("/", 1)[-1].removesuffix(".md")
        out.append(SignupEvent(key=slug, when=when, label=str(fm.get("title") or slug)))
    return sorted(out, key=lambda e: e.when)


def _from_csv(path: str, *, days: int) -> list[SignupEvent]:
    cutoff = _cutoff(days)
    out: list[SignupEvent] = []
    p = Path(path)
    if not p.is_file():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            when = _parse_date(row.get("date") or row.get("signup_date") or row.get("created"))
            key = str(row.get("id") or row.get("email") or row.get("key") or "").strip()
            if not key or when is None or when < cutoff:
                continue
            out.append(SignupEvent(key=key, when=when, label=str(row.get("label") or key)))
    return sorted(out, key=lambda e: e.when)


def _from_http_json(url: str, *, days: int) -> list[SignupEvent]:
    """Stub adapter: expects JSON list of `{id, date}` (or `signup_date`)."""
    cutoff = _cutoff(days)
    try:
        with urlopen(url, timeout=20) as resp:  # noqa: S310 — admin-configured URL
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    rows = payload if isinstance(payload, list) else payload.get("signups") or []
    out: list[SignupEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = _parse_date(row.get("date") or row.get("signup_date") or row.get("created"))
        key = str(row.get("id") or row.get("email") or row.get("key") or "").strip()
        if not key or when is None or when < cutoff:
            continue
        out.append(SignupEvent(key=key, when=when, label=str(row.get("label") or key)))
    return sorted(out, key=lambda e: e.when)
