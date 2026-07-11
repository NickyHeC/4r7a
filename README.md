# FourSeven 四库七阁

The automated platform that covers any information circulation within a company.

FourSeven (seven archives of four repositories) is the maintenance layer for an internal company wiki. The wiki is a directory of **Markdown files (the source of truth)** that is mirrored to [Notion](https://www.notion.so). Agents ingest information from various sources, compile it into structured wiki articles, and sync those Markdown pages to your Notion workspace via the [Notion CLI](https://developers.notion.com/cli/get-started/overview).

The *seven archives of the four repositories* (四库七阁) was the largest library in Chinese history. It refers to the *Siku Quanshu* (四库全书, "Complete Library of the Four Treasuries"), commissioned by the Qianlong Emperor and compiled between 1772 and 1782, which organized its contents into four repositories. Seven hand-copied sets of the collection were produced, each housed in its own imperial archive (阁) — the seven archives that give FourSeven its name.

## Expectations

FourSeven is built to boost startup operational efficiency. The goal is **work-ahead,
not block**: agents finish agent-suitable work on schedule *before* your attention is
needed — the Monday standup wiki is ready Sunday evening, expense reports are compiled
before review, drafts sit in Gmail waiting for you to send. The system should move
faster than you, not hold you up waiting on it.

**Automate what agents can; keep humans where judgment matters.** Not everything will
be automated, and not everything should be. Approvals, policy calls, relationship
decisions, and actuation at the source (send mail, move money) stay with people.
FourSeven handles ingestion, synthesis, scheduling prep, and wiki sync so your team
contributes where human processing actually adds value — that pairing is what produces
boosted efficiency, not full replacement.

You still need to participate. Agents save time when you work with them, but they
cannot chase you down or hold you accountable — you can ignore their messages with no
consequences. The people who benefit most are the ones who want to be helped.

Operations work is part of a startup's day-to-day. Most of the boring prep is handled
here; get your head down and finish the rest.

**Work-ahead is not nudging.** Features like `pending_reply_monitor`, `follow_up_nudger`,
`daily_brief`, `stale_action_escalator`, and draft-unsent nudges are intentionally out
of scope: agents prepare work before you need it; they do not chase you to do yours.
We keep the features that earn their place and skip code that adds noise without enough
payoff.

## Data flow

Information always flows **MD first, Notion second**:

```mermaid
flowchart TD
  subgraph knowledge [Knowledge path]
    IN[ingest] --> RAW[raw/entries]
    RAW --> ABS[absorb LLM writer]
    ABS --> WIKI
  end

  subgraph departments [Operational agents]
    ENG[Engineering\nGitHub · Linear]
    FIN[Finance\nMercury · Ramp]
    OPS[Operations\nGmail · GCal · Granola]
    EW[Employee Wiki\nper-member work logs]
  end

  WIKI[(wiki/**/*.md\nsource of truth)]
  EWIKI[(employee_wiki/**/*.md\nper-member buildings)]
  NOTION[Notion mirror]

  ENG -->|write_wiki_page| WIKI
  FIN -->|write_wiki_page| WIKI
  OPS -->|write_wiki_page| WIKI
  ABS --> WIKI
  ENG -. work events .-> EW
  OPS -. work events .-> EW
  EW -->|materializers| EWIKI
  WIKI --> NotionSync --> NOTION
  EWIKI --> NotionSync
```

```
intake -> raw/entries/*.md -> absorb (LLM writer) -> wiki/**/*.md (source of truth) -> NotionSync -> Notion (mirror)
```

- **Knowledge path**: `ingest` mechanically writes raw Markdown entries; `absorb` is an LLM writer that synthesizes them into wiki articles (theme-organized, `[[wikilinks]]`, cited sources).
- **Operational path**: department agents write their pages (open PRs, expense reports) directly as Markdown via `write_wiki_page`, then sync.

The wiki Markdown lives on a shared volume (`COMPANY_BRAIN_WIKI_DIR`, e.g. `/workspace/wiki` on a cloud VM). The binding to each Notion page is stored in the file's frontmatter (`notion_page_id`).

## Agents

Agents are organized **department → platform → agents**. Each department has one or
more persistent **managers** that dispatch specialist agents based on what they find.
This section is a high-level map of the departments and the platforms they cover —
for the detailed work, scope, sources, and destinations of every agent, see the
**[Agent Handbook](docs/agents/README.md)** (`docs/agents/` — one file per department).

### Engineering

- **GitHub** — open PR tracking, branch/environment status, weekly feature updates, and a user-facing product features list. Dispatched by `github_manager.py`.
- **Linear** — the cross-platform task hub. `linear_manager.py` polls for terminal issues and propagates completion to the originating platform; specialists handle slot checks, stale audits, manual management, and workspace structure proposals. A `task_bindings` registry gives every task one identity across Gmail, Granola, Slack, and Notion (`engineering/linear/`).

### Finance

- **Mercury** — bank transactions, IO card spend, and total-asset snapshots (bank + treasury).
- **Ramp** — card spend categorized by QuickBooks category (via the Ramp MCP server).

Finance has two managers — `monthly_expense.py` and `quarterly_calculation.py` — that
span both platforms, plus department-level cross-platform agents (budget summary,
subscription audit, manual-accounting requests). All read-only at the source.

### Operations

The catch-all department for general platforms that don't belong to a more specific
department (Gmail, Slack ops, Notion ops, ...).

- **Gmail** — MCP + REST executive assistant (Phases 0–5): triage, CRM, Linear task creation (via the engineering Linear client), receipt routing, meeting scheduling (`ext_meeting_scheduler` + GCal), and **service profiles** (EA / employee / service account). Posture: **read + labels + draft compose only — never send**.
- **Google Calendar** — availability lookup, meeting booking (with Meet links), optional morning Slack agenda DM (off by default).
- **Granola** — meeting notes ingested after each meeting ends (calendar-driven), with a weekly miss check as backstop (business: per-member API keys; enterprise: single company-wide key); meeting action items become Linear tasks. Read-only at the source.
- **Slack** — full operations platform: Events API ingest (tier 0/1 triage), open threads,
  `@wiki` Q&A (channel ACL + Notion citations), customer support orchestrator (Gmail +
  Connect fan-in), onboarding backfill, and HR offboard signals. Action-item threads
  still bind to Linear via `action_items.py`. See [operations handbook](docs/agents/operations.md)
  Slack section; Weave (`@weave` system changes) lives under **Admin**.
- **Notion** — multi-database task registry: links existing task rows into `task_bindings` by Linear ID (read-first) and propagates Linear status back to the correct database row.

### Admin

- **Weave** — separate Slack app for system-change requests (`@weave`). Triage writes
  `admin/change-request/{id}.md`, mirrors to a Notion change-request DB when configured,
  and dispatches draft PRs for approved `config_only` changes (W2 `members.yaml` only;
  `config/roster.yaml` cannot invoke). See [admin handbook](docs/agents/admin.md).

### HR

- **Roster + offboarding** — `config/roster.yaml` for trial/intern/contractor; promote to
  `members.yaml` via `company-brain hr promote`. Offboarding is proposal-only at
  `hr/offboard-proposal/{member}.md` (Workspace/Notion removal stubs in v1). See
  [HR handbook](docs/agents/hr.md).

### Employee Wiki

A cross-cutting substrate giving each employee a **work building** (`employee_wiki/{member}/`) alongside the company building (`wiki/**`) — both Markdown source-of-truth, Notion-mirrored, cross-linked. Employee wikis are **documentation, not evaluation**.

- **Ledger + materializers** — platform agents (Linear, Granola, Gmail, Slack) append attributed events to `config/work_events.jsonl`; `employee_wiki_manager.py` polls and dispatches `work_event_materializer.py`, which writes per-member `work-log/` entries and refreshes `_index.md`. No platform agent dual-writes employee pages.
- **Zip import** — `employee_wiki_import.py` quarantines a zip of `.md` files, runs a deterministic security scan + duplicate detection, and gates the first import behind admin review (`import_review.py`).
- **Notion sync labels** — each page's `sync:` frontmatter (`private` / `company` / `admin_only` / `location:` / `not_synced`) routes it to the right teamspace; `members.yaml` holds the per-member index and ingest/read scopes.

### External Wiki

Admin-only one-shot import of shared external Markdown wikis into `wiki/external/{source}/` (e.g. a friend's startup ops playbook). Reuses the zip quarantine + security scan + duplicate detection pipeline; every mount requires admin approval.

- **Mount pipeline** — `external_wiki_import.py` → quarantine → `external_mount_review.py` → `external_promote.py` with provenance frontmatter (`external_source`, `import_id`, `sync:`).
- **Registry** — `config/external_sources.yaml` tracks mounted sources and history.
- **Admin catalog** — `content_catalog.py` regenerates `admin/content-catalog.md` (view-only fleet TOC mirrored to the admin Notion teamspace). Manual rebuild: `company-brain catalog`.

### Member Bridge (MCP)

A scoped **MCP server** (co-located with the wiki, reached over a private mesh) lets a member's AI coding agent converse with company-brain without direct access to the Markdown wiki. Humans read via Notion teamspaces; member AI agents use the bridge only.

- **Tools** — `report_blocker`, `get_priority`, `search_practices`, `list_skills`, `get_skill`. Blockers are a summary compilation layer; Linear issue tracking stays in each agent's own integration.
- **Scope** — per-member bearer tokens (hashes only); reads are department-scoped (`sync: company` + `sync: location:{dept}` from `members.yaml` `bridge.departments` + own `employee_wiki/{member}/`). Rate limits 60 reads/min, 20 reports/day.
- **Flow** — `report_blocker` → `config/bridge_events.jsonl` → `bridge_manager` → `bridge_event_materializer` → `employee_wiki/{member}/blockers/`; daily `blocker_rollup` writes `engineering/priorities/blockers.md` (deterministic, no LLM over member text).
- **Commands** — `company-brain bridge serve | issue-token | revoke-token | rebuild-index | manager | rollup`; verify with `company-brain doctor bridge`. Client skill: `.cursor/skills/4r7a-bridge/`.

## Self-maintaining foundation

Agents run a closed, eval-gated loop in `BaseAgent.execute()`: `should_run` (cheap cost gate) -> `run` -> `verify` (triage: ok / rework / noise), up to `max_iterations`.

- **Eval gate**: state-changing agents implement `verify()`; consequential changes can be verified in an ephemeral [smolvm](https://github.com/smol-machines/smolvm) sandbox (`COMPANY_BRAIN_SANDBOX=smolvm`) before committing — reproduce, then commit only if it passes.
- **Cost gates**: expensive agents implement `should_run()` using cheap change-detection (`agents/gates.py`) so no LLM is invoked when nothing changed; re-fires dedup via stored "handled" state.
- **Notify selectively**: **every** human-facing message goes through `notify.Notifier` / `Signal` (never a direct Slack call) — detect everything, deliver only what's `actionable`/`alert`; `info` and routine ticks are silent.

## Cloud direction

FourSeven can run on **any cloud VM service** that meets these requirements: a CLI (or API) to spin up and manage VMs, agents in a manager VM can launch nested VMs for specialists, persistent machines with no billing at idle, and cron-based wake for schedule-driven managers where the provider supports it (otherwise managers run persistently in their VM).

**Defaults** (override with `COMPANY_BRAIN_VM_PROVIDER`):

| Mode | Default backend | Tooling |
|------|-----------------|---------|
| Local VM / sandbox | [smolvm](https://github.com/smol-machines/smolvm) (Smol Machines) | `smolvm machine run` with the repo `Smolfile` |
| Cloud fleet | [smol cloud](https://smolmachines.com/) (Smol Machines hosted) | `smol machine` CLI (integration pending) |

The same `Smolfile` spec describes image, egress allow-list, and shared wiki volume mounts for local smolvm runs and cloud deployment. Agents dispatch through `AgentRuntime` (`COMPANY_BRAIN_RUNTIME=local|cloud`) so the same code runs in-process today and on a VM later.

## Setup (agent-assisted)

company-brain is designed to be installed with the help of an AI coding agent.
Open this repo in your AI coding agent and ask it to **"set up company-brain"** —
it follows [`project_install.md`](project_install.md), a step-by-step runbook that picks the mode,
installs the CLIs, connects your platforms (with read-only finance tokens), runs
the onboarding agents, and verifies everything with `company-brain doctor`.

Manual fallback:

```bash
pip install -e .
cp .env.example .env      # fill in tokens
company-brain doctor      # shows mode, wiki location, and what's connected
ntn login && company-brain init
```

### Local vs cloud

- **Local** (default): the wiki Markdown lives in `./wiki` inside the project
  folder (gitignored). Run everything on one machine.
- **Cloud**: the wiki Markdown lives on the cloud VM's persistent storage at
  `/workspace/wiki`. Set `COMPANY_BRAIN_MODE=cloud`.

`company-brain doctor` reports the active mode and connection status. See
`.env.example` for all environment variables.

### Models (which LLM powers the agents)

Agents run on **two SDKs**: the Claude Agent SDK (MCP-native, big-context
reasoning agents) and the OpenAI Agents SDK (provider-flexible specialists). One
knob — `COMPANY_BRAIN_LLM_PROVIDER`, resolved against `config/models.yaml` —
switches the model:

- **`anthropic` / `openai`** — hosted provider APIs via your key. Default for
  **local** installs (no GPU needed).
- **`glm`** — open-source [GLM-5](https://github.com/zai-org/GLM-5) behind an
  OpenAI-compatible endpoint, so **no external tokens are billed**. Easiest install
  is via [Ollama](https://ollama.com) (`ollama pull glm-5`, served at `:11434/v1`).
  It is the **cloud** option (self-hosted on the GPU VM) or a remote open-source
  host a local install connects to via `GLM_BASE_URL`. Locally installing GLM-5 is
  not realistic.

## Commands

| Command                          | Description                                                          |
| -------------------------------- | -------------------------------------------------------------------- |
| `company-brain doctor`           | Show mode, wiki location, runtime, and platform connection status    |
| `company-brain init`             | Discover existing workspace content, set up Notion wiki structure    |
| `company-brain ingest <source>`  | Run an ingestion agent; writes raw Markdown entries to `raw/entries/`|
| `company-brain absorb`           | LLM writer compiles raw entries into wiki Markdown articles, then syncs to Notion |
| `company-brain query <question>` | Query the wiki (reads the Markdown index/backlinks)                  |
| `company-brain sync`             | Push changed wiki Markdown pages to Notion (MD is the source of truth)|
| `company-brain status`           | Show wiki statistics                                                 |
| `company-brain cleanup`          | Audit and enrich articles                                            |


## Project Structure

```
company-brain/
  project_install.md      # Agent-assisted setup runbook
  Smolfile                # VM spec (Smol Machines Smolfile): image, allow_hosts, volumes
  config/                 # wiki, notion, finance, engineering, operations, models, members, bridge
  src/company_brain/
    cli.py · config.py · runtime/ · wiki/ · notion/ · doctor/ · llm/
    agents/               # department → platform → agent
      engineering/        # github_manager, github/, linear/
      finance/            # monthly_expense, quarterly_calculation, mercury/, ramp/
      operations/         # gmail_manager, gmail/, gcal/, granola/
      employee_wiki/      # employee_wiki_manager, materializer, import, onboarding
      bridge/             # bridge_manager, materializer, blocker_rollup
    bridge/               # MCP server, auth, read gate, index, tools
  docs/agents/            # Agent handbook — schedules, diagrams, per-agent detail
  wiki/ · employee_wiki/ · raw/entries/   # Gitignored locally; shared volume in cloud
```

Agent filenames, schedules, and data flow diagrams live in [`docs/agents/`](docs/agents/README.md), not here.

## Configuration

- **`config/wiki.yaml`** defines the wiki taxonomy: sections, article types, and writing conventions.
- **`config/notion.yaml`** maps wiki sections to Notion page IDs. Generated by `company-brain init`.
- **`config/engineering.yaml`** holds engineering settings (Linear team defaults). Secrets stay in `.env`.
- **`config/finance.yaml`** holds finance schedules, the Slack channel, Notion page titles, and learned categories.
- **`config/operations.yaml`** holds operations settings (e.g. the Gmail connection provider and write posture, plus the `employee_wiki` poll/import block). Secrets stay in `.env`.
- **`config/members.yaml`** is the employee-wiki member index — per-member email, status, Notion teamspace, platform bindings, and ingest/read scopes (pointers only; secrets stay in `.env`).
- **`config/models.yaml`** selects the LLM provider behind every agent via `COMPANY_BRAIN_LLM_PROVIDER`.
- The wiki Markdown lives under `COMPANY_BRAIN_WIKI_DIR` (default `./wiki`), with control files `_index.md`, `_backlinks.json`, and `_absorb_log.json`. Per-member employee wikis live under `COMPANY_BRAIN_EMPLOYEE_WIKI_DIR` (default sibling `./employee_wiki`).

## License

MIT