# Repo Memory Log

**Purpose: read this first.** This file is the fast path to development context so
an AI coding agent does not have to read the entire project to understand how it
got here. Skim the recent entries to learn the current architecture and recent
decisions, then dive into specific files only as needed (saves tokens/time).

A running log of significant actions, decisions, and changes. Newest entries on
top. Each entry: date, summary, key changes, and the commit it landed in (or
"working tree" if not yet committed). After meaningful work, prepend a new entry.

---

## 2026-06-18 — Gmail Phase 4 + Linear connection (working tree)

- **Linear connection** (`operations/linear/linear_client.py`): GraphQL issue
  create (default), official MCP at `mcp.linear.app`, optional community `linear`
  CLI when `LINEAR_USE_CLI=1`. Config: `linear.team_key` / `team_id` in
  `config/operations.yaml`; `LINEAR_API_KEY` in `.env`.
- **Phase 4 agents**: `inbox_task` (1. Action + complex 2. Reply → Linear),
  `team_on_it` (4. Team On It → Linear + Slack), `duplicate_across_mailboxes`,
  `receipt_router` (Friday weekly gap report). Routing skips `duplicate_of`
  records for downstream specialists.
- `doctor` Linear check; Smolfile `api.linear.app` + `mcp.linear.app`; docs in
  `project_install.md`, `agent_list.md`, README.

## 2026-06-18 — Gmail Phase 3 CRM + notifications (working tree)

- **Phase 3 agents**: `investor_tracker`, `gmail_customer_support`, `customer_crm`,
  `growth_inbound`, `vendor_tracker`, `gmail_crm`, `recruiting_inbound`,
  `partnership_digest` (weekly Friday digest + archive low-relevance).
- Shared: `contact_lists`, `wiki_crm` (seed pages + append helpers); triage now
  reads investor/customer lists from wiki, tags Vendor/People/Investor.
- `gmail_manager` dispatches all Phase 3 agents at 8/12/4; onboarding seeds CRM
  wiki pages. Config: CRM wiki paths, Slack channels (#customer-support, #events,
  #growth, #partnerships), partnership digest schedule.

## 2026-06-18 — Gmail Phase 2 high-value writers (working tree)

- **Phase 2 agents**: `draft_reply` (MCP draft for simple `2. Reply`),
  `thread_watcher` (15m sent-folder delta → Decision/Ingest enrichment),
  `decision_propagate` (timeline wiki append), `gmail_ingest` (clear →
  `raw/entries`, ambiguous → queue), `ingest_queue_review` (Monday #ingest
  ping), `attachment_router` (contracts/decks/docs on wiki volume).
- Shared helpers: `mail_body`, `complexity`, `decision`, `operations_slack`;
  extended `gmail_rest` (sent history, attachments), `gmail_state`
  (sent_history_id), routing `find_by_thread` / `upsert_thread_tags`.
- `gmail_manager` dispatches Phase 2 specialists at 8/12/4; onboarding starts
  `thread_watcher` alongside triage + manager. Config: wiki paths, `#ingest`
  Slack channel, thread_watcher interval, ingest review schedule.

## 2026-06-18 — Gmail Phase 0 + Phase 1 (working tree)

- **Phase 0 plumbing**: `gmail_rest.py` (history, labels, modify via
  `GMAIL_OAUTH_ACCESS_TOKEN`), `gmail_state.py` (historyId cursor at
  `wiki/operations/gmail/_state.json`), `routing.py` (per-message JSON routing
  records), `labels.py` (taxonomy with attention visible / domain hidden),
  `classify.py` (deterministic Phase-1 heuristics), `scheduling.py`,
  `triage_apply.py`, expanded `config/operations.yaml` (schedules, label taxonomy,
  `gmail.modify` scope).
- **Phase 1 agents**: persistent `inbox_triage` (30m workdays, sole raw-mail
  reader), persistent `gmail_manager` (8/12/4 dispatch shell + 10pm sweep),
  ephemeral `inbox_sweep` (Reply-sent, FYI-opened, Newsletter/Receipt +1d,
  Meeting opened), one-time `gmail_onboarding` (labels + 30d backfill, starts
  triage + manager). Docs: `agent_list.md`, README, `.env.example` (`GMAIL_MAILBOX`,
  `gmail.modify`), `project_install.md`.

## 2026-06-18 — LLM provider abstraction + open-source GLM-5 option (working tree)

- **One knob switches the model behind every agent**: new `config/models.yaml`
  (`default_provider` + `providers` with `sdk: claude|openai` and a model id) and
  `COMPANY_BRAIN_LLM_PROVIDER` env, resolved by `config.resolve_llm_provider()` /
  `config.load_models_config()` (added `ProviderSpec`/`ModelsConfig`).
- New `company_brain/llm/` package: `provider.py` (`LLMProvider` +
  `resolve_provider()` reading per-provider `*_BASE_URL`/`*_API_KEY` env;
  `prompt_caching_1h_enabled()`), `claude.py` (`model_kwargs()`/`options_env()`
  for Claude-SDK agents), `openai_agents.py` (`make_model()`/`make_run_config()`
  binding OpenAI-Agents-SDK specialists to the provider — LitellmModel for
  anthropic, OpenAIChatCompletionsModel over AsyncOpenAI(base_url) for
  openai/glm). All SDK imports lazy.
- **SDK split is now provider-aware**: Claude Agent SDK = MCP-native/big-context
  agents (absorb, ramp_card_spend, budget_report, subscription_audit) — wired to
  splat `llm.claude.model_kwargs()/options_env()` into `ClaudeAgentOptions`.
  OpenAI Agents SDK = the provider-flexible path (can target a self-hosted/remote
  open-source GLM-5 OpenAI-compatible endpoint at no external-token cost).
- **GLM-5 (https://github.com/zai-org/GLM-5)** is the `glm` provider: cloud option
  = self-hosted on the GPU VM via **Ollama** (`ollama pull glm-5`, OpenAI-compatible
  at `:11434/v1` — easier than pulling raw weights; SGLang/vLLM remain alternatives),
  local option = remote-connect via `GLM_BASE_URL`. Locally installing GLM-5 is
  not realistic, so local installs default to a hosted provider key.
- **Prompt caching**: Claude Agent SDK caches tools+system+context automatically;
  `ENABLE_PROMPT_CACHING_1H` extends the write TTL to 1h for recurring agents
  whose intra-run calls are minutes apart. Self-hosted GLM uses the engine's
  prefix caching (SGLang RadixAttention / vLLM `--enable-prefix-caching`).
- Added `openai-agents[litellm]` dep; `.env.example` provider/GLM/OpenAI vars +
  caching knob; `sfile` allow_hosts (api.openai.com + GLM host placeholder);
  `doctor` now prints the active `LLM:` provider/model/endpoint and checks the
  right credential; updated README, project_install.md, agent-construction rule.

## 2026-06-17 — Operations department + Gmail connection layer (working tree)

- New **operations** department (`agents/operations/`): the catch-all for general
  platforms that don't fit a specific department (Gmail, Slack ops, Notion ops,
  Linear, ...). Only the **Gmail connection layer** is built so far — no
  specialists, manager, or onboarding agent yet (user will spec those next).
- `operations/gmail/gmail_client.py` mirrors `ramp_client`: builds the
  `mcp_servers` mapping for the Claude Agent SDK with two paths selected by
  `GMAIL_MCP_PROVIDER` — **official** (Google-hosted Gmail MCP, HTTP at
  `gmailmcp.googleapis.com/mcp/v1`, OAuth `gmail.readonly`+`gmail.compose`,
  default) and **composio** (hosted MCP, HTTP + `x-api-key`). Posture is
  **read + labels + draft compose, never send**: `GMAIL_SEND_FORBIDDEN=True`,
  `send_allowed()` stays false unless a human opts in via config + env.
- Added `config/operations.yaml` (provider/scopes/allow_send) + loader
  `operations/shared/config.py`; `.env.example` Gmail/Composio vars; Smolfile
  allow_hosts (gmailmcp/gmail/oauth2/accounts.googleapis + backend.composio.dev);
  a `doctor` Gmail check; README (Operations platform map + tree + config) and
  `project_install.md` (Gmail connect step, both paths); `agent_list.md` gained an
  Operations section noting connectivity-only (agents forthcoming).

## 2026-06-17 — Onboarding hands off to managers; FourSeven rename (working tree)

- **Onboarding -> manager handoff**: onboarding agents now start their platform's
  persistent manager(s) after backfill, then exit. `github_onboarding` starts
  `github_manager`; `finance_onboarding` starts both `monthly_expense` and
  `quarterly_calculation`. The managers' loops idle until their next correct
  scheduled time (they do not re-run the just-backfilled work). Gated by a
  `start_manager(s)=True` kwarg so tests can disable.
- Added `AgentRuntime.start(agent_cls, config, **kwargs)` — a non-blocking
  handoff for persistent agents (daemon thread locally; dedicated VM under the
  cloud runtime later), distinct from `run` (run-to-completion). Onboarding uses
  `get_runtime().start(...)`.
- Updated the `agent-onboarding` rule with the handoff step and the convention
  that the onboarding agent is listed **last** for its platform/department in
  `agent_list.md`. Moved `finance_onboarding` to the end of Finance and gave both
  onboarding agents their own "Onboarding" label row at the end.
- **Rename**: product English name is now **FourSeven** (seven archives of four
  repositories); README title is "FourSeven 四库七阁" with a history paragraph on
  the Siku Quanshu. The **repo/CLI name stays `company-brain`** (unchanged).

## 2026-06-17 — Split detailed agent docs into agent_list.md (working tree)

- Anticipating many more agents, moved the per-agent detail out of `README.md`
  into a new root file `agent_list.md`. README now only maps departments to the
  platforms they cover (high level) and links to `agent_list.md`.
- `agent_list.md` is **one HTML table per department** (header shown once).
  Within each, agents are grouped via full-width label rows: **managers** first,
  then **cross-platform agents**, then **platform specialists**. Each agent spans
  three stacked rows: a full-width name row, then the property row (State
  persistent/ephemeral, Trigger/Schedule, Info Source, Destination wiki MD path,
  Notion Page), then a full-width `colspan` description box. A `&nbsp;` spacer row
  follows each agent; an extra spacer precedes each group label for more
  separation. HTML is used because pure-markdown tables can't interleave the
  description box under one shared header; `<code>` wraps inline filenames/paths.
  Blank fields (not "N/A") where one doesn't apply (e.g. Mercury/Ramp specialists
  return data to managers and write no page).
- When adding/removing an agent, update `agent_list.md` (detail) and keep
  README's platform map in sync.

## 2026-06-16 — Access control via Notion teamspaces (working tree)

- Member read access is **delegated to Notion teamspaces** (Notion enforces who
  sees what; admin sets levels in Notion) rather than a company-brain identity/ACL
  system. The full Markdown wiki is admin-only; members read in Notion.
- `NotionConfig` gained `teamspaces` (key -> parent page id) and
  `section_teamspace` (section/prefix -> teamspace key | `admin_only`); helper
  `teamspace_for_section` (longest-prefix match). `NotionSync` routes a page to
  its teamspace parent and **skips mirroring `admin_only` sections** (MD-only).
- Updated the `access-control` rule, `config/notion.yaml` (teamspaces blocks),
  and `project_install.md`. Backward-compatible: no mapping = previous behavior.
- Still pending: wiki content versioning (validated writes + rollback). The
  earlier "company-brain-side identity + read-scope enforcement" approach is
  dropped in favor of Notion teamspaces.

## 2026-06-16 — Renamed AGENTS.md -> project_install.md (working tree)

- The agent-assisted install/onboarding runbook is now `project_install.md`
  (the `AGENTS.md` filename is reserved for other use later). Updated all
  references (README, cli `doctor`, agent-construction rule, self-references).

## 2026-06-16 — Update/append write modes + GitHub onboarding backfill (working tree)

- Added an explicit `WRITE_MODE` ("update" | "append") to every page-writing agent
  and a `mode=` argument to `write_wiki_page` (append = new section prepended under
  the heading, newest on top; update = overwrite).
  - Update: `open_pr`, `branch_monitor`, `subscription_audit`, `request_manual_accounting`, `monthly_expense` (per-month pages).
  - Append: `feature_update`, `product_features`, `quarterly_calculation`, `budget_report`, `asset_compile`.
- `request_manual_accounting` switched prepend -> update (page shows the current set).
- `github_onboarding` now backfills by **running the GitHub specialists** (open_pr,
  branch_monitor, feature_update, product_features) instead of seeding placeholder
  pages — mirroring `finance_onboarding`.
- `asset_compile` now publishes appended snapshots to a "Total Assets" page.
- `monthly_expense` kept per-month pages (reverted a brief rolling-page experiment).
- Docs: `wiki-data-flow` (update/append convention) and `agent-onboarding` (backfill
  via specialists) rules updated.

## 2026-06-16 — Branch monitor agent (working tree)

- Added `branch_monitor.py` GitHub specialist: maintains a "Branch Status" wiki page
  with, per repo, an environments table (deploy / ahead-behind prod / status) and a
  branches/PRs table (target env / ahead-behind / last activity / risk).
- Dispatched by the GitHub manager every morning; extended `gh.py` with read-only
  `default_branch`, `list_branches`, `compare_branches`, `list_deployments`.

## 2026-06-16 — Self-maintaining foundation + open-source onboarding (`265de2f`)

- Self-maintaining loop in `BaseAgent.execute()`: `should_run` cost gate -> run ->
  `verify` triage (ok/rework/noise) with bounded iteration.
- New: `agents/result.py`, `agents/gates.py` (state store + change/dedup), `notify.py`
  (Signal/Notifier: detect everything, notify selectively), `runtime/sandbox.py`
  (optional smolvm sandboxed verification).
- Open-source onboarding: `config.resolve_mode()` (local vs cloud), `company-brain
  doctor` command, root `AGENTS.md` setup runbook, README slimmed to human-facing.
- Mercury/Ramp documented read-only at client + rule + README.
- Cleanup: removed `scripts/setup_wiki.py` and `wiki-gen-skill.md`.

## 2026-06-16 — Markdown wiki source of truth + Notion mirror + runtime (`9de72b2`)

- The wiki is now a directory of Markdown files (source of truth); Notion is a synced
  mirror. New `WikiStore`/`MarkdownDoc`, `NotionSync`, `wiki/absorb.py` LLM writer loop,
  `wiki/indexer.py` (`_index.md` + `_backlinks.json`), and `wiki/publish.py` helper.
- Ingestion writes `raw/entries/*.md`; absorb log moved to `wiki/_absorb_log.json`.
- Added `runtime/` (AgentRuntime/AgentDeployer: local now, smol cloud later) and a
  `Smolfile`; agents write MD-first then sync.
- Renamed `manual_request` -> `request_manual_accounting`.

## 2026-06-15 — Finance department + department reorganization (`a8434a8`)

- Reorganized agents into department -> platform; GitHub moved under `engineering/`
  with a `github_manager`.
- Added the finance department: Mercury (read-only CLI) and Ramp (read-only MCP)
  platforms, specialists (asset_compile, bank_transaction, mercury_card_spend,
  ramp_card_spend), persistent managers (monthly_expense, quarterly_calculation),
  cross-platform agents (budget_report, subscription_audit, request_manual_accounting),
  and finance_onboarding.
- Added agent rules: construction (SDK selection, integrations), organization,
  scheduling, onboarding, lifecycle.

## 2026-06-15 — Hierarchical agent display in README (`e7884a1`)

- Showed each manager above a table of its specialist sub-agents; codified the
  display convention in the organization rule.

## 2026-06-15 — Initial scaffold, agent rules, GitHub agents (`a034341`)

- Renamed the internal project to 四库七阁 (repo dir unchanged).
- Established the agent-construction rule set (Anthropic Claude Agent SDK vs OpenAI
  Agents SDK selection; Slack SDK; Notion discover-or-create; GitHub CLI read-only).
- Created the first GitHub agents (open_pr, feature_update, product_features,
  github_onboarding) under a GitHub manager.
- Gitignored personal `notepad.md`.

## 2026-06-15 — Initial commit (`f4168bb`)

- Base project: README, LICENSE, config (wiki.yaml/notion.yaml), and the
  `company_brain` package skeleton (cli, config, notion, wiki, ingestion, output).
