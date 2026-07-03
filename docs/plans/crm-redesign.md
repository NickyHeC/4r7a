# CRM redesign — design + build plan

**Status:** session 6 shipped (2026-07-02). Sessions 7–8 pending.
`docs/agents/operations.md`, `config/notion.yaml`, `config/operations.yaml`, and `memory.md`.

**Scope:** entity-per-person CRM on the wiki MD volume, Notion database mirrors, unified
inbound handling, promotion rules, 7-day inbox retention. **Out of scope this ship:**
customer usage/product fields (note only), growth weekly digest, employee-scoped connection
wikis.

---

## Goals

1. One canonical **contact** per person (`crm/contact/{slug}.md`); `segment` is a property,
   not a folder move.
2. **Inbound** opportunities typed into separate Notion databases; MD mirrors under
   `crm/inbound/{type}/`.
3. **`crm_registry`** — fast email/domain → slug + segment lookup for triage and dedup.
4. Score-gated **`#growth`** alerts for press & events (v1); shared scorer reused for all
   inbound types (wiki always).
5. **7 calendar days** in inbox for inbound CRM mail; archive via `inbox_sweep`.
6. **Promotion:** two-way mail → `connection`; `customer` / `investor` only via signed
   contract or manual index edit.

---

## Wiki layout

```
crm/
  contact/{slug}.md              # canonical entity (all segments)
  customer/_index.md             # confirmed customer index (triage list + admin edit)
  investor/_index.md             # confirmed investor index (triage list + admin edit)
  promotion-log.md               # append-only segment migrations
  _registry.json                 # derived cache (email/domain → slug, segment); rebuild safe
  inbound/
    press-podcast/{slug}.md
    event-invitation/{slug}.md
    partnership/{slug}.md
    founder-networking/{slug}.md
    investor-interest/{slug}.md
    candidate/{slug}.md
    unmatched/{slug}.md          # identity unknown at triage time
```

**Not under CRM**

| Today | After |
|-------|-------|
| `operations/gmail/vendor/` | `finance/vendor/{slug}.md` (finance department listing; ops mail still tags `Vendor`) |
| `people/{member}.md` | unchanged — **employees only** |

Legacy paths (`operations/gmail/investor.md`, `customer.md`, `connection.md`,
`media-promotion.md`, `inbound-candidate.md`, `investor-interest.md`) → migrate via
`name_migrate.py` mappings + one-time content import into entity pages.

---

## Contact entity (`crm/contact/{slug}.md`)

Slug: kebab-case from primary email local-part + domain, or company name when no email
(e.g. `jane-doe-acme-com`).

### Frontmatter (v1)

```yaml
title: "Jane Doe"                    # Notion title
segment: connection                  # customer | investor | connection
canonical_email: jane@acme.com
canonical_domain: acme.com           # optional; set when domain-level match intended
aliases: []                          # additional emails merged manually
main_connection_employee: nicky      # member key; required when segment=connection
status: active                       # active | archived
promoted_from: inbound/partnership   # provenance when auto/manual promotion
promoted_at: 2026-07-02
sources: [gmail:msg_id_abc]
# Reserved for later (do not populate in v1):
# product_tier:
# last_active:
# usage_notes:
```

### Body

- `## Interactions` — append newest-first (Option B): inbound sections land here when
  `contact_slug` is known.
- Short `## Notes` freeform for humans.

### Segment indexes

`crm/customer/_index.md` and `crm/investor/_index.md` hold the **confirmed lists** triage
reads today (email/domain bullets). Editing the index OR setting `segment` on a contact
page triggers registry rebuild. **Contract signed** is the business trigger for adding
to customer/investor index (human/agent documents in promotion log).

---

## Inbound item pages (`crm/inbound/{type}/{slug}.md`)

One page per opportunity (= one Notion DB row). Slug: `{YYYY-MM-DD}-{short-subject-slug}` or
message-id hash when subject empty.

### Frontmatter

```yaml
title: "Podcast invite — Acme FM"
inbound_type: press-podcast        # matches folder
contact_slug: jane-doe-acme-com    # empty → lives under inbound/unmatched/ until linked
message_id: "..."
thread_id: "..."
mailbox: ceo@company.com
triaged_at: 2026-07-02T12:00:00+00:00
received_at: 2026-07-02T11:55:00+00:00
score: 7
score_reasons: ["reputable_domain:acme.com", "keyword:podcast"]
slack_notified: false
status: open                       # open | engaged | promoted | archived
notion_page_id:                    # filled by NotionSync
```

### Body

Structured extract: from, subject, preview, link to Gmail thread. When `contact_slug` is
set, also append a summary `## …` block to `crm/contact/{slug}.md` (dual write).

### Inbound types ↔ triage labels

| Triage label | Inbound folder | Notion DB key |
|--------------|----------------|---------------|
| `Cold Inbound/Press & Podcast` | `press-podcast` | `inbound_press_podcast` |
| `Cold Inbound/Event Invitations` | `event-invitation` | `inbound_event_invitation` |
| `Cold Inbound/Partnership` | `partnership` | `inbound_partnership` |
| `Cold Inbound/Founder Networking` | `founder-networking` | `inbound_founder_networking` |
| `Cold Inbound/Investor Interest` | `investor-interest` | `inbound_investor_interest` |
| `Cold Inbound/Job Seekers` | `candidate` | `inbound_candidate` |

---

## `crm_registry`

**Path:** `crm/_registry.json` (wiki volume; rebuild from contact pages + indexes).

```json
{
  "version": 1,
  "by_email": {
    "jane@acme.com": { "slug": "jane-doe-acme-com", "segment": "connection" }
  },
  "by_domain": {
    "sequoiacap.com": { "slug": "sequoia-capital", "segment": "investor" }
  },
  "updated_at": "2026-07-02T..."
}
```

- **Rebuild:** `company-brain crm rebuild-registry` (new CLI) or end of any contact write.
- **Never hand-edit** during normal ops (same posture as `_backlinks.json`).
- **Triage** reads registry instead of regex-scraping log pages.
- **Dedup rule:** before creating inbound/contact, lookup email → existing slug; attach
  inbound to that contact instead of creating duplicate.

---

## Scoring (`inbound_score.py`)

Shared module; $0 heuristics first (LLM optional later behind cost gate).

| Signal | Weight |
|--------|--------|
| Domain on `config/operations.yaml` → `crm.reputable_domains` | +4 |
| Known press outlet / event org list (config) | +3 |
| Segment already `connection` or `customer` | +2 |
| Relevance keywords per type (partnership/integration/api/…) | +1–2 each |
| Free-email domain (gmail.com, …) | −2 |
| Generic outreach patterns (`quick question`, `reaching out`, …) | −1 |

**Thresholds (configurable):**

```yaml
crm:
  slack_score_threshold: 6          # press + events → #growth when score >= this
  archive_score_threshold: 2        # optional: mark low-priority in wiki only
```

v1 **Slack:** only `press-podcast` and `event-invitation` emit `ACTIONABLE` to `#growth`
when `score >= slack_score_threshold`. Other inbound types write wiki only (scorer runs,
stores score + reasons).

Deprecate for inbound: `#events`, `#partnerships` digest channel, `#growth-inbound` if
present.

---

## Promotion rules

```mermaid
flowchart TD
  IN[inbound item created] --> UNK{contact known?}
  UNK -->|no| UM[crm/inbound/unmatched/]
  UNK -->|yes| CT[section on crm/contact/{slug}]
  TW[thread_watcher] --> TWO{two-way exchange?}
  TWO -->|yes, not dismissive| CON[segment → connection + promotion-log]
  TWO -->|thanks / not interested| DIS[status → archived; no promote]
  ADM[admin: index edit or contract signed] --> CI[segment → customer or investor]
  CI --> PL[promotion-log append]
  CI --> REG[registry rebuild]
  CI --> INB[remove open inbound rows / mark promoted]
```

### Two-way exchange (auto → `connection`)

- Thread has **≥1 inbound** and **≥1 outbound (SENT)** from mailbox.
- Outbound body does **not** match dismissive patterns: `thanks`, `not interested`,
  `pass`, `unsubscribe`, `no thank`, etc.
- Does **not** auto-promote to customer/investor.

### Manual → `customer` / `investor`

- Add email/domain to `crm/customer/_index.md` or `crm/investor/_index.md`, **or**
- Set `segment` on contact + document `contract_signed: true` in promotion log entry.
- Open inbound rows for that contact → `status: promoted`; stop Slack re-alerts.

### `crm/promotion-log.md`

Append-only sections:

```markdown
## 2026-07-02 — jane-doe-acme-com: inbound/partnership → connection

**Trigger:** two-way exchange (thread …)
**Actor:** thread_watcher
```

---

## Inbox retention (`inbox_sweep`)

Add rule (calendar days):

```
IF domain_tags match any CRM inbound label
AND triaged_at + 7 days <= now
AND routing record handled for inbound specialist
AND message still in INBOX
THEN archive
```

- Applies to: press, events, partnership, founder networking, investor interest, candidate.
- **Replaces** `partnership_digest` archive behavior — remove weekly digest agent (or reduce
  to no-op stub until deleted).
- Top-N keep-in-inbox logic from old digest **removed**; retention is time-based only.

---

## Agents (build session)

| Action | Detail |
|--------|--------|
| **New** | `crm/registry.py` — load/rebuild/slookup |
| **New** | `operations/shared/inbound_score.py` |
| **New** | `operations/gmail/inbound_crm.py` — replaces per-type append agents for CRM inbound |
| **Refactor** | `connection.py` → writes/updates `crm/contact/` not log page |
| **Refactor** | `investor_tracker.py` — confirmed → contact segment investor; interest → inbound |
| **Refactor** | `customer_crm.py` — contact segment customer |
| **Refactor** | `growth_inbound.py` — split: press/events → inbound_crm + #growth |
| **Remove** | `partnership_digest.py` after inbound_crm covers partnership + founder networking |
| **Refactor** | `recruiting_inbound.py` → inbound type `candidate` |
| **Refactor** | `vendor_tracker.py` — wiki path `finance/vendor/{slug}.md` |
| **Extend** | `thread_watcher` — two-way detection → promotion helper |
| **Extend** | `inbox_sweep.py` — 7-day CRM inbound archive |
| **Extend** | `classify.py` — remove `"partnership opportunity"` from `SALES_HINTS` |
| **Extend** | `wiki_crm.py` → `crm/` helpers or rename to `company_brain/crm/` package |
| **Migrate** | `name_migrate.py` legacy path map |

Dispatch: `inbound_crm` runs 8/12/4 via `gmail_manager` (same as today’s CRM specialists).
Consolidate handled key to `inbound_crm` or per-type keys — prefer single key with type in
record.

---

## Notion (`config/notion.yaml` additions)

```yaml
section_teamspace:
  crm: company                    # or admin — confirm at connect time

crm_databases:
  inbound_press_podcast:
    database_id: ""
    columns:
      title: Name
      contact: Contact
      score: Score
      status: Status
      received: Received
  inbound_event_invitation: { ... }
  inbound_partnership: { ... }
  inbound_founder_networking: { ... }
  inbound_investor_interest: { ... }
  inbound_candidate: { ... }
  crm_contacts:
    database_id: ""
    columns:
      title: Name
      segment: Segment
      email: Email
      main_connection: "Main connection"
      status: Status
```

Each inbound MD page syncs to its type DB; each `crm/contact/{slug}.md` syncs to
`crm_contacts`. NotionSync discover-or-create; `notion_page_id` in frontmatter.

---

## Config (`config/operations.yaml` additions)

```yaml
crm:
  contact_dir: crm/contact
  inbound_dir: crm/inbound
  registry_path: crm/_registry.json
  promotion_log: crm/promotion-log.md
  customer_index: crm/customer/_index.md
  investor_index: crm/investor/_index.md
  inbound_retention_days: 7
  slack_score_threshold: 6
  reputable_domains: []           # admin-maintained
  growth_channel: "#growth"       # sole inbound alert channel (press + events v1)
```

Remove or repoint legacy `gmail.wiki_paths.*` keys after migration.

---

## Migration checklist

1. `company-brain migrate-names --dry-run` with new mappings.
2. Script/import: split legacy log pages into contact + inbound item pages where possible.
3. Seed `crm/customer/_index.md` + `crm/investor/_index.md` from old list sections.
4. Rebuild registry; run triage dry-run on sample routing records.
5. Update `docs/agents/operations.md` CRM section + mermaid (remove partnership_digest
   from weekly schedule).
6. Remove `partnership_inbound` row from `docs/tabled.md`.
7. `pytest`, `company-brain doctor code`, `doctor naming`.

### Legacy → canonical path map (add to `name_migrate.py`)

| Legacy | Canonical |
|--------|-----------|
| `operations/gmail/investor.md` | `crm/investor/_index.md` |
| `operations/gmail/investor-interest.md` | (split into `crm/inbound/investor-interest/*`) |
| `operations/gmail/customer.md` | `crm/customer/_index.md` |
| `operations/gmail/connection.md` | (split into `crm/contact/*`) |
| `operations/gmail/media-promotion.md` | (split into `crm/inbound/press-podcast/*`) |
| `operations/gmail/inbound-candidate.md` | (split into `crm/inbound/candidate/*`) |
| `operations/gmail/vendor/` | `finance/vendor/` |

---

## Tests (minimum)

- `tests/fixtures/crm/` — registry rebuild, dedup, promotion dismissive phrases
- `inbound_score` cases per type
- `classify`: `"partnership opportunity"` → Partnership not Sales Outreach
- `inbox_sweep`: archives at day 7, not day 6
- Profile: EA enables inbound_crm; employee profile unchanged flat cold inbound

---

## Build order (one concern per session)

1. **Registry + contact entity schema** — no agent changes yet; CLI rebuild.
2. **classify fix + path config** — partnership opportunity; new wiki paths in yaml.
3. **inbound_crm + inbound_score** — press/events/partnership/founder/investor-interest/candidate.
4. **thread_watcher promotion** + promotion-log.
5. **inbox_sweep retention**; delete partnership_digest.
6. **vendor path move** to finance.
7. **Notion DB stubs + sync routing** (if workspace connected).
8. **Migration + docs + tabled cleanup**.

---

## Rule compliance

| Rule | How |
|------|-----|
| naming | kebab slugs; singular folders; `crm/contact/{slug}.md` |
| wiki-data-flow | MD first; `write_wiki_page`; Notion mirror |
| agent-eval | score + notify selective; `$0` classify/registry |
| platform-boundary | no send; CRM proposes; human signs contract / edits index |
| access-control | `crm` teamspace routing in Notion for read ACL |

---

## Deferred (explicit)

- Customer **usage/product** fields on contact — spec later; frontmatter keys reserved.
- Score-gated Slack for partnership, founder networking, investor interest, candidate.
- LLM inbound scoring tier.
- `#events` / `#partnerships` channel cleanup in Slack workspace (config only in v1).
