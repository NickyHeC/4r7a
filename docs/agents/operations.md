# Operations — Agent Handbook

Catch-all department for general platforms: **Gmail executive assistant** and **Linear**
task workflows. Code lives under `src/company_brain/agents/operations/`.

**Vision:** a team of agents working alongside the user to complete work and document
information in the company. The **executive assistant** package (**Phases 0–5**) is
**shipped** — triage, CRM, Linear tasks, receipt routing, and service profiles.

In the ideal case, every company Gmail account connects to company-brain and ingest
happens automatically once each mailbox is onboarded.

**Config:** [`config/operations.yaml`](../../config/operations.yaml) — profile
definitions in `gmail.profiles`, active default in `gmail.profile`, per-mailbox
overrides in `gmail.mailbox_profiles`. **Env:** `GMAIL_*`, `GRANOLA_*`, `LINEAR_*`, `SLACK_WIKI_BOT_TOKEN`

**Posture:** Gmail agents **read, label, and draft only — never send**. Finance platforms
stay read-only at the source (see [Finance handbook](finance.md)).

---

## Gmail — how it runs

The Gmail package is a fleet of agents around a **routing record** per message. Only
**`inbox_triage`** reads raw mail on a schedule; specialists act on routing records
keyed by message id.

```mermaid
flowchart TD
  subgraph persistent [Persistent loops]
    IT[inbox_triage every 30m workdays]
    TW[thread_watcher every 15m workdays]
    GM[gmail_manager 8/12/4 + 22:00 workdays]
    GR[meeting_watch 15m poll]
  end
  IT -->|classify + label| RR[(routing record JSON)]
  TW -->|sent-mail enrich| RR
  GM -->|read RR| SPEC[profile-enabled specialists]
  TW --> DP[decision_propagate]
  TW --> GI[ingest]
  SPEC -->|Meeting Request| GCAL[calendar_availability · book_meeting]
  GR --> WIKI[raw entries + daily digest MD]
```

### Schedules (workdays, configurable)

| Agent / action | Default schedule |
|----------------|------------------|
| `inbox_triage` | Every **30 min** |
| `thread_watcher` | Every **15 min** |
| `gmail_manager` dispatch | **08:00, 12:00, 16:00** |
| `inbox_sweep` | **22:00** (via manager) |
| `ingest_queue_review` | **Monday 08:00** |
| `receipt_router` | **Friday 08:00** |

All times in `config/operations.yaml` → `gmail.schedules`.

---

## Routing records

One JSON file per triaged message on the wiki volume:

```
wiki/operations/gmail/routing/<mailbox>/<message_id>.json
```

Example:

```json
{
  "message_id": "...",
  "thread_id": "...",
  "mailbox": "ceo@company.com",
  "triaged_at": "2026-06-18T12:00:00+00:00",
  "attention": "2. Reply",
  "domain_tags": ["Investor", "Cold Inbound/Partnership"],
  "contact_type": "investor",
  "extracted": { "subject": "...", "from": "..." },
  "handled": { "draft_reply": "2026-06-18T16:00:00+00:00" },
  "disposition": { "mark_read": false, "archive_now": false }
}
```

**Two dimensions:** `attention` (1–4 or none) + `domain_tags[]` (multi-tag allowed).

Specialists query **`unhandled_for(specialist_key, …)`** and mark **`handled[specialist_key]`**
when done. Duplicate mailbox copies get `extracted.duplicate_of` and are skipped by
downstream specialists (except `duplicate_across_mailboxes`).

---

## Label taxonomy

### Visibility

Only **attention labels (1–4)** show next to subjects in the Gmail inbox list
(`messageListVisibility: show`). All domain labels are created with **hide** so they
don't clutter the inbox home view; triage still applies them for search and routing.

### Attention (visible, leave unread unless noted)

| Label | Meaning |
|-------|---------|
| `1. Action` | Requires action (sign, deadline, etc.) |
| `2. Reply` | Needs a reply |
| `3. FYI` | Informational |
| `4. Team On It` | Delegate to team (Linear + Slack) |

### Customer

Single **`Customer`** label — active customers only (wiki CRM list drives triage).
Prospect vs customer disambiguation lives in the routing record / CRM logic.

### Cold inbound (EA profile: nested under `Cold Inbound/`)

| Sub-label | Triage disposition |
|-----------|-------------------|
| `Sales Outreach` | Mark read + archive |
| `Job Seekers` | Mark read + archive |
| `Miscellaneous` | Mark read + archive |
| `Investor Interest` | Keep in inbox → **`inbound_crm`** |
| `Partnership` | Keep in inbox → **`inbound_crm`** |
| `Founder Networking` | Keep in inbox → **`inbound_crm`** |
| `Press & Podcast` | **`inbound_crm`** (+ score-gated Slack `#growth` when configured) |
| `Event Invitations` | **`inbound_crm`** (+ score-gated Slack `#growth` when configured) |
| `Job Seekers` | Mark read + archive at triage; **`inbound_crm`** logs to wiki first |

**Employee profile:** flat **`Cold Inbound`** only (no nested sub-labels).

### Investor rule (EA profile only)

Confirmed investor emails/domains in **`crm/investor/_index.md`** → **`Investor`** label +
`contact_type: investor`. Cold interest → **`crm/inbound/investor-interest/`** via
**`inbound_crm`**. Confirmed investors also get **`crm/contact/{slug}.md`** from
**`investor_tracker`**.

Employee profile: no Investor label; investor detection skipped.

### Other domain labels (hidden)

| Label | Applied by | Notes |
|-------|------------|-------|
| `AI Meeting Notes` | triage | Read + archive immediately |
| `Newsletters/<name>` | triage | Read at triage; archive +1 day in sweep (EA). Employee: flat `Newsletters` |
| `Receipts` | triage | Read at triage; archive +1 day in sweep (Ramp match window) |
| `Meeting` / `Meeting Request` | triage | Calendar invites |
| `Ingest` | thread_watcher | Sent-mail enrichment |
| `Vendor` | triage | Billing/renewal comms |
| `People` | triage | Connections (not investors) |
| `Warm intro` | triage | EA only; confident cases |
| `Decision` | thread_watcher | Real decisions in sent mail (not thanks/pass) |

### Disposition at triage

| Type | mark read | archive now | archive later |
|------|-----------|-------------|---------------|
| AI meeting notes | yes | yes | — |
| Newsletters | yes | — | sweep +1 day |
| Receipts | yes | — | sweep +1 day |
| Auto-archive cold (Sales, Job Seekers, Misc) | yes | yes | — |

Label names and auto-archive list: `config/operations.yaml` → `gmail.labels`.

---

## Service profiles

`gmail_manager` runs for **every** connected account. Triage labels and dispatched
specialists follow the active profile.

| Profile | Use case | Key differences |
|---------|----------|-----------------|
| **`executive_assistant`** (default) | Startup founders / CEO | Full label taxonomy, nested cold inbound & newsletters, all specialists |
| **`employee`** | Employee Gmail | Flat Cold Inbound & Newsletters; no Investor or Warm intro; no investor_tracker, receipt_router |
| **`service_account`** | Purpose inboxes | Attention **1–3** only; minimal domain labels; override per mailbox |

**Set profile:** `gmail.profiles` defines each profile's labels and agents;
`gmail.profile` is the default for `GMAIL_MAILBOX`; override per deploy with
`GMAIL_PROFILE=employee`, or per mailbox in `gmail.mailbox_profiles`. See
[`project_install.md`](../../project_install.md).

---

## Manager

### `gmail_manager.py`

| | |
|---|---|
| **State** | persistent |
| **Schedule** | **08:00, 12:00, 16:00, 22:00** on workdays |
| **Source** | Routing records (`wiki/operations/gmail/routing/`) |

At **8/12/4:** runs **`duplicate_across_mailboxes`** first, then every profile-enabled
specialist in dispatch order. Weekly agents only on their configured day/time.
At **22:00:** **`inbox_sweep`** when enabled for the profile.

Does not read Gmail directly — only dispatches specialists via `get_runtime().run()`.

---

## Persistent Gmail agents (`operations/gmail/`)

### `inbox_triage.py`

| | |
|---|---|
| **State** | persistent |
| **Schedule** | Every **30 min** on workdays |
| **Source** | Gmail REST (`historyId` delta or backfill query) |
| **Destination** | Routing record JSON per message |
| **SDK** | None for classify ($0 heuristics); Gmail REST for modify |

**The only raw-mail reader.** Classifies once, applies visible attention + hidden domain
labels, disposition (read/archive), writes routing record. Does **not** dispatch
specialists. Respects active **service profile** for label set and classification.

### `thread_watcher.py`

| | |
|---|---|
| **State** | persistent |
| **Schedule** | Every **15 min** on workdays |
| **Source** | Gmail sent-folder history delta |

Classifies sent mail: acknowledgment vs **decision** vs **ingest-worthy**. Applies
`Decision` / `Ingest` labels when allowed by profile; enriches routing records; dispatches
**`decision_propagate`** and **`ingest`** when those agents are enabled.

---

## Lifecycle & writers

### `inbox_sweep.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | **22:00** workdays via manager |
| **Source** | Gmail + routing records |

Archives: `2. Reply` after sent reply; `3. FYI` after opened; Newsletters +1 day;
Meeting after opened; Receipts +1 day. REST only, no LLM.

### `draft_reply.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | 8/12/4 via manager |
| **Source** | `2. Reply` routing records (simple threads) |
| **Destination** | Gmail draft (never send) |
| **SDK** | Claude Agent SDK + Gmail MCP |
| **Cost gate** | `is_simple_reply_message()` + `changed_since` before LLM |

Creates drafts for low-complexity Reply threads. Skips legal/multi-party/long threads
(handled by **`inbox_task`** → Linear).

### `decision_propagate.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | Dispatched by `thread_watcher` on real decisions |
| **Destination** | `operations/decisions/timeline.md` |
| **Notion** | Company Timeline |
| **Write mode** | append |

Appends decision section from sent mail. Skips thanks/pass acknowledgments.

### `ingest.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | `thread_watcher` or manager |
| **Destination** | `raw/entries/*.md` (clear content) or ingest queue flag |

Clear ingest → raw wiki entries for absorb; ambiguous → **`ingest_queue_review`**.

### `ingest_queue_review.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | **Monday 08:00** via manager |
| **Destination** | `operations/gmail/ingest-queue.md` |
| **Notion** | Ingest Queue |
| **Write mode** | append |

Appends ambiguous items; pings **`#ingest`** on Slack.

### `attachment_router.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | 8/12/4 via manager |
| **Destination** | `operations/gmail/attachments/{contracts,decks,documents,other}/` |

Fetches attachments from triaged mail onto the wiki volume.

---

## CRM & notifications

Entity-per-person CRM on the wiki (MD source of truth), mirrored to Notion database
rows when `config/notion.yaml` → `crm_databases` is populated. Slack alerts are
**severity-gated** via `Notifier` / `Signal` — never direct Slack calls.

```mermaid
flowchart LR
  IC[inbound_crm 8/12/4] --> IN[crm/inbound/type/slug.md]
  IT[investor_tracker] --> CT[crm/contact/slug.md]
  CC[customer_crm] --> CT
  CN[connection] --> CT
  TW[thread_watcher sent mail] --> PR[promotion → connection segment]
  SW[inbox_sweep 22:00] --> AR[archive CRM inbound after 7 days]
  IN --> NS[Notion DB row mirror]
  CT --> NS
```

**Wiki layout:** `crm/contact/{slug}.md` (canonical person), segment indexes at
`crm/customer/_index.md`, `crm/investor/_index.md`, and `crm/lead/_index.md`,
typed inbound under `crm/inbound/{type}/`, derived lookup at `crm/_registry.json`.
Segments: `customer` | `investor` | `connection` | `lead`. **`lead`** = interest
without an existing company relationship (growth lead research); optional
`priority` 1–10 on the contact page. Vendors stay in **`finance/vendor/`** (not CRM).

**CLI:** `company-brain crm seed`, `crm rebuild-registry`, `crm sync-notion`.

### `inbound_crm.py` *(EA profile)*

| | |
|---|---|
| **Tags** | All six cold inbound types (press, events, partnership, founder networking, investor interest, job seekers) |
| **Destination** | `crm/inbound/{type}/{date}-{subject-slug}.md` |
| **Write mode** | update (one page per message) |
| **Slack** | Score ≥ threshold → `#growth` for **press + events only** (v1) |
| **Retention** | **`inbox_sweep`** archives from Gmail **7 calendar days** after `triaged_at` |

Replaces the retired log-page agents (`growth_inbound`, `recruiting_inbound`,
`partnership_digest`).

### `investor_tracker.py` *(EA profile)*

| | |
|---|---|
| **Tags** | `Investor`, `Cold Inbound/Investor Interest` |
| **Destination** | Confirmed → `crm/contact/{slug}.md`; interest → `crm/inbound/investor-interest/` (via **`inbound_crm`**) |
| **Write mode** | append on contact interactions |

Index list: **`crm/investor/_index.md`**.

### `customer_mail_notify.py`

| | |
|---|---|
| **Tags** | `Customer` |
| **Destination** | Slack `#customer-support` |

Posts summary with source mailbox per customer message via the
**`customer_support`** orchestrator (classify → wiki → `#customer-support` notify).

### `customer_support.py` *(cross-platform)*

| | |
|---|---|
| **Sources** | `slack/customer_intake`, `gmail/customer_mail_notify` |
| **Destination** | Bugs → `engineering/issue/` + Linear; features → `product/feature-request*.md`; discussions → open threads |
| **Slack** | `#customer-support` via `customer_support_notifier()` |

Single orchestrator for customer intake classification and routing.

### `customer_crm.py`

| | |
|---|---|
| **Tags** | `Customer` |
| **Destination** | `crm/contact/{slug}.md` (segment `customer`) |
| **Write mode** | append |

Active customers only; **`crm/customer/_index.md`** drives triage classification.

### `vendor_tracker.py`

| | |
|---|---|
| **Tags** | `Vendor` |
| **Destination** | `finance/vendor/<slug>.md` |
| **Write mode** | append |

Ops comms per vendor. Finance costs in **`subscription_audit`**.

### `connection.py`

| | |
|---|---|
| **Tags** | `People`, `Warm intro` (EA only) |
| **Destination** | `crm/contact/{slug}.md` (segment `connection`) |
| **Write mode** | append |

Excludes `contact_type: investor`. Two-way mail can auto-promote to `connection` via
**`thread_watcher`** + `crm/promotion.py` (dismissive outbound replies excluded).

**Promotion:** `customer` / `investor` segments only via signed contract or manual
index edit — never auto-promoted from inbound.

---

## Cross-platform

### `inbox_task.py`

| | |
|---|---|
| **Tags** | `1. Action`, complex `2. Reply` |
| **Destination** | Linear issue (GraphQL) |
| **Requires** | `LINEAR_API_KEY`, `linear.team_key` in `config/engineering.yaml` |

Simple replies stay with **`draft_reply`**.

### `team_on_it.py`

| | |
|---|---|
| **Tags** | `4. Team On It` |
| **Destination** | Linear issue + Slack `#team-ops` |

No Gmail forward (send forbidden). Team picks up from Slack + Linear.

### `duplicate_across_mailboxes.py`

| | |
|---|---|
| **Schedule** | First in each manager dispatch pass |
| **Source** | Routing records across `gmail.connected_mailboxes` |

Marks secondary copies with `extracted.duplicate_of` so specialists don't double-act.

### `receipt_router.py` *(EA profile)*

| | |
|---|---|
| **Schedule** | **Friday 08:00** |
| **Purpose** | Get receipts into the inbox Ramp watches — not transaction reconciliation |
| **Tags** | `Receipts` + subscription sender list |
| **Forwarding** | Copies missing receipts from other **company-domain** mailboxes via Gmail insert (no external send) |
| **Destination** | `receipt_router.destination_mailbox` (default primary) |
| **Wiki** | `operations/gmail/receipt-route.md` (append) |

Ramp auto-attaches from the destination inbox. This agent only routes mail there;
it does not cross-check Ramp transactions (Ramp owns documentation gaps).
Forwarding logic lives in `receipt_forward.py` (invoked by `receipt_router`).

---

## Linear (via engineering connection layer)

Gmail task agents use the **engineering** Linear client — there is no separate
operations Linear platform folder.

### `engineering/linear/linear_client.py`

Cross-department connection layer (see [Engineering handbook](engineering.md)):

1. **GraphQL API** (default) — `LINEAR_API_KEY` → `api.linear.app/graphql`
2. **Official MCP** — `https://mcp.linear.app/mcp` (Claude SDK agents)
3. **Community CLI** (optional) — `LINEAR_USE_CLI=1` + `linear` on PATH

Used by **`inbox_task`** and **`team_on_it`** for issue creation. Team defaults:
`config/engineering.yaml` → `linear.team_key` / `linear.team_id`.

---

## Google Calendar (`operations/gcal/`)

Connection mirrors Gmail: official Google-hosted Calendar MCP at
`https://calendarmcp.googleapis.com/mcp/v1` plus REST (`gcal_rest.py`) for
deterministic agents. OAuth token can be shared with Gmail when calendar scopes
are on the same consent.

| Agent | Schedule | Description |
|-------|----------|-------------|
| `calendar_availability.py` | On demand | Returns open meeting slots (used by `ext_meeting_scheduler`) |
| `book_meeting.py` | On demand | Creates calendar events with guests + Google Meet link |
| `daily_agenda.py` | **08:00** workdays (opt-in) | Slack DM rundown of today's meetings; **off by default** |

#### Gmail cross-platform (`operations/gmail/`)

| Agent | Schedule | Description |
|-------|----------|-------------|
| `ext_meeting_scheduler.py` | Via `gmail_manager` 8/12/4 | Proposes times (draft) or books meetings for `Meeting Request` threads where the user confirmed |

**`ext_meeting_scheduler`** evaluates meeting importance (investor/customer → high;
cold inbound → low). Low-importance slots avoid booking before significant calendar
events. When it books, thread context is written into the Google Calendar event
description — no separate `meeting_prep` agent. Config: `config/operations.yaml` →
`gcal.*`; enable morning DM with `gcal.daily_agenda.enabled: true` + `slack_user`
(or `GCAL_DAILY_AGENDA=1`).

---

## Granola — how it runs

**`meeting_watch.py`** is the persistent agent (polls calendar every 15 min).
It dispatches **`ingest`** after each meeting ends (+ buffer) and runs
**`miss_check`** weekly as the safety net for any missed meetings.

```mermaid
flowchart TD
  GMW[meeting_watch persistent] -->|meeting ended| GI[ingest]
  GMW -->|Friday| MC[miss_check]
  GI --> GT[task]
  GT --> Linear[(Linear + task_bindings)]
```

| Agent | Schedule | Description |
|-------|----------|-------------|
| `meeting_watch.py` | Persistent (15 min poll) | Post-meeting ingest + weekly miss check |
| `ingest.py` | Dispatched per meeting | Raw entries + daily digest wiki page |
| `task.py` | After ingest | Action items → Linear issue + `task_bindings` |
| `miss_check.py` | Weekly (via watch) | Calendar vs ingest gap report |

### Deployment modes

| Mode | API keys | Scope |
|------|----------|-------|
| **business** | One key per member (`GRANOLA_MEMBER_KEYS`) | Personal notes for each roster entry in `granola.members` |
| **enterprise** | Single `GRANOLA_API_KEY` | Public notes (Team-space folders visible to workspace) |

Business mode deduplicates notes by Granola note id across member keys. Enterprise mode
pulls all notes accessible to the company key in one pass.

### Output

1. **Raw entries** — one `raw/entries/*.md` per meeting (tags: `granola`, `meeting`) for absorb.
2. **Daily digest** — `operations/granola/meeting/YYYY-MM-DD.md` (compiled snapshot, `update` mode).

Config: `config/operations.yaml` → `granola.schedule` (`watch_interval_minutes`,
`post_meeting_buffer_minutes`, `miss_check_day`, `miss_check_time`). Client:
`granola/granola_client.py` (REST, read-only). Requires Google Calendar for meeting watch.

### `granola_onboarding.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | Once, on first Granola connection |
| **Source** | Granola (default **30-day** backfill) |

1. Runs **`ingest`** once per day across the backfill window (oldest first).
2. Starts persistent **`meeting_watch`** via `get_runtime().start()` and exits.

---

## Slack — how it runs

**`slack_manager`** polls on a workday schedule and dispatches specialists.
**`company-brain slack events`** runs the Events API hot lane (Socket Mode local,
HTTP cloud). Poll via **`thread_watcher`** remains backup.

```mermaid
flowchart TD
  EV[slack events listener] -->|message| TRI[ingest_triage]
  EV -->|app_mention| AW[ask_wiki / wiki_commands]
  EV -->|reaction| OT[open_threads]
  SM[slack_manager persistent] -->|poll interval| TW[thread_watcher]
  SM -->|each pass| OTM[open_thread_monitor]
  SM -->|each pass| CI[customer_intake]
  SM -->|daily| CR[channel_registry]
  SM -->|daily| TA[thread_absorb]
  TW --> TRI
  TW --> AI[action_items]
  TRI --> CS[customer_support orchestrator]
  CI --> CS
  TRI --> RR[(slack routing records)]
  TA --> RAW[raw/entries]
  RAW --> ABS[absorb]
  OTM --> EW[employee_wiki open-thread.md]
  AI --> TB[(task_bindings + Linear)]
  LM[linear_manager] -->|Done| LC[linear_completed]
  LC --> STR[slack_thread_respond]
  STR --> TB
  AW --> RET[wiki/retrieve hybrid lexical]
```

| Agent | Schedule | Description |
|-------|----------|-------------|
| `slack_manager.py` | Persistent (`poll_interval_minutes`) | Dispatches watcher/monitor/intake; daily `channel_registry` + `thread_absorb` |
| `customer_support.py` | Via intake specialists | Classify customer mail/Slack → wiki + Linear + `#customer-support` |
| `customer_intake.py` | Events hot lane + manager | Slack Connect / customer channels → orchestrator |
| `ingest_triage.py` | Events API + poll backup | Tier 0/1 classify → routing records; dispatches `action_items` / `customer_intake` |
| `ask_wiki.py` | `@wiki` mention (Events) | Channel ACL Q&A via planner fan-out (wiki + CRM + practices, max 3; fail closed) + Notion citations |
| `wiki_planner.py` | Via `ask_wiki` | Parallel retrieve; project registry prefixes when channel has `project:` or registry channel match |
| `thread_absorb.py` | Daily via manager / CLI | Distill closed/aged internal threads → `raw/entries` (no LLM); long threads get burst distill first; skips Connect/customer |
| `burst_distill.py` | Via `thread_absorb` | Segment long threads by idle gap / speaker shift; structured bullets (not an agent) |
| `wiki_commands.py` | `@wiki` mention | `threads`, `help`, `sync now <platform>` (notion/crm/github/posthog); blocked in Connect channels |
| `internal_meeting_scheduler.py` | `@wiki` meeting keywords | Propose/book slots on primary calendar |
| `thread_watcher.py` | Via manager | Poll backup; runs triage on each message |
| `open_thread_monitor.py` | Via manager | Rebuild `employee_wiki/{member}/open-thread.md` from open routing records |
| `action_items.py` | Via triage / watcher | Action thread → Linear + routing record |
| `channel_registry.py` | Daily via manager | Sync `config/slack_channels.json`; auto-join internal channels |
| `events_router.py` / `events_server.py` | CLI `slack events` | Socket Mode or HTTP Events API |
| `weave_events_router.py` / `weave_events_server.py` | CLI `weave events` | Weave app `@weave` mentions |
| `slack_onboarding.py` | Once (`slack onboarding run`) | $0 estimate + backfill; starts `slack_manager` |
| `offboard_signal.py` | `user_change` Events + CLI | Slack deactivation → HR offboard proposal |
| `slack_client.py` | — | Slack Web API (wiki bot; not an agent) |

**Retrieval:** shared [`wiki/retrieve.py`](../../src/company_brain/wiki/retrieve.py) — title boost +
term frequency + simple IDF + age decay (no embeddings). Scope for humans =
channel `wiki_prefixes`, or project registry prefixes from
`operations/project-registry.md` / channel `project:`; agents use `bridge.departments`.
Encyclopedia absorb uses urgency lanes (`urgent` / `normal` / `bulk` in
`config/wiki.yaml` → `absorb`) and soft length guidance (~800–1200 words); skips
while the fleet pause gate is active.

**CLI:** `company-brain slack events`, `slack sync-channels`, `slack thread-absorb [--force]`,
`slack channel list|tag|enable-connect`, `slack onboarding estimate|run`, `weave events`,
`weave poll-approvals`, `hr promote|offboard`

Config: `config/operations.yaml` → `slack_platform`; `config/slack_channels.json`
for per-channel ingest scope. Env: `SLACK_WIKI_BOT_TOKEN`, `SLACK_WIKI_APP_TOKEN`
(Socket Mode), optional `SLACK_WIKI_SIGNING_SECRET` (HTTP).

Completion replies: `engineering/linear/linear_completed/slack_thread_respond.py`
(dispatched when a bound Slack task reaches Done in Linear).

**Onboarding** (`slack_onboarding.py`):

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | Once, on first Slack connection |
| **CLI** | `company-brain slack onboarding estimate` ($0 count), `slack onboarding run [--days N] [--all] [--absorb]` |

Backfills routing records via `ingest_triage`, optionally runs absorb on raw entries,
then starts `slack_manager` via `get_runtime().start()`.

**Weave** — see [admin handbook](admin.md). **`company-brain weave events`** for the
Weave app listener; change requests at `admin/change-request/{id}.md`.

**HR** — see [HR handbook](hr.md). Roster in `config/roster.yaml`; W2 in `members.yaml`.
`company-brain hr promote` / `hr offboard`.

---

## Notion — how it runs

Notion is the human visualizer/edit surface for the MD wiki. Default teamspaces:
**admin** + **company** (engineering/product/growth route to company unless optional
splits are configured). Persistent **`notion_manager`** polls the full Notion surface:
page sync, `@wiki`, conflicts, page moves, stale/archive, task DBs, CRM mirrors, and
Weave approval rows.

```mermaid
flowchart TD
  NM[notion_manager] -->|poll| SP[sync_pull]
  NM --> WD[wiki_directive]
  NM --> CR[conflict_resolution]
  NM --> CA[conflict_apply]
  NM --> PS[page_system]
  NM --> ST[stale_review]
  NM --> DC[deprecated_collector]
  NM --> TS[task_scanner]
  NM --> OD[orphan_discovery weekly]
  NM --> CRM[crm Notion sync]
  NM --> WV[weave approval poll]
  SP -->|Notion ahead / merge| MD[(wiki MD)]
  WD -->|fill or move| MD
  CR -->|evidence or escalate| MD
  CA -->|admin choice| MD
  PS -->|relocate / stub TTL| MD
  ST --> RQ[review.md]
  OD --> OR[admin/notion-orphan-review]
  DC -->|Archive parent| N[(Notion pages)]
  AG[department agents] -->|write_wiki_page| MD
  MD --> NS[NotionSync push]
  NS --> N
  SP --> N
  TS --> NDB[(Notion task DBs)]
  GT[granola task] -->|create row| SYNC[task_sync]
  LC[linear_completed] -->|status update| SYNC
  SYNC --> NDB
```

**Manager:** `notion_manager.py` — persistent; interval from
`config/operations.yaml` → `notion_platform.poll_interval_minutes`.

| Agent | Schedule | Description |
|-------|----------|-------------|
| `sync_pull.py` | Via manager | Pull human Notion edits → MD; merge when compatible; mark `sync_conflict` when not |
| `wiki_directive.py` | Via manager | Plain-text `@wiki` on page: fill (teamspace-scoped) and/or move; respect `external` |
| `conflict_resolution.py` | Via manager | Evidence tie-break or escalate to Conflict Resolutions log + Notion DB |
| `conflict_apply.py` | Via manager | Apply admin `resolved_md` / `resolved_notion` from Notion DB |
| `page_system.py` | Via manager | Relocate `page_relocate_to` pages; expire move stubs (`stub_ttl_days`) |
| `stale_review.py` | Via manager | Flag idle active pages → `operations/notion/review.md` (+ optional review DB) |
| `deprecated_collector.py` | Via manager | Archive Notion page under Archive parent when all four eligibility rules hold |
| `task_scanner.py` | Via manager | Query updated task DB rows; link by Linear ID (read-first) |
| `orphan_discovery.py` | Weekly via manager | Crawl configured teamspace roots; unbound pages → `admin/notion-orphan-review/` (Adopt / Ignore / Archive; never auto-adopt) |
| `task_sync.py` | Via propagation / Granola ingest | Create or update Notion row for a binding |
| `db.py` / `conflict_store.py` | — | Helpers (not agents) |

Also each manager pass: **CRM** `sync_all_crm` and **Weave** `poll_approved_dispatch`.

**Archive eligibility (all required):** MD idle ≥ `archive_idle_days`, `status: done` / past
`end_date`, Notion idle ≥ same window, no shared link confirmed (`shared_link: false` or
`no_shared_link: true`). MD retained.

**Push policy:** signature-gated `NotionSync`. New pages skipped when
`mirror_enabled: false` (onboarding ingest-only).

**Conflicts / review:** `operations/notion/conflict-resolution.md`,
`operations/notion/review.md`; optional DBs in `config/notion.yaml`.

Config: `config/notion.yaml` → teamspaces, archive_parents, conflict/review DBs.
CLI: `company-brain notion manager [--once]`, `notion sync-pull`,
`notion onboarding run [--confirm-mirror]`.

Requires `ntn` CLI authenticated. Task scanner also started by **`linear_onboarding`**
when a task `database_id` is set.

### `notion_onboarding.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | Once, early in install (after MD wiki setup) |
| **Source** | Notion workspace |

1. Scan workspace; ingest existing pages → MD (`sync=False` / no push) when present.
2. Structured alongside tree + Archive parents only if workspace empty **or**
   `--confirm-mirror` (large reorg confirm gate).
3. Without confirm on a non-empty workspace: ingest-only (`mirror_enabled: false`).
4. Starts **`notion_manager`** via `get_runtime().start()` and exits.

Deferred: accounting/CRM review-queue expansions —
[`docs/tabled.md`](../tabled.md).

---

## Onboarding

### `gmail_onboarding.py`

| | |
|---|---|
| **State** | ephemeral |
| **Schedule** | Once, on first Gmail connection |
| **Source** | Gmail (default **30-day** backfill) |

1. Ensures label taxonomy for the mailbox profile.
2. Seeds CRM wiki pages (profile-filtered).
3. Runs backfill triage.
4. Starts persistent **`inbox_triage`**, **`thread_watcher`**, **`gmail_manager`** via
   `get_runtime().start()` and exits.

---

## Deferred work

See [`docs/tabled.md`](../tabled.md) — Operations (Gmail, Slack, Notion, other).
