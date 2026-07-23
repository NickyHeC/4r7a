"""First-class project registry (human-edited MD).

Page: ``operations/project-registry.md`` — table rows:

| key | wiki_prefixes | channels | teamspace |
|-----|---------------|----------|-----------|
| acme | product/,engineering/ | C0123 | company |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from company_brain.wiki.store import LocalWikiStore, WikiStore

REGISTRY_PATH = "operations/project-registry.md"
REGISTRY_TITLE = "Project Registry"

_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|?\s*$")


@dataclass
class ProjectEntry:
    key: str
    wiki_prefixes: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    teamspace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "wiki_prefixes": list(self.wiki_prefixes),
            "channels": list(self.channels),
            "teamspace": self.teamspace,
        }


def load_registry(*, store: WikiStore | None = None) -> dict[str, ProjectEntry]:
    store = store or LocalWikiStore()
    if not store.exists(REGISTRY_PATH):
        return {}
    try:
        doc = store.read(REGISTRY_PATH)
    except FileNotFoundError:
        return {}
    return parse_registry_body(doc.body or "")


def parse_registry_body(body: str) -> dict[str, ProjectEntry]:
    out: dict[str, ProjectEntry] = {}
    for line in (body or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip()
        if not key or key.lower() in {"key", "-----", "---"}:
            continue
        if set(key) <= {"-"}:
            continue
        prefixes = [p.strip() for p in m.group(2).split(",") if p.strip()]
        channels = [c.strip() for c in m.group(3).split(",") if c.strip()]
        teamspace = m.group(4).strip()
        # Normalize prefixes to end with /
        norm = []
        for p in prefixes:
            p = p.strip().strip("/")
            if p:
                norm.append(p + "/")
        out[key.lower()] = ProjectEntry(
            key=key.lower(),
            wiki_prefixes=norm,
            channels=channels,
            teamspace=teamspace,
        )
    return out


def resolve_project(key: str, *, store: WikiStore | None = None) -> ProjectEntry | None:
    if not key:
        return None
    return load_registry(store=store).get(key.strip().lower())


def channel_project_key(channel_id: str) -> str | None:
    from company_brain.agents.operations.slack import channels_config

    entry = channels_config.get_channel(channel_id) or {}
    raw = entry.get("project") or entry.get("project_key") or ""
    key = str(raw).strip().lower()
    return key or None


def prefixes_for_channel(channel_id: str, *, store: WikiStore | None = None) -> list[str] | None:
    """Return registry prefixes for a channel, or None to fall back to ACL prefixes.

    Resolution order: ``project`` / ``project_key`` on the Slack channel entry,
    then a match against the registry ``channels`` column.
    """
    key = channel_project_key(channel_id)
    if key:
        entry = resolve_project(key, store=store)
        if entry and entry.wiki_prefixes:
            return list(entry.wiki_prefixes)
    cid = (channel_id or "").strip()
    if not cid:
        return None
    for entry in load_registry(store=store).values():
        if cid in entry.channels and entry.wiki_prefixes:
            return list(entry.wiki_prefixes)
    return None


def ensure_registry_stub(*, store: WikiStore | None = None) -> str:
    """Create an empty registry page if missing (MD-first)."""
    from company_brain.wiki.publish import write_wiki_page

    store = store or LocalWikiStore()
    if store.exists(REGISTRY_PATH):
        return REGISTRY_PATH
    body = (
        "Human-edited project scopes for `@wiki` and retrieve.\n\n"
        "| key | wiki_prefixes | channels | teamspace |\n"
        "|-----|---------------|----------|----------|\n"
        "| example | product/,engineering/ |  | company |\n"
    )
    write_wiki_page(
        REGISTRY_PATH,
        REGISTRY_TITLE,
        body,
        mode="update",
        section="operations",
        type_="index",
        sync=False,
        extra_frontmatter={"sync": "admin_only"},
    )
    return REGISTRY_PATH
