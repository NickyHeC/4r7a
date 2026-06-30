"""Promote approved employee wiki imports from quarantine."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from company_brain.wiki.duplicate_detect import FileDuplicateVerdict, parse_duplicate_report
from company_brain.wiki.employee_paths import _slug, member_prefix
from company_brain.wiki.employee_publish import write_employee_wiki_page
from company_brain.wiki.employee_store import LocalEmployeeWikiStore, WikiStore

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


@dataclass
class PromoteResult:
    import_id: str
    member: str
    promoted: list[str]
    linked: list[str]
    dropped: list[str]
    layout_map: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "member": self.member,
            "promoted": self.promoted,
            "linked": self.linked,
            "dropped": self.dropped,
            "layout_map": self.layout_map,
        }


def promote_import(
    member_key: str,
    import_id: str,
    *,
    store: WikiStore | None = None,
    decisions: dict[str, str] | None = None,
    remove_quarantine: bool = True,
) -> PromoteResult:
    """Move approved import files into the member wiki tree."""
    store = store or LocalEmployeeWikiStore()
    quarantine = member_quarantine_rel(member_key, import_id)
    report_path = f"{quarantine}duplicate_report.json"
    if not store.exists(report_path):
        raise FileNotFoundError(report_path)

    report = parse_duplicate_report(store.read_text(report_path))
    decisions = decisions or {}
    layout_map: dict[str, str] = {}
    promoted: list[str] = []
    linked: list[str] = []
    dropped: list[str] = []

    for verdict in report.files:
        action = decisions.get(verdict.path) or _default_action(verdict)
        if action == "drop":
            dropped.append(verdict.path)
            continue
        if action == "link":
            target = verdict.canonical or (verdict.candidates[0] if verdict.candidates else None)
            if not target:
                dropped.append(verdict.path)
                continue
            stub = _write_link_stub(member_key, verdict, target, store=store)
            linked.append(stub)
            layout_map[verdict.path] = stub
            continue

        dest = _propose_dest(member_key, verdict.path)
        body = _read_quarantine_file(store, quarantine, verdict.path)
        rewritten = _rewrite_wikilinks(body, layout_map)
        title = _title_from_import(verdict.path, rewritten)
        write_employee_wiki_page(
            dest,
            title,
            rewritten,
            member=member_key,
            store=store,
            mirror_notion=False,
        )
        promoted.append(dest)
        layout_map[verdict.path] = dest

    if remove_quarantine:
        qpath = store.abspath(quarantine.rstrip("/"))
        if qpath.exists():
            shutil.rmtree(qpath)

    return PromoteResult(
        import_id=import_id,
        member=member_key,
        promoted=promoted,
        linked=linked,
        dropped=dropped,
        layout_map=layout_map,
    )


def member_quarantine_rel(member_key: str, import_id: str) -> str:
    return f"{member_prefix(member_key)}imports/_quarantine/{import_id}/"


def _default_action(verdict: FileDuplicateVerdict) -> str:
    if verdict.verdict == "link":
        return "link"
    if verdict.verdict == "review":
        return "import"
    return verdict.verdict


def _propose_dest(member_key: str, quarantine_path: str) -> str:
    slug = _slug(PurePosixPath(quarantine_path).stem)
    lower = quarantine_path.lower()
    if "project" in lower:
        return f"{member_prefix(member_key)}projects/{slug}.md"
    if "work" in lower or "log" in lower or "standup" in lower:
        return f"{member_prefix(member_key)}work_log/{slug}.md"
    return f"{member_prefix(member_key)}knowledge/{slug}.md"


def _read_quarantine_file(store: WikiStore, quarantine: str, rel: str) -> str:
    path = f"{quarantine}{rel}".replace("//", "/")
    doc = store.read(path)
    body = doc.body
    if not body.strip():
        body = f"# {_title_from_import(rel, '')}\n\n_Imported from {rel}._\n"
    return body


def _title_from_import(rel_path: str, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return PurePosixPath(rel_path).stem.replace("-", " ").replace("_", " ")


def _write_link_stub(
    member_key: str,
    verdict: FileDuplicateVerdict,
    canonical: str,
    *,
    store: WikiStore,
) -> str:
    slug = _slug(PurePosixPath(verdict.path).stem)
    dest = f"{member_prefix(member_key)}knowledge/{slug}-link.md"
    title = _title_from_import(verdict.path, "")
    company_links = [canonical] if not canonical.startswith(f"{member_key}/") else []
    body = (
        f"# {title}\n\n"
        f"This note duplicates existing content at `{canonical}`.\n\n"
        f"See [[{canonical}|canonical page]].\n"
    )
    write_employee_wiki_page(
        dest,
        title,
        body,
        member=member_key,
        duplicate_of=canonical,
        company_links=company_links or None,
        store=store,
        mirror_notion=False,
    )
    return dest


def _rewrite_wikilinks(body: str, layout_map: dict[str, str]) -> str:
    if not layout_map:
        return body

    def repl(match: re.Match[str]) -> str:
        target = match.group(1)
        label = match.group(2)
        mapped = layout_map.get(target) or layout_map.get(PurePosixPath(target).name)
        if not mapped:
            return match.group(0)
        if label:
            return f"[[{mapped}|{label}]]"
        return f"[[{mapped}]]"

    return WIKILINK_RE.sub(repl, body)
