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
overrides in `gmail.mailbox_profiles`. **Env:** `GMAIL_*`, `LINEAR_*`, `SLACK_BOT_TOKEN`

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
  end
  IT -->|classify + label| RR[(routing record JSON)]
  TW -->|sent-mail enrich| RR
  GM -->|read RR| SPEC[profile-enabled specialists]
  TW --> DP[decision_propagate]
  TW --> GI[gmail_ingest]
  ON[gmail_onboarding once] --> IT & TW & GM
```

### Schedules (workdays, configurable)

| Agent / action | Default schedule |
|----------------|------------------|
| `inbox_triage` | Every **30 min** |
| `thread_watcher` | Every **15 min** |
| `gmail_manager` dispatch | **08:00, 12:00, 16:00** |
| `inbox_sweep` | **22:00** (via manager) |
| `ingest_queue_review` | **Monday 08:00** |
| `partnership_digest` | **Friday 08:00** |
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
| `Investor Interest` | Keep in inbox |
| `Partnership` | Keep; weekly **partnership_digest** ranks and archives low scores |
| `Founder Networking` | Same as Partnership |
| `Press & Podcast` | **growth_inbound** |
| `Event Invitations` | **growth_inbound** |

**Employee profile:** flat **`Cold Inbound`** only (no nested sub-labels).

### Investor rule (EA profile only)

Confirmed investor emails/domains in **`investors-crm.md`** → **`Investor`** label +
`contact_type: investor`. Everything else cold → **`Cold Inbound/Investor Interest`**.

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
| **`employee`** | Employee Gmail | Flat Cold Inbound & Newsletters; no Investor or Warm intro; no investor_tracker, partnership_digest, receipt_router |
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
**`decision_propagate`** and **`gmail_ingest`** when those agents are enabled.

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
| **Destination** | `operations/gmail/company-timeline.md` |
| **Notion** | Company Timeline |
| **Write mode** | append |

Appends decision section from sent mail. Skips thanks/pass acknowledgments.

### `gmail_ingest.py`

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

All Slack messages below are **severity-gated**: agents emit a `Signal` through a
`Notifier` (built via `operations_slack` helpers like `ingest_notifier()` /
`channel_notifier(channel)`), never a direct Slack call. `info` is logged-only;
only `actionable` / `alert` reach a channel — detect everything, notify selectively.

### `investor_tracker.py` *(EA profile)*

| | |
|---|---|
| **Tags** | `Investor`, `Cold Inbound/Investor Interest` |
| **Destination** | `investors-crm.md`, `investor-interests.md` |
| **Write mode** | append |

### `gmail_customer_support.py`

| | |
|---|---|
| **Tags** | `Customer` |
| **Destination** | Slack `#customer-support` |

Posts summary with source mailbox per customer message.

### `customer_crm.py`

| | |
|---|---|
| **Tags** | `Customer` |
| **Destination** | `customer-crm.md` |
| **Write mode** | append |

Active customers only; wiki list also drives triage classification.

### `growth_inbound.py`

| | |
|---|---|
| **Tags** | `Cold Inbound/Press & Podcast`, `Cold Inbound/Event Invitations` |
| **Destination** | `media-promotion.md` + Slack `#events` or `#growth` |

### `vendor_tracker.py`

| | |
|---|---|
| **Tags** | `Vendor` |
| **Destination** | `operations/gmail/vendors/<slug>.md` |
| **Write mode** | append |

Ops comms per vendor. Finance costs in **`subscription_audit`**.

### `gmail_crm.py`

| | |
|---|---|
| **Tags** | `People`, `Warm intro` (EA only) |
| **Destination** | `company-connections.md` |
| **Write mode** | append |

Excludes `contact_type: investor`.

### `recruiting_inbound.py`

| | |
|---|---|
| **Tags** | `Cold Inbound/Job Seekers` |
| **Destination** | `inbound-candidates.md` |
| **Write mode** | append |

Logs candidates even when auto-archived at triage.

### `partnership_digest.py` *(EA profile)*

| | |
|---|---|
| **Schedule** | **Friday 08:00** |
| **Tags** | Partnership, Founder Networking |
| **Destination** | Slack `#partnerships` (ranked digest) |

Keeps top-scoring messages in inbox; archives the rest.

---

## Cross-platform

### `inbox_task.py`

| | |
|---|---|
| **Tags** | `1. Action`, complex `2. Reply` |
| **Destination** | Linear issue (GraphQL) |
| **Requires** | `LINEAR_API_KEY`, `linear.team_key` |

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
| **Tags** | `Receipts` + subscription sender list |
| **Destination** | `receipt-routing.md` |
| **Write mode** | append |

Weekly gap report vs configured subscription domains. Full Ramp transaction match
deferred to finance agents.

---

## Linear connection (`operations/linear/`)

### `linear_client.py`

Not an agent — shared connection layer for **`inbox_task`** and **`team_on_it`**:

1. **GraphQL API** (default) — `LINEAR_API_KEY` → `api.linear.app/graphql`
2. **Official MCP** — `https://mcp.linear.app/mcp` (Claude SDK agents)
3. **Community CLI** (optional) — `LINEAR_USE_CLI=1` + `linear` on PATH

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

## Not yet built (Gmail)

| Item | Notes |
|------|-------|
| `meeting_scheduler` | — |
| Warm intro classifier | Confident cases only; heuristic TBD |
| `inbox_task` archive on Linear done | Linear-side agent, not gmail sweep |
| Full Ramp receipt cross-check | Gap report shipped; finance reconciliation separate |
| `security_triage` | Auth alerts, wire-transfer patterns |
| `meeting_prep` | Pairs with meeting_scheduler |
