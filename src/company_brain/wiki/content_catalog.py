"""Build the admin content catalog (table of contents) from wiki trees."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

from company_brain.config import resolve_employee_wiki_dir
from company_brain.external_sources_config import load_external_sources
from company_brain.wiki.external_paths import admin_table_of_contents_path
from company_brain.wiki.store import LocalWikiStore, WikiStore


@dataclass
class CatalogPage:
    rel_path: str
    title: str
    notion_page_id: str | None = None


@dataclass
class EmployeeBuildingSummary:
    member_key: str
    page_count: int


@dataclass
class ContentCatalog:
    rebuilt_at: str
    company_sections: dict[str, list[CatalogPage]] = field(default_factory=dict)
    external_mounts: dict[str, list[CatalogPage]] = field(default_factory=dict)
    employee_buildings: list[EmployeeBuildingSummary] = field(default_factory=list)
    admin_pages: list[CatalogPage] = field(default_factory=list)
    mount_metadata: dict[str, str] = field(default_factory=dict)

    @property
    def company_page_count(self) -> int:
        return sum(len(pages) for pages in self.company_sections.values())

    @property
    def external_page_count(self) -> int:
        return sum(len(pages) for pages in self.external_mounts.values())


def build_content_catalog(
    *,
    store: WikiStore | None = None,
    include_employee_wiki: bool = True,
) -> ContentCatalog:
    store = store or LocalWikiStore()
    rebuilt_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    catalog = ContentCatalog(rebuilt_at=rebuilt_at)

    for rel in _content_paths(store):
        doc = store.read(rel)
        title = str(doc.frontmatter.get("title") or PurePosixPath(rel).stem)
        page = CatalogPage(
            rel_path=rel,
            title=title,
            notion_page_id=doc.frontmatter.get("notion_page_id"),
        )
        if rel.startswith("admin/"):
            catalog.admin_pages.append(page)
        elif rel.startswith("external/") and not rel.startswith("external/_quarantine/"):
            source = rel.split("/", 2)[1] if rel.count("/") >= 1 else "external"
            catalog.external_mounts.setdefault(source, []).append(page)
        else:
            section = str(doc.frontmatter.get("section") or _top_section(rel))
            catalog.company_sections.setdefault(section, []).append(page)

    sources = load_external_sources()
    for key, spec in sources.sources.items():
        active = next((m for m in reversed(spec.mounts) if m.status == "active"), None)
        if active:
            catalog.mount_metadata[key] = active.mounted_at or spec.label
        else:
            catalog.mount_metadata[key] = spec.label

    if include_employee_wiki:
        catalog.employee_buildings = _employee_summaries()

    for pages in catalog.company_sections.values():
        pages.sort(key=lambda p: p.rel_path)
    for pages in catalog.external_mounts.values():
        pages.sort(key=lambda p: p.rel_path)
    catalog.admin_pages.sort(key=lambda p: p.rel_path)

    return catalog


def render_catalog_markdown(catalog: ContentCatalog) -> str:
    lines = [
        "# Content Catalog",
        "",
        f"_Last rebuilt: {catalog.rebuilt_at}. View-only — edit content in the wiki MD volume._",
        "",
        f"## Company wiki ({catalog.company_page_count} pages)",
        "",
    ]

    for section in sorted(catalog.company_sections):
        pages = catalog.company_sections[section]
        lines.append(f"### {section} ({len(pages)})")
        lines.append("")
        for page in pages[:30]:
            lines.append(_page_line(page))
        if len(pages) > 30:
            lines.append(f"- _…and {len(pages) - 30} more in `{section}/`_")
        lines.append("")

    if catalog.external_mounts:
        lines.append(f"## External mounts ({catalog.external_page_count} pages)")
        lines.append("")
        for source in sorted(catalog.external_mounts):
            pages = catalog.external_mounts[source]
            mounted = catalog.mount_metadata.get(source, "")
            header = f"### {source}"
            if mounted:
                header += f" (mounted {mounted[:10]})" if "T" in mounted else f" ({mounted})"
            lines.append(header)
            lines.append("")
            for page in pages[:20]:
                if page.rel_path.endswith("/_index.md"):
                    continue
                lines.append(_page_line(page))
            if len(pages) > 20:
                lines.append(f"- _…and {len(pages) - 20} more_")
            lines.append("")

    if catalog.employee_buildings:
        lines.append(f"## Employee wikis ({len(catalog.employee_buildings)} buildings)")
        lines.append("")
        for b in sorted(catalog.employee_buildings, key=lambda x: x.member_key):
            lines.append(
                f"- **{b.member_key}** — {b.page_count} pages · `employee_wiki/{b.member_key}/`"
            )
        lines.append("")

    if catalog.admin_pages:
        lines.append("## Admin audit")
        lines.append("")
        for page in catalog.admin_pages:
            lines.append(_page_line(page))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def catalog_wiki_path() -> str:
    return admin_table_of_contents_path()


def _content_paths(store: WikiStore) -> list[str]:
    skip_prefixes = ("raw/", "external/_quarantine/")
    skip_names = {"_index.md", "_backlinks.json", "_absorb_log.json"}
    out: list[str] = []
    for rel in store.list():
        if not rel.endswith(".md"):
            continue
        if any(rel.startswith(p) for p in skip_prefixes):
            continue
        if PurePosixPath(rel).name in skip_names:
            continue
        if "/_quarantine/" in rel:
            continue
        out.append(rel)
    return out


def _top_section(rel_path: str) -> str:
    parts = PurePosixPath(rel_path).parts
    return parts[0] if parts else "general"


def _page_line(page: CatalogPage) -> str:
    notion = f" · Notion `{page.notion_page_id}`" if page.notion_page_id else ""
    return f"- [[{page.rel_path}|{page.title}]]{notion}"


def _employee_summaries() -> list[EmployeeBuildingSummary]:
    root = resolve_employee_wiki_dir()
    if not root.exists():
        return []
    summaries: list[EmployeeBuildingSummary] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        count = sum(1 for p in entry.rglob("*.md") if "/imports/_quarantine/" not in str(p))
        summaries.append(EmployeeBuildingSummary(member_key=entry.name, page_count=count))
    return summaries
