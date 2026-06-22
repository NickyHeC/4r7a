# FourSeven 四库七阁

The automated platform that covers any information circulation within a company.

FourSeven (seven archives of four repositories) is the maintenance layer for an internal company wiki. The wiki is a directory of **Markdown files (the source of truth)** that is mirrored to [Notion](https://www.notion.so). Agents ingest information from various sources, compile it into structured wiki articles, and sync those Markdown pages to your Notion workspace via the [Notion CLI](https://developers.notion.com/cli/get-started/overview).

The *seven archives of the four repositories* (四库七阁) was the largest library in Chinese history. It refers to the *Siku Quanshu* (四库全书, "Complete Library of the Four Treasuries"), commissioned by the Qianlong Emperor and compiled between 1772 and 1782, which organized its contents into four repositories. Seven hand-copied sets of the collection were produced, each housed in its own imperial archive (阁) — the seven archives that give FourSeven its name.

## Data flow

Information always flows **MD first, Notion second**:

```
intake -> raw/entries/*.md -> absorb (LLM writer) -> wiki/**/*.md (source of truth) -> NotionSync -> Notion (mirror)
```

- **Knowledge path**: `ingest` mechanically writes raw Markdown entries; `absorb` is an LLM writer that synthesizes them into wiki articles (theme-organized, `[[wikilinks]]`, cited sources).
- **Operational path**: department agents write their pages (open PRs, expense reports) directly as Markdown via `write_wiki_page`, then sync.

The wiki Markdown lives on a shared volume (`COMPANY_BRAIN_WIKI_DIR`, e.g. `/workspace/wiki` on a smol cloud VM). The binding to each Notion page is stored in the file's frontmatter (`notion_page_id`).

## Agents

Agents are organized **department → platform → agents**. Each department has one or
more persistent **managers** that dispatch specialist agents based on what they find.
This section is a high-level map of the departments and the platforms they cover —
for the detailed work, scope, sources, and destinations of every agent, see the
**[Agent Handbook](docs/agents/README.md)** (`docs/agents/` — one file per department).

### Engineering

- **GitHub** — open PR tracking, branch/environment status, weekly feature updates, and a user-facing product features list. Dispatched by `github_manager.py`.

### Finance

- **Mercury** — bank transactions, IO card spend, and total-asset snapshots (bank + treasury).
- **Ramp** — card spend categorized by QuickBooks category (via the Ramp MCP server).

Finance has two managers — `monthly_expense.py` and `quarterly_calculation.py` — that
span both platforms, plus department-level cross-platform agents (budget summary,
subscription audit, manual-accounting requests). All read-only at the source.

### Operations

The catch-all department for general platforms that don't belong to a more specific
department (Gmail, Slack ops, Notion ops, Linear, ...).

- **Gmail** — MCP + REST executive assistant (Phases 0–5): triage, CRM, Linear tasks, receipt routing, and **service profiles** (EA / employee / service account). Posture: **read + labels + draft compose only — never send**.
- **Linear** — GraphQL + official MCP (`operations/linear/linear_client.py`) for Gmail task workflows.

## Self-maintaining foundation

Agents run a closed, eval-gated loop in `BaseAgent.execute()`: `should_run` (cheap cost gate) -> `run` -> `verify` (triage: ok / rework / noise), up to `max_iterations`.

- **Eval gate**: state-changing agents implement `verify()`; consequential changes can be verified in an ephemeral [smol](https://github.com/smol-machines/smolvm) sandbox (`COMPANY_BRAIN_SANDBOX=smolvm`) before committing — reproduce, then commit only if it passes.
- **Cost gates**: expensive agents implement `should_run()` using cheap change-detection (`agents/gates.py`) so no LLM is invoked when nothing changed; re-fires dedup via stored "handled" state.
- **Notify selectively**: **every** human-facing message goes through `notify.Notifier` / `Signal` (never a direct Slack call) — detect everything, deliver only what's `actionable`/`alert`; `info` and routine ticks are silent.

## Cloud direction (smol VMs)

The target state runs every agent in an isolated [smol](https://github.com/smol-machines/smolvm) cloud VM: company-brain spans a multi-VM fleet, managers spin up specialist VMs on demand (via the forthcoming `smol machine` CLI), and all VMs share the wiki volume. Agents dispatch through an `AgentRuntime` (`COMPANY_BRAIN_RUNTIME=local|smolcloud`) so the same code runs in-process today and on a VM later. VM config lives in the `Smolfile`.

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
- **Cloud**: the wiki Markdown lives on the smol cloud VM's persistent storage at
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
  project_install.md   # Agent-assisted setup/onboarding runbook (read by your AI coding agent)
  Smolfile             # smol VM definition (image, net allow-list, shared wiki volume)
  wiki/                # Markdown wiki — source of truth (gitignored; shared volume in cloud)
  raw/entries/         # Raw ingested Markdown entries (gitignored)
  config/
    wiki.yaml          # Wiki taxonomy and structure
    notion.yaml        # Notion workspace mapping (generated by init)
    finance.yaml       # Finance schedules, Slack channel, Notion titles, learned categories
    models.yaml        # LLM provider selection (anthropic | openai | open-source GLM-5)
  src/company_brain/
    cli.py             # CLI entry point
    config.py          # Config + wiki-dir/runtime/LLM-provider resolution
    llm/               # LLM provider abstraction (anthropic | openai | open-source GLM-5)
    runtime/           # AgentRuntime / AgentDeployer (local now, smol cloud later)
    notion/            # Notion CLI wrapper + NotionSync (MD -> Notion mirror)
    wiki/              # WikiStore, Article, index, indexer (_index.md/_backlinks), absorb writer, publish helper
    ingestion/         # Ingestion pipeline (writes raw Markdown entries)
    output/            # Formatter and publisher
    agents/            # Agent base classes, organized by department → platform
      engineering/             # Department (may hold multiple managers)
        github_manager.py        # Manager scoped to GitHub — dispatches GitHub specialists
        github/                  # Platform — specialist agents live directly here
          gh.py                  # Read-only GitHub CLI wrapper (shared)
          open_pr.py             # Open PRs -> wiki MD -> Notion (daily)
          branch_monitor.py      # Per-repo env + branch/PR status tables (every morning)
          feature_update.py      # Weekly feature updates -> wiki MD -> Notion (Mondays)
          product_features.py    # User-facing product features -> wiki MD -> Notion (ranked)
          github_onboarding.py   # One-time repo scan on first GitHub connection
      finance/                 # Department (Mercury + Ramp)
        monthly_expense.py       # Manager — monthly expense report (Notion + Slack)
        quarterly_calculation.py # Manager — quarterly metrics (Notion)
        budget_report.py         # Cross-platform — budget summary vs company timeline
        subscription_audit.py    # Cross-platform — recurring spend + overlap audit
        request_manual_accounting.py # Cross-platform — manual categorization + learning loop
        finance_onboarding.py    # One-time historical backfill
        shared/                  # categories, notion_pages, slack, transactions, config
        mercury/                 # Mercury CLI wrapper + specialists
          mercury_client.py
          asset_compile.py
          bank_transaction.py
          mercury_card_spend.py
        ramp/                    # Ramp MCP client + specialist
          ramp_client.py
          ramp_card_spend.py
      operations/              # Department (catch-all for general platforms)
        gmail_manager.py       # Persistent manager (8/12/4 + 10pm sweep)
        shared/                  # gmail_config, routing, labels, classify, scheduling
        gmail/                   # Platform — MCP + REST
          gmail_client.py        # Gmail MCP connection (official Google MCP | Composio)
          gmail_rest.py          # REST: history, labels, archive (gmail.modify)
          inbox_triage.py        # Persistent 30m triage (sole raw-mail reader)
          thread_watcher.py      # Persistent 15m sent-folder watcher
          inbox_sweep.py         # Nightly lifecycle archive rules
          draft_reply.py         # MCP draft compose for simple Reply threads
          decision_propagate.py  # Decision → company timeline wiki
          gmail_ingest.py        # Ingest → raw entries
          ingest_queue_review.py # Ambiguous ingest queue + weekly #ingest ping
          attachment_router.py   # Attachments → wiki volume
          investor_tracker.py    # Investor CRM + interests
          gmail_customer_support.py  # Customer → Slack
          customer_crm.py        # Customer wiki CRM
          growth_inbound.py      # Press/events routing
          vendor_tracker.py      # Per-vendor wiki pages
          gmail_crm.py           # People → Company Connections
          recruiting_inbound.py  # Job seekers → candidates wiki
          partnership_digest.py  # Weekly ranked partnership digest
          inbox_task.py          # Action / complex Reply → Linear
          team_on_it.py          # Team On It → Linear + Slack
          duplicate_across_mailboxes.py
          receipt_router.py      # Weekly receipt gap report
          gmail_onboarding.py    # One-time labels + backfill + seeds
        linear/                  # Platform — GraphQL + MCP
          linear_client.py
```

## Configuration

- **`config/wiki.yaml`** defines the wiki taxonomy: sections, article types, and writing conventions.
- **`config/notion.yaml`** maps wiki sections to Notion page IDs. Generated by `company-brain init`.
- **`config/finance.yaml`** holds finance schedules, the Slack channel, Notion page titles, and learned categories.
- **`config/operations.yaml`** holds operations settings (e.g. the Gmail connection provider and write posture). Secrets stay in `.env`.
- **`config/models.yaml`** selects the LLM provider behind every agent via `COMPANY_BRAIN_LLM_PROVIDER`.
- The wiki Markdown lives under `COMPANY_BRAIN_WIKI_DIR` (default `./wiki`), with control files `_index.md`, `_backlinks.json`, and `_absorb_log.json`.

## License

MIT