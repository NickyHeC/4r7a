"""Promote approved external wiki mounts from quarantine."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from company_brain.external_sources_config import (
    ExternalSourcesConfig,
    MountRecord,
    load_external_sources,
    save_external_sources,
    utc_now_iso,
)
from company_brain.wiki.duplicate_detect import FileDuplicateVerdict, parse_duplicate_report
from company_brain.wiki.external_paths import (
    external_landing_path,
    external_promote_prefix,
    external_quarantine_rel,
    source_slug,
)
from company_brain.wiki.name_migrate import migrate_rel_path, migrate_title
from company_brain.wiki.publish import UPDATE, write_wiki_page
from company_brain.wiki.store import LocalWikiStore, WikiStore

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


@dataclass
class ExternalPromoteResult:
    import_id: str
    source: str
    promoted: list[str]
    linked: list[str]
    dropped: list[str]
    layout_map: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "source": self.source,
            "promoted": self.promoted,
            "linked": self.linked,
            "dropped": self.dropped,
            "layout_map": self.layout_map,
        }


def promote_external_mount(
    source_key: str,
    import_id: str,
    *,
    store: WikiStore | None = None,
    decisions: dict[str, str] | None = None,
    remove_quarantine: bool = True,
    mounted_by: str = "admin",
    default_sync: str | None = None,
    rebuild_catalog: bool = True,
) -> ExternalPromoteResult:
    """Move approved quarantine files into ``wiki/external/{source}/``."""
    store = store or LocalWikiStore()
    key = source_slug(source_key)
    quarantine = external_quarantine_rel(key, import_id)
    report_path = f"{quarantine}duplicate_report.json"
    if not store.exists(report_path):
        raise FileNotFoundError(report_path)

    sources_cfg = load_external_sources()
    spec = sources_cfg.get(key)
    sync_default = default_sync or (spec.default_sync if spec else "company")

    report = parse_duplicate_report(store.read_text(report_path))
    decisions = decisions or {}
    layout_map: dict[str, str] = {}
    promoted: list[str] = []
    linked: list[str] = []
    dropped: list[str] = []
    mounted_at = utc_now_iso()

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
            stub = _write_link_stub(
                key,
                verdict,
                target,
                import_id=import_id,
                mounted_at=mounted_at,
                sync_label=sync_default,
                store=store,
            )
            linked.append(stub)
            layout_map[verdict.path] = stub
            continue

        dest = _propose_dest(key, verdict.path)
        body = _read_quarantine_file(store, quarantine, verdict.path)
        rewritten = _rewrite_wikilinks(body, layout_map)
        title = migrate_title(_title_from_import(verdict.path, rewritten), rel_path=dest)
        write_wiki_page(
            dest,
            title,
            rewritten,
            mode=UPDATE,
            section=f"external/{key}",
            sync_label=sync_default,
            extra_frontmatter={
                "source": "external",
                "external_source": key,
                "external_path": verdict.path,
                "import_id": import_id,
                "mounted_at": mounted_at,
                "duplicate_of": None,
            },
            store=store,
        )
        promoted.append(dest)
        layout_map[verdict.path] = dest

    _write_landing_page(
        key,
        import_id=import_id,
        promoted=promoted,
        linked=linked,
        store=store,
        sync_label=sync_default,
        spec_label=spec.label if spec else key,
    )
    _record_mount(
        sources_cfg,
        key,
        import_id=import_id,
        mounted_by=mounted_by,
        file_count=len(promoted) + len(linked),
        quarantine=quarantine,
    )

    if remove_quarantine:
        qpath = store.abspath(quarantine.rstrip("/"))
        if qpath.exists():
            shutil.rmtree(qpath)

    if rebuild_catalog:
        from company_brain.agents.external_wiki.external_wiki_config import catalog_config

        if catalog_config().rebuild_on_mount:
            _rebuild_catalog()

    return ExternalPromoteResult(
        import_id=import_id,
        source=key,
        promoted=promoted,
        linked=linked,
        dropped=dropped,
        layout_map=layout_map,
    )


def _default_action(verdict: FileDuplicateVerdict) -> str:
    if verdict.verdict == "link":
        return "link"
    if verdict.verdict == "review":
        return "import"
    return verdict.verdict


def _propose_dest(source_key: str, quarantine_path: str) -> str:
    rel = migrate_rel_path(quarantine_path.lstrip("/"))
    return f"{external_promote_prefix(source_key)}{rel}"


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
    source_key: str,
    verdict: FileDuplicateVerdict,
    canonical: str,
    *,
    import_id: str,
    mounted_at: str,
    sync_label: str,
    store: WikiStore,
) -> str:
    stem = PurePosixPath(verdict.path).stem
    dest = f"{external_promote_prefix(source_key)}stubs/{stem}-link.md"
    title = _title_from_import(verdict.path, "")
    body = (
        f"# {title}\n\n"
        f"This note duplicates existing content at `{canonical}`.\n\n"
        f"See [[{canonical}|canonical page]].\n"
    )
    write_wiki_page(
        dest,
        title,
        body,
        mode=UPDATE,
        section=f"external/{source_key}",
        sync_label=sync_label,
        extra_frontmatter={
            "source": "external",
            "external_source": source_key,
            "external_path": verdict.path,
            "import_id": import_id,
            "mounted_at": mounted_at,
            "duplicate_of": canonical,
        },
        store=store,
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


def _write_landing_page(
    source_key: str,
    *,
    import_id: str,
    promoted: list[str],
    linked: list[str],
    store: WikiStore,
    sync_label: str,
    spec_label: str,
) -> None:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {spec_label}",
        "",
        f"External wiki mount (`{source_key}`). Import `{import_id}` promoted {when}.",
        "",
        f"- **Pages:** {len(promoted)}",
        f"- **Link stubs:** {len(linked)}",
        "",
        "## Pages",
        "",
    ]
    for path in sorted(promoted)[:50]:
        title = PurePosixPath(path).stem.replace("-", " ").replace("_", " ")
        lines.append(f"- [[{path}|{title}]]")
    if len(promoted) > 50:
        lines.append(f"- _…and {len(promoted) - 50} more_")
    lines.append("")

    write_wiki_page(
        external_landing_path(source_key),
        spec_label,
        "\n".join(lines).rstrip() + "\n",
        mode=UPDATE,
        section=f"external/{source_key}",
        sync_label=sync_label,
        extra_frontmatter={
            "source": "external",
            "external_source": source_key,
            "import_id": import_id,
            "type": "index",
        },
        store=store,
    )


def _record_mount(
    cfg: ExternalSourcesConfig,
    source_key: str,
    *,
    import_id: str,
    mounted_by: str,
    file_count: int,
    quarantine: str,
) -> None:
    if source_key not in cfg.sources:
        cfg.ensure_source(source_key)
    cfg.append_mount(
        source_key,
        MountRecord(
            import_id=import_id,
            mounted_at=utc_now_iso(),
            mounted_by=mounted_by,
            file_count=file_count,
            quarantine_path=quarantine,
            promote_prefix=external_promote_prefix(source_key),
            status="active",
        ),
    )
    save_external_sources(cfg)


def _rebuild_catalog() -> None:
    from company_brain.agents.external_wiki.content_catalog import ContentCatalogAgent
    from company_brain.config import load_config

    try:
        ContentCatalogAgent(load_config()).run()
    except Exception:
        pass
