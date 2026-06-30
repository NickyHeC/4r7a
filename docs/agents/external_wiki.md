# External Wiki Mount — Agent Handbook

Admin-only one-shot import of external Markdown wikis into the **company building**
at `wiki/external/{source}/`. Shared helpers reuse the employee zip import scan and
duplicate detection patterns; targets, provenance, and sync defaults differ.

**Config:** [`config/external_sources.yaml`](../../config/external_sources.yaml) (source registry),
[`config/operations.yaml`](../../config/operations.yaml) → `external_wiki`.
**Plan:** [`docs/plans/external-wiki-mount.md`](../plans/external-wiki-mount.md).

---

## How it runs

```mermaid
flowchart TB
  ZIP[Zip of .md from external source] --> Q[wiki/external/_quarantine/source/import_id/]
  Q --> SCAN[import_scan]
  SCAN --> DUP[duplicate_detect]
  DUP --> REV[external_mount_review]
  REV -->|admin Slack| ADMIN[admin channel]
  REV -->|approve| PROM[external_promote]
  PROM --> EW[wiki/external/source/**]
  EW --> NS[NotionSync]
  PROM --> TOC[content_catalog → admin/table-of-contents.md]
```

Every mount requires admin approval in v1. Promoted pages carry provenance frontmatter
(`external_source`, `import_id`, `sync:`). The admin content catalog at
`admin/table-of-contents.md` is regenerated after each mount (when
`external_wiki.catalog.rebuild_on_mount` is true).

---

## Specialists (`agents/external_wiki/`)

| Agent | Schedule | Description |
|-------|----------|-------------|
| `external_wiki_import.py` | On demand (admin) | Extracts zip into quarantine, security scan + duplicate detection, always dispatches admin review |
| `external_mount_review.py` | On demand (via import) | Writes `admin/external-mount-reviews/{id}.md` and pings admin Slack |
| `content_catalog_agent.py` | On demand / after mount | Regenerates `admin/table-of-contents.md` (view-only fleet catalog) |

**Helpers:** `external_wiki_config.py`, `external_wiki_slack.py`. Wiki-layer helpers:
`external_paths.py`, `external_promote.py`, `content_catalog.py`, `import_zip.py`,
plus reused `import_scan.py` and `duplicate_detect.py` (`detect_external_duplicates`).

---

## Admin runbook

1. Register or confirm the source key in `config/external_sources.yaml`.
2. Run `ExternalWikiImportAgent` with `source_key` and a zip of `.md` files.
3. Review the admin page at `admin/external-mount-reviews/{import_id}.md` and the Slack ping.
4. Approve via `ExternalWikiImportAgent.approve(source_key=..., import_id=...)`.
5. Optionally rebuild the catalog manually: `company-brain catalog`.

Employee zip import reviews live under `admin/import-reviews/` (top-level `admin` section).

---

## Default sync policy

| Content | Default `sync:` | Notion teamspace |
|---------|-----------------|------------------|
| Promoted external pages | `company` (per-source override in registry) | Company |
| Mount review pages | `admin_only` | Admin |
| Content catalog | `admin_only` | Admin (`section_teamspace: admin → admin`) |

---

## What this does and does not do

**Does:** one-shot mount, duplicate linking, provenance stamping, admin audit trail, fleet TOC.

**Does not (v1):** live sync, bidirectional Notion pull, member-initiated mounts, cryptographic provenance.
