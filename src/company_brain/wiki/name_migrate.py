"""Wiki path and title migration to company-brain naming conventions.

Used by ``company-brain migrate-names`` and by import/promote pipelines to
normalize pre-existing Markdown paths before they land in the wiki store.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from company_brain.wiki.store import CONTROL_FILES, MarkdownDoc, WikiStore

Volume = Literal["company", "employee"]

# --- Path renames (legacy rel_path -> canonical) --------------------------------

EXACT_PATH_RENAMES: dict[str, str] = {
    "engineering/github/open-prs.md": "engineering/github/open-pr.md",
    "engineering/github/feature-updates.md": "engineering/github/feature-update.md",
    "engineering/github/product-features.md": "engineering/github/product-feature.md",
    "engineering/linear/stale-projects.md": "engineering/linear/stale-audit.md",
    "finance/expense-reports.md": "finance/expense-report.md",
    "finance/budget-summary.md": "finance/budget-summary.md",
    "finance/company-subscriptions.md": "finance/subscription.md",
    "finance/company-timeline.md": "operations/decisions/timeline.md",
    "finance/manual-accounting.md": "finance/manual-accounting.md",
    "finance/quarterly-metric.md": "finance/quarterly-metric.md",
    "finance/total-assets.md": "finance/total-asset.md",
    "operations/gmail/company-timeline.md": "operations/decisions/timeline.md",
    "operations/gmail/ingest-queue.md": "operations/gmail/ingest-queue.md",
    "operations/gmail/receipt-routing.md": "operations/gmail/receipt-route.md",
    "operations/gmail/investors-crm.md": "operations/gmail/investor.md",
    "operations/gmail/investor-interests.md": "operations/gmail/investor-interest.md",
    "operations/gmail/customer-crm.md": "operations/gmail/customer.md",
    "operations/gmail/media-promotion.md": "operations/gmail/media-promotion.md",
    "operations/gmail/company-connections.md": "operations/gmail/connection.md",
    "operations/gmail/inbound-candidates.md": "operations/gmail/inbound-candidate.md",
    "operations/granola/missed-notes.md": "operations/granola/missed-note.md",
    "admin/table-of-contents.md": "admin/content-catalog.md",
}

# Longest prefix first when applying.
PREFIX_PATH_RENAMES: list[tuple[str, str]] = sorted(
    [
        ("finance/expense-reports/", "finance/expense-report/"),
        ("operations/granola/daily/", "operations/granola/meeting/"),
        ("operations/gmail/vendors/", "operations/gmail/vendor/"),
        ("admin/import-reviews/", "admin/import-review/"),
        ("admin/external-mount-reviews/", "admin/mount-review/"),
        ("engineering/admin/import-reviews/", "admin/import-review/"),
    ],
    key=lambda pair: len(pair[0]),
    reverse=True,
)

EMPLOYEE_SEGMENT_RENAMES = {"work_log": "work-log"}

# --- Title renames --------------------------------------------------------------

EXACT_TITLE_RENAMES: dict[str, str] = {
    "Linear Stale Projects and Issues": "Stale Audit",
    "Linear Slot Check": "Slot Check",
    "Linear Manual Management": "Manual Management",
    "Linear Structure": "Structure Proposal",
    "Granola Missed Notes": "Missed Notes",
    "4r7a Content Catalog": "Content Catalog",
    "Investors CRM": "Investors",
    "Customer CRM": "Customers",
    "Company Connections": "Connections",
    "Investor Interests": "Investor Interest",
    "Company Subscriptions": "Subscriptions",
    "Total Assets": "Total Assets",
}

TITLE_PATTERNS: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"^(.+) Expense Report$"), r"\1 Expenses"),
    (re.compile(r"^Meeting notes — (.+)$"), r"Meetings \1"),
    (re.compile(r"^External mount — (.+)$"), r"Mount Review — \1"),
    (re.compile(r"^Import review — (.+)$"), r"Import Review — \1"),
]


def _vendor_title(match: re.Match[str]) -> str:
    return match.group(1).replace("-", " ").replace("_", " ").title()


VENDOR_TITLE_PATTERN = (re.compile(r"^Vendor — (.+)$"), _vendor_title)

# Gmail routing ``handled`` keys renamed with the 2026-06 naming pass.
SPECIALIST_KEY_RENAMES: dict[str, str] = {
    "gmail_ingest": "ingest",
    "gmail_customer_support": "customer_support",
    "gmail_crm": "connection",
}

FRONTMATTER_PATH_KEYS = frozenset(
    {
        "duplicate_of",
        "canonical_path",
        "external_path",
        "wiki_path",
    }
)

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def migrate_rel_path(rel_path: str, *, volume: Volume = "company") -> str:
    """Return the canonical wiki rel_path for a legacy or imported path."""
    rel = PurePosixPath(rel_path.strip().strip("/")).as_posix()
    if not rel or rel.endswith(".json"):
        return rel_path.strip().strip("/")

    if rel in EXACT_PATH_RENAMES:
        return EXACT_PATH_RENAMES[rel]

    for old_prefix, new_prefix in PREFIX_PATH_RENAMES:
        if rel == old_prefix.rstrip("/"):
            return new_prefix.rstrip("/")
        if rel.startswith(old_prefix):
            return new_prefix + rel[len(old_prefix) :]

    if volume == "employee":
        parts = rel.split("/")
        changed = False
        for i, part in enumerate(parts):
            if part in EMPLOYEE_SEGMENT_RENAMES:
                parts[i] = EMPLOYEE_SEGMENT_RENAMES[part]
                changed = True
        if changed:
            return "/".join(parts)

    return rel


def migrate_title(title: str, *, rel_path: str = "") -> str:
    """Return the canonical article title for a legacy title string."""
    text = (title or "").strip()
    if not text:
        stem = PurePosixPath(rel_path).stem if rel_path else ""
        return stem.replace("-", " ").title() if stem else text

    if text in EXACT_TITLE_RENAMES:
        return EXACT_TITLE_RENAMES[text]

    for pattern, repl in (*TITLE_PATTERNS, VENDOR_TITLE_PATTERN):
        if isinstance(repl, str):
            updated = pattern.sub(repl, text)
        else:
            m = pattern.match(text)
            updated = repl(m) if m else text
        if updated != text:
            return updated

    return text


def migrate_specialist_key(key: str) -> str:
    if key in SPECIALIST_KEY_RENAMES:
        return SPECIALIST_KEY_RENAMES[key]
    if key.startswith("gmail_"):
        stripped = key[len("gmail_") :]
        if stripped:
            return stripped
    return key


@dataclass
class PathRename:
    old_path: str
    new_path: str
    volume: Volume


@dataclass
class TitleUpdate:
    rel_path: str
    old_title: str
    new_title: str


@dataclass
class RoutingKeyUpdate:
    rel_path: str
    old_key: str
    new_key: str


@dataclass
class MigrationPlan:
    renames: list[PathRename] = field(default_factory=list)
    title_updates: list[TitleUpdate] = field(default_factory=list)
    link_rewrites: list[tuple[str, str, str]] = field(default_factory=list)
    routing_updates: list[RoutingKeyUpdate] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed_paths(self) -> dict[str, str]:
        return {r.old_path: r.new_path for r in self.renames}


def plan_migration(
    *,
    company_store: WikiStore | None = None,
    employee_store: WikiStore | None = None,
    include_routing: bool = True,
    rewrite_links: bool = True,
) -> MigrationPlan:
    """Scan wiki volumes and build a migration plan (dry-run safe)."""
    plan = MigrationPlan()
    path_map: dict[str, str] = {}

    if company_store is not None:
        _plan_volume(company_store, volume="company", plan=plan, path_map=path_map)
    if employee_store is not None:
        _plan_volume(employee_store, volume="employee", plan=plan, path_map=path_map)

    if rewrite_links and path_map:
        _plan_link_rewrites(company_store, path_map, plan)
        _plan_link_rewrites(employee_store, path_map, plan)

    if include_routing and company_store is not None:
        _plan_routing_updates(company_store, plan)

    return plan


def apply_migration(
    plan: MigrationPlan,
    *,
    company_store: WikiStore | None = None,
    employee_store: WikiStore | None = None,
    rebuild_index: bool = False,
) -> dict[str, int]:
    """Execute a migration plan returned by :func:`plan_migration`."""
    counts = {"renamed": 0, "titles": 0, "routing": 0}
    path_map = plan.changed_paths

    stores: dict[Volume, WikiStore | None] = {
        "company": company_store,
        "employee": employee_store,
    }

    for rename in sorted(plan.renames, key=lambda r: r.old_path.count("/"), reverse=True):
        store = stores.get(rename.volume)
        if store is None:
            continue
        src = store.abspath(rename.old_path)
        dest = store.abspath(rename.new_path)
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        counts["renamed"] += 1

    for volume, store in (("company", company_store), ("employee", employee_store)):
        if store is None:
            continue
        for rel in store.list():
            if PurePosixPath(rel).name in CONTROL_FILES:
                continue
            try:
                doc = store.read(rel)
            except FileNotFoundError:
                continue
            serialized = _normalize_doc(doc, rel_path=rel, path_map=path_map)
            if serialized != doc.serialize():
                store.write(rel, MarkdownDoc.parse(serialized))
                counts["titles"] += 1

    if company_store is not None:
        for upd in plan.routing_updates:
            path = company_store.abspath(upd.rel_path)
            if not path.exists():
                continue
            data = json.loads(path.read_text())
            handled = dict(data.get("handled") or {})
            if upd.old_key not in handled:
                continue
            if upd.new_key not in handled:
                handled[upd.new_key] = handled.pop(upd.old_key)
            else:
                handled.pop(upd.old_key, None)
            data["handled"] = handled
            path.write_text(json.dumps(data, indent=2) + "\n")
            counts["routing"] += 1

    if rebuild_index and company_store is not None:
        _rebuild_company_index(company_store)

    return counts


def _plan_volume(
    store: WikiStore,
    *,
    volume: Volume,
    plan: MigrationPlan,
    path_map: dict[str, str],
) -> None:
    targets: dict[str, str] = {}
    for rel in store.list():
        if PurePosixPath(rel).name in CONTROL_FILES:
            continue
        new_rel = migrate_rel_path(rel, volume=volume)
        if new_rel == rel:
            continue
        if new_rel in targets and targets[new_rel] != rel:
            plan.conflicts.append(
                f"{volume}: multiple sources map to {new_rel!r} ({targets[new_rel]!r}, {rel!r})"
            )
            continue
        targets[new_rel] = rel
        if store.exists(new_rel) and new_rel != rel:
            plan.conflicts.append(f"{volume}: target already exists: {new_rel!r} (from {rel!r})")
            continue
        plan.renames.append(PathRename(old_path=rel, new_path=new_rel, volume=volume))
        path_map[rel] = new_rel


def _plan_link_rewrites(
    store: WikiStore | None,
    path_map: dict[str, str],
    plan: MigrationPlan,
) -> None:
    if store is None:
        return
    for rel in store.list():
        if rel not in path_map and rel not in path_map.values():
            # Still rewrite links on pages that reference old paths.
            pass
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        new_body = _rewrite_paths_in_text(doc.body, path_map)
        new_fm = dict(doc.frontmatter)
        fm_changed = False
        for key in FRONTMATTER_PATH_KEYS:
            val = new_fm.get(key)
            if isinstance(val, str) and val in path_map:
                new_fm[key] = path_map[val]
                fm_changed = True
        if isinstance(new_fm.get("related"), list):
            related = [path_map.get(str(x), str(x)) for x in new_fm["related"]]
            if related != new_fm["related"]:
                new_fm["related"] = related
                fm_changed = True
        if new_body != doc.body or fm_changed:
            target = path_map.get(rel, rel)
            plan.link_rewrites.append((rel, target, new_body))
            if fm_changed:
                # Title pass happens in apply via _normalize_doc; stash fm via reread after rename.
                pass


def _plan_routing_updates(store: WikiStore, plan: MigrationPlan) -> None:
    routing_root = store.abspath("operations/gmail/routing")
    if not routing_root.exists():
        return
    for path in sorted(routing_root.rglob("*.json")):
        rel = path.relative_to(store.abspath(".")).as_posix()
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            plan.skipped.append(rel)
            continue
        handled = data.get("handled") or {}
        for old_key, _ts in list(handled.items()):
            new_key = migrate_specialist_key(old_key)
            if new_key != old_key:
                plan.routing_updates.append(
                    RoutingKeyUpdate(rel_path=rel, old_key=old_key, new_key=new_key)
                )


def _normalize_doc(
    doc: MarkdownDoc,
    *,
    rel_path: str,
    path_map: dict[str, str],
) -> str:
    fm = dict(doc.frontmatter)
    body = doc.body

    old_title = str(fm.get("title") or "")
    h1 = _first_h1(body)
    base_title = old_title or h1 or PurePosixPath(rel_path).stem
    new_title = migrate_title(base_title, rel_path=rel_path)

    old_stem = None
    for old_path, new_path in path_map.items():
        if new_path == rel_path:
            old_stem = PurePosixPath(old_path).stem
            break
    if old_stem and fm.get("id") == old_stem:
        fm["id"] = PurePosixPath(rel_path).stem

    if new_title and new_title != old_title:
        fm["title"] = new_title

    for key in FRONTMATTER_PATH_KEYS:
        val = fm.get(key)
        if isinstance(val, str) and val in path_map:
            fm[key] = path_map[val]

    if isinstance(fm.get("related"), list):
        fm["related"] = [path_map.get(str(x), str(x)) for x in fm["related"]]

    body = _rewrite_paths_in_text(body, path_map)
    if new_title and h1 and migrate_title(h1, rel_path=rel_path) == new_title:
        body = _replace_h1(body, new_title)

    return MarkdownDoc(frontmatter=fm, body=body).serialize()


def _rewrite_paths_in_text(text: str, path_map: dict[str, str]) -> str:
    if not path_map:
        return text

    def _wikilink(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        label = match.group(2)
        new_target = path_map.get(target, target)
        if label:
            return f"[[{new_target}|{label}]]"
        return f"[[{new_target}]]"

    updated = WIKILINK_RE.sub(_wikilink, text)
    for old, new in sorted(path_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        updated = updated.replace(f"`{old}`", f"`{new}`")
        updated = updated.replace(old, new)
    return updated


def _first_h1(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _replace_h1(body: str, title: str) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i] = f"# {title}"
            return "\n".join(lines).rstrip() + "\n"
    return body


def _rebuild_company_index(store: WikiStore) -> None:
    from company_brain.wiki.article import Article
    from company_brain.wiki.indexer import rebuild

    articles = []
    for rel in store.list():
        if PurePosixPath(rel).name in CONTROL_FILES:
            continue
        try:
            doc = store.read(rel)
        except FileNotFoundError:
            continue
        articles.append(Article.from_doc(doc, rel_path=rel))
    rebuild(store, articles, {})
