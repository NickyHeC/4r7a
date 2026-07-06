"""Bridge search index — rebuilt from wiki pages passing read gate."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from company_brain.bridge.config import BridgeConfig, load_bridge_config
from company_brain.bridge.read_gate import ReadGate
from company_brain.config import CONFIG_DIR, resolve_employee_wiki_dir, resolve_wiki_dir
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.store import LocalWikiStore


@dataclass
class IndexEntry:
    rel_path: str
    title: str
    sync: str
    volume: str
    department: str = ""
    kind: str = "page"
    tags: list[str] = field(default_factory=list)


@dataclass
class BridgeIndex:
    rebuilt_at: str
    entries: list[IndexEntry] = field(default_factory=list)
    skills: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rebuilt_at": self.rebuilt_at,
            "entries": [asdict(e) for e in self.entries],
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BridgeIndex:
        entries = [IndexEntry(**e) for e in (data.get("entries") or [])]
        return cls(
            rebuilt_at=str(data.get("rebuilt_at") or ""),
            entries=entries,
            skills=dict(data.get("skills") or {}),
        )


def _walk_store(store: LocalWikiStore, volume: str) -> list[tuple[str, dict, str]]:
    root = store.root
    if not root.exists():
        return []
    out: list[tuple[str, dict, str]] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".") or "/." in rel:
            continue
        doc = store.read(rel)
        fm = dict(doc.frontmatter or {})
        title = str(fm.get("title") or path.stem)
        out.append((rel, fm, title))
    return out


def rebuild_index(
    *,
    bridge_cfg: BridgeConfig | None = None,
    config_dir: Path | None = None,
    company_store: LocalWikiStore | None = None,
    employee_store: LocalEmployeeWikiStore | None = None,
) -> BridgeIndex:
    cfg = bridge_cfg or load_bridge_config(config_dir)
    rebuilt_at = datetime.now(timezone.utc).isoformat()
    index = BridgeIndex(rebuilt_at=rebuilt_at)

    company = company_store or LocalWikiStore(root=resolve_wiki_dir())
    employee = employee_store or LocalEmployeeWikiStore(root=resolve_employee_wiki_dir())

    # Index all members' readable pages using a synthetic gate per department bucket.
    seen: set[tuple[str, str]] = set()

    for rel, fm, title in _walk_store(company, "company"):
        sync = str(fm.get("sync") or "")
        dept = ""
        if sync.startswith("location:"):
            dept = sync.split(":", 1)[1]
        key = ("company", rel)
        if key in seen:
            continue
        seen.add(key)
        index.entries.append(
            IndexEntry(
                rel_path=rel,
                title=title,
                sync=sync,
                volume="company",
                department=dept,
                kind="page",
            )
        )

    for rel, fm, title in _walk_store(employee, "employee"):
        sync = str(fm.get("sync") or "")
        member = str(fm.get("member") or rel.split("/", 1)[0])
        key = ("employee", rel)
        if key in seen:
            continue
        seen.add(key)
        index.entries.append(
            IndexEntry(
                rel_path=rel,
                title=title,
                sync=sync,
                volume="employee",
                department=member,
                kind="page",
            )
        )

    for dept, manifest_rel in (cfg.skills_manifest or {}).items():
        index.skills[dept] = _load_skills_manifest(company, manifest_rel)

    _save_index(cfg, index, config_dir)
    return index


def _load_skills_manifest(store: LocalWikiStore, rel_path: str) -> list[dict[str, str]]:
    if not store.exists(rel_path):
        return []
    raw = store.read(rel_path).body
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return []
    skills = data.get("skills") or []
    out: list[dict[str, str]] = []
    for item in skills:
        if isinstance(item, dict) and item.get("id"):
            out.append(
                {
                    "id": str(item["id"]),
                    "title": str(item.get("title") or item["id"]),
                    "path": str(item.get("path") or ""),
                }
            )
    return out


def load_index(cfg: BridgeConfig | None = None, config_dir: Path | None = None) -> BridgeIndex:
    cfg = cfg or load_bridge_config(config_dir)
    path = cfg.config_path(cfg.index_path, config_dir or CONFIG_DIR)
    if not path.exists():
        return BridgeIndex(rebuilt_at="")
    try:
        return BridgeIndex.from_dict(json.loads(path.read_text()))
    except json.JSONDecodeError:
        return BridgeIndex(rebuilt_at="")


def _save_index(cfg: BridgeConfig, index: BridgeIndex, config_dir: Path | None) -> None:
    path = cfg.config_path(cfg.index_path, config_dir or CONFIG_DIR)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index.to_dict(), indent=2) + "\n")
    tmp.replace(path)


def search_entries(
    index: BridgeIndex,
    gate: ReadGate,
    query: str,
    *,
    limit: int = 20,
) -> list[IndexEntry]:
    q = query.strip().lower()
    if not q:
        return []
    hits: list[IndexEntry] = []
    for entry in index.entries:
        if not gate.can_read(entry.rel_path, entry.sync, volume=entry.volume):
            continue
        hay = f"{entry.title} {entry.rel_path} {' '.join(entry.tags)}".lower()
        if q in hay:
            hits.append(entry)
        if len(hits) >= limit:
            break
    return hits
