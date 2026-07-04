# Repo Memory Log

**Purpose: read this first.** This file is the fast path to development context so
an AI coding agent does not have to read the entire project to understand how it
got here. Skim the recent entries to learn the current architecture and recent
decisions, then dive into specific files only as needed (saves tokens/time).

A running log of significant actions, decisions, and changes. Newest entries on
top. Each entry: date, summary, key changes, and the commit it landed in (or
"working tree" if not yet committed). After meaningful work, prepend a new entry.

---

## 2026-07-03 — Generalize cloud VM runtime (provider-agnostic)

- **Runtime:** `CloudRuntime` / `CloudDeployer` / `VMSandbox` are now generic
  abstractions not tied to any specific cloud VM provider. `COMPANY_BRAIN_RUNTIME=local|cloud`;
  `COMPANY_BRAIN_SANDBOX=vm`.
- **VM spec:** `vmspec.toml` (generic TOML VM specification — image, network
  allow-list, volumes). Provider-agnostic — works with any cloud VM service that
  offers a CLI, persistent machines with no idle billing, and cron-based wake.
- **Cloud direction:** managers live in VMs woken by cron where the provider
  supports it; persistent manager loops otherwise. Agents can spin up other VMs
  via the provider CLI.
- **Doctor:** `vmspec_allow_hosts` check validates agent API hosts against `vmspec.toml`.
- **Docs/rules:** all references updated (README, project_install, agent-runtime,
  agent-eval, agent-construction, platform-boundary, solo-maintainer, development,
  no-sus skill, .env.example, .gitignore, wiki/store docstring).

## 2026-07-02 — LLM budget reconcile + CLI (vendor fallback)

- **`llm/reconcile.py`** — Mercury card vendor totals vs tracked usage; doctor warn on drift.
- **`company-brain models budget`** — status, run caps, `--reconcile` flag.
- **Doctor `llm`** — per-agent run cap summary; reconcile check when budget enabled.
- **Spot checks** — wrapped in `run_budget_scope`.

## 2026-07-02 — LLM budget Layer B (per-run cap enforcement)

- **`llm/run_budget.py`** — `run_budget_scope()` context; caps on USD, steps, tool calls.
- **`BaseAgent.execute()`** — wraps run/verify loop; blocks before each iteration.
- **SDK hooks** — `begin_llm_step()` + tool-call tracking on Claude/OpenAI paths; absorb scoped.
- **`resolve_llm_agent_key()`** — maps `finance_budget_report` → `budget_report` for limits.

## 2026-07-02 — LLM budget Layer A (categories, caps defaults, usage tracking)

- **`config/models.yaml`** — `spend_categories` (runtime/builder), tier+agent `run_limits`,
  `model_rates`, `token_budget.guidance_usd` ($200 runtime / $50 builder soft targets;
  $250 hard pool).
- **`llm/budget.py`** — `record_usage()`, `resolve_spend_category()`, `resolve_run_limits()`,
  `estimate_usd()`, category breakdown in `budget_status()`, near-limit alert to `#wiki-admin`.
- **`llm/tracking.py`** — `iter_claude_query`, `run_openai_sync`, SDK usage hooks wired into
  absorb, draft_reply, budget_report, subscription_audit, card_spend, spot_check.
- **Layer B shipped:** enforce `run_limits` in `BaseAgent.execute()` + LLM SDK hooks.

## 2026-07-02 — CRM build session 8 (handbook + cleanup)

- **`docs/agents/operations.md`** — CRM section rewrite (entity layout, mermaid,
  `inbound_crm`, promotion/retention); removed retired agent docs.
- **Deleted** deprecated `growth_inbound.py`, `recruiting_inbound.py`; plan file removed.
- **`docs/tabled.md`** — shipped partnership_inbound row removed; hiring log → inbound_crm.

## 2026-07-02 — CRM build session 7 (Notion DB sync)

- **`crm/notion_sync.py`** — contact + inbound pages → `crm_databases` Notion rows;
  discover-or-create by title; `notion_page_id` + `synced_hash` in frontmatter.
- **`write_wiki_page`** — auto-syncs CRM entity paths; **`company-brain crm sync-notion`** CLI.
- **`NotionConfig.crm_databases`** + number/date property patches in notion `db.py`.
- **Tests:** `test_crm_notion_sync.py` (4 cases). 162 passing.

## 2026-07-02 — CRM build session 6 (vendor path → finance)

- **`vendor_tracker`** — writes `finance/vendor/<slug>.md` (was `operations/gmail/vendor/`);
  `section="finance"`; config via `config/finance.yaml` → `wiki.vendor_dir`.
- **`finance/shared/config.py`** — `vendor_dir()` helper; removed from operations config.
- **`name_migrate.py`** — `operations/gmail/vendor/` → `finance/vendor/`.
- **Docs:** `docs/agents/finance.md`, `docs/agents/operations.md` destination updated.
- **Tests:** `test_vendor_tracker.py` (2 cases). 158 passing.

## 2026-07-02 — CRM build session 5 (inbox retention)

- **`crm/retention.py`** — 7 calendar-day rule from `triaged_at`; requires CRM inbound
  tag + `inbound_crm` handled (legacy keys accepted).
- **`inbox_sweep`** — archives CRM cold inbound when retention due.
- **Removed** `partnership_digest.py`, schedule/config, `partnership_digest_notifier`.
- **Tests:** `test_crm_retention.py` (5 cases). 156 passing.

## 2026-07-02 — CRM build session 4 (two-way promotion)

- **`crm/promotion.py`** — two-way thread detection, dismissive outbound filter,
  auto-promote counterparty to `connection`, append `crm/promotion-log.md`, mark
  inbound pages `promoted` / `archived`, routing record `crm_promoted_to`.
- **`thread_watcher`** — calls promotion after every sent message (including ack).
- Skips `customer` / `investor` segments; requires `crm.default_connection_employee`.
- **Tests:** `test_crm_promotion.py` (4 cases). 151 passing.

## 2026-07-02 — CRM build session 3 (all inbound types + contact writers)

- **`inbound_crm`** — all 6 cold inbound tags → `crm/inbound/{type}/`; Slack still
  press + events only.
- **Retired from dispatch:** `partnership_digest`, `recruiting_inbound`, `growth_inbound`
  (files deprecated); routing handled keys migrate via `name_migrate`.
- **Contact entity writers:** `investor_tracker` (confirmed Investor only),
  `connection` (People/Warm intro), `customer_crm` → `crm/contact/{slug}` via
  `record_interaction_on_contact`.
- **Config:** `crm.default_connection_employee` for new connections.
- **Tests:** partnership inbound, connection contact entity. 147 passing.

## 2026-07-02 — CRM build session 2 (inbound_crm + inbound_score)

- **`inbound_score.py`** — shared $0 scorer (reputable/press/event domains, keywords,
  free-email penalty, known contact boost); Slack threshold for press + events only.
- **`inbound_crm.py`** — replaces `growth_inbound` in dispatch; writes
  `crm/inbound/{press-podcast,event-invitation}/` pages; score-gated `#growth` alerts.
- **`crm/inbound.py`** — triage tag map, inbound page writer, contact dual-write.
- **Config:** `crm.press_domains`, `crm.event_domains`; profiles/manager wired to
  `inbound_crm`. `growth_inbound.py` deprecated (file retained).
- **Tests:** `test_inbound_score.py`, `test_inbound_crm.py`. 145 passing.

## 2026-07-02 — CRM build session 1 (registry + contact schema)

- **Package:** `src/company_brain/crm/` — `config`, `schema`, `slug`, `registry`, `contacts`, `seeds`.
- **CLI:** `company-brain crm seed`, `company-brain crm rebuild-registry`.
- **Config:** `config/operations.yaml` → `crm:` block; customer/investor indexes at
  `crm/customer/_index.md`, `crm/investor/_index.md`; `config/notion.yaml` → `crm: company`
  teamspace + `crm_databases` stubs.
- **Classify:** removed `"partnership opportunity"` from Sales Outreach hints.
- **Migration:** `name_migrate.py` maps legacy investor/customer paths → `crm/`.
- **Tests:** `tests/test_crm_registry.py` (6 tests); classify partnership case. 139 passing.

## 2026-07-02 — CRM redesign agreed (entity-per-person + unified inbound)

Design locked in `docs/plans/crm-redesign.md` (build not started):

- **Entity model:** `crm/contact/{slug}.md` with `segment` (customer | investor | connection);
  `crm_registry` (`crm/_registry.json`) for email/domain dedup; Option B inbound sections on
  contact when known, `crm/inbound/unmatched/` otherwise.
- **Inbound types (6 Notion DBs):** press-podcast, event-invitation, partnership,
  founder-networking, investor-interest, candidate — shared `inbound_score.py`; v1 Slack
  alerts (`#growth` only) for press + events when score ≥ threshold.
- **Promotion:** two-way exchange → connection (exclude dismissive replies); customer/investor
  via contract signed or index edit; `crm/promotion-log.md` audit.
- **Retention:** 7 calendar days in inbox via `inbox_sweep`; `partnership_digest` archive
  behavior retired.
- **Out of CRM:** vendor listing → `finance/vendor/`; employees stay in `people/`.
- **Classify fix:** remove `"partnership opportunity"` from Sales Outreach hints.

## 2026-07-02 — Work-ahead product posture (README + scheduling rule)

- **Design principle:** agents finish agent-suitable work *before* human attention is
  needed; not everything automated — humans contribute where judgment/actuation matters.
- **README Expectations** rewritten; **agent-scheduling.mdc** adds work-ahead posture +
  rule 6 (deadline − duration − buffer). Distinct from no-nudge out-of-scope features.

## 2026-07-02 — Ruff format adoption (5d3f017)

- **`ruff format .`** on 105 files; pre-commit `ruff-format` + CI `ruff format --check`.
- **`.git-blame-ignore-revs`** points at the format commit; optional
  `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

## 2026-07-02 — Post-feature hygiene checklist (working tree)

- **`docs/development.md`:** added "Post-feature hygiene checklist" — four passes
  (cleanliness / coherence / dead code / safety+deps) with concrete commands, plus an
  optional table (mypy, coverage, codespell, extended ruff). Run after big builds.
- **`.pre-commit-config.yaml`:** added standard `pre-commit-hooks` (trailing-whitespace,
  end-of-file-fixer, check-merge-conflict, check-added-large-files, check-yaml,
  detect-private-key). `ruff-format` deliberately **omitted** — adopting it is a one-time
  ~105-file reformat, a separate decision.
- **`solo-maintainer.mdc` §7:** points at the checklist and enumerates the passes.
- **Ran the plan project-wide:** ruff/tests/doctor-code green (naming 99 = tabled Slack
  rename only); secret scan clean (2 test-fixture false positives); `pip-audit` → bumped
  direct-dep floors `requests>=2.33.0`, `python-dotenv>=1.2.2` (CVE patches). Flagged (not
  fixed, pre-existing): `mercury_client.py` uses `print()` for CLI-fallback diagnostics →
  should move to `self.logger` in a future finance pass.
- Session dead-code trim: removed `llm/eval.py` (zero-logic), unused
  `operations_slack.wiki_admin_notifier` + `operations.yaml` key, `budget.record_usage`
  / `maybe_alert_budget` (unwired), `ModelHealthReport.all_ok`; gitignored
  `config/doctor-history.json`; added `llm` doctor row to development.md.

## 2026-07-02 — LLM tiers tabled follow-ups (working tree)

- **Tabled:** overall agent scheduling revisit → Slack platform build (`docs/tabled.md`).
- **Tabled:** batch absorb by urgency, token budget usage tracking (API tokens primary;
  card_spend vendor bills fallback), LLM eval harness (concept in `docs/tabled.md` only).
- Restored `config/models.yaml` `providers` after test artifact drift.

## 2026-07-02 — LLM model tiers + health doctor (working tree)

- **`config/models.yaml`:** `mode` (performance | balanced), cross-provider `tiers`,
  per-agent tier map, `agent_providers` (strategy B: Anthropic MCP agents + OpenAI
  `budget_report`), `fallback_chains`, doctor `overrides`, optional `token_budget`.
- **`company_brain.llm.tiers`:** `resolve_agent_model()` / `resolve_agent_provider()`;
  onboarding via `company-brain models configure`; doctor `llm` subcommand pings
  models, auto-falls back within chain, persists override, alerts `#wiki-admin`.
- **Work-ahead scheduling:** `agents/scheduling/work_ahead.py`; Linear stale audit
  runs in a Sunday window (12h buffer) so Monday 9am standup wiki is ready.
- **Absorb:** anti-cram / length targets in system prompt (readable pages, split topics).
- **`project_install.md`:** LLM onboarding step documents mode choice + doctor health.

## 2026-06-30 — Agent filename rename pass (working tree)

- Drop redundant platform prefix inside platform folders:
  `mercury/card_spend.py`, `ramp/card_spend.py`, `granola/{ingest,meeting_watch,miss_check,task}.py`,
  `notion/{db,platform_config,task_config,task_scanner,task_sync}.py`.
- Class names shortened where safe (`IngestAgent`, `TaskScannerAgent`, …); finance keeps
  `MercuryCardSpendAgent` / `RampCardSpendAgent` (same stem in different folders).
- `migrate-names --gate-keys` renames `config/state.json` handled keys (`granola_ingest` → `ingest`, etc.).

## 2026-06-30 — Governance refinements (working tree)

- **Design-before-build:** solo-maintainer rule — list concerns one-by-one, 2–3 rounds,
  `docs/plans/` deleted after ship; tabled reminders at plan start only.
- **`company-brain doctor naming`:** legacy path drift, WIKI_PATH slugs, agent suffix/prefix.
- **Handbooks:** steady-state mermaid only (no onboarding nodes); operations deferred → `tabled.md`.
- **Tabled:** platform connection order + quarterly doc pass under 4r7a onboarding.

## 2026-06-30 — Solo maintainer governance (working tree)

- **Rule:** `.cursor/rules/solo-maintainer.mdc` — flag rule drift, read `docs/tabled.md`
  when building platforms, doc update obligations, naming consistency, pre-ship checklist.
- **Docs:** `docs/tabled.md` (canonical deferrals from notepad + handbooks),
  `docs/doc-style.md` (handbook/memory/README layers and templates).
- Links added in `docs/development.md`, `docs/agents/README.md`.

## 2026-06-30 — Naming convention migration (working tree)

- Added `.cursor/rules/naming.mdc` (three-layer: agent snake_case → wiki kebab slug → article/Notion title).
- Renamed agents: `content_catalog_agent` → `content_catalog`; `gmail_ingest` → `ingest`; `gmail_customer_support` → `customer_support`; `gmail_crm` → `connection`.
- Stripped `gmail_` prefix from specialist `name` / dispatch keys (kept `gmail_manager`, `gmail_onboarding`).
- Wiki paths: singular slugs (`open-pr`, `expense-report/`, `subscription`, `operations/decisions/timeline.md`, `admin/content-catalog.md`, `admin/import-review/`, `admin/mount-review/`, `work-log/`).
- Titles aligned (e.g. Stale Audit, Jan 2026 Expenses, Mount Review — {source}).
- **`company-brain migrate-names`** CLI + `wiki/name_migrate.py` for bulk renames on existing trees; import/promote pipelines call `migrate_rel_path()` / `migrate_title()`. 122 tests pass.

---

- **Phases A–D shipped:** `wiki/external_paths.py`, `external_sources_config.py`,
  `config/external_sources.yaml`, `external_wiki` block in `operations.yaml`,
  mount pipeline (`external_wiki_import`, `external_mount_review`, `external_promote`),
  `detect_external_duplicates`, admin catalog (`content_catalog.py`, `content_catalog`),
  `company-brain catalog` CLI, `section_teamspace: admin → admin`.
- Employee import reviews migrated to `admin/import-review/` (from `engineering/admin/`).
- `write_wiki_page` accepts `sync_label` + `extra_frontmatter` for provenance stamping.
- Docs: `docs/agents/external_wiki.md`, README, project_install, access-control rule.
- 115 tests pass.

## 2026-06-29 — Employee wiki cleanliness audit (working tree)

- Removed dead duplicate `member_quarantine_path` (employee_paths) — `member_quarantine_rel`
  in import_promote is the single home. Consolidated `_target_members` → public
  `event_target_members` in `work_events.py` (shared by store + materializer).
- Fixed resource leak (`with open(...)`), inline `import json`, and indirect `WikiStore`
  import in the import pipeline.
- Added `docs/agents/employee_wiki.md` handbook + index rows (docs/agents/README, agent_list);
  agents doctor now covers all employee_wiki files. Remaining handbook/dispatch warnings are
  pre-existing (Linear config helpers + finance managers). 110 tests pass.
- **Full-project coherence sweep:** README (architecture diagram + Employee Wiki section +
  project-structure tree + config list), `project_install.md` (member onboarding/import step),
  `.env.example` (`COMPANY_BRAIN_EMPLOYEE_WIKI_DIR`), and `.cursor/rules/access-control.mdc`
  (employee wiki `sync:` labels + `members.yaml` scopes) now all reference the employee wiki.
- **Pre-existing doctor warnings cleared (out-of-scope cleanup):**
  - `agent_handbook_coverage` — refined `doctor/agents.py` so handbook coverage targets only
    files defining a `BaseAgent` subclass (config/standards/propagation helpers like
    `notion_config`, `slack_config`, `task_propagate`, `task_standards` are not agents, matching
    the existing `_client`/`_rest` exclusions and the platform-helper placement rule).
  - `manager_runtime_dispatch` — finance managers (`monthly_expense`, `quarterly_calculation`,
    `subscription_audit`) now dispatch transaction specialists via `get_runtime().run()` instead
    of inline `.execute()`, per agent-runtime.mdc.
  - Doctors: agents/wiki/ops = 100; connect warnings are local-only missing tokens.

## 2026-06-29 — Employee wiki Phase E (working tree)

- **Platform materializers:** Granola meeting ingest, Gmail inbox/team-on-it, Slack action items
  → `work_events.jsonl` via `record_*_work_event()` hooks; materializer handles all sources.
- **Contributors:** Granola attendee emails resolve to contributor work_log lines.
- **`_index.md` refresh:** materializer updates ## This quarter from recent work_log bullets.
- **`find_by_slack_user_id`** in members_config; watcher passes Slack user id to action items.
- Tests: `tests/test_employee_wiki_materializers.py`.

## 2026-06-29 — Employee wiki Phases C–D (ea16a16)

- **Phase C — Notion sync labels:** `notion/sync_routing.py`, `member_teamspace.py`,
  `wiki/employee_notion_sync.py`; `sync:` frontmatter on employee pages; onboarding syncs index.
- **Phase D — Zip import:** `import_scan.py`, `duplicate_detect.py`, `import_promote.py`;
  agents `employee_wiki_import`, `import_review`; first-import admin gate via `StateStore`;
  duplicate tiers 1–4 with link stubs on approve.
- Config: `employee_wiki.import` block in `operations.yaml`.
- Tests: `test_employee_notion_sync.py`, `test_employee_wiki_import.py` (105 total passing).

## 2026-06-26 — Employee wiki Phases A–B (working tree)

- **Foundation:** `resolve_employee_wiki_dir()`, `config/members.yaml`, `members_config.py`,
  `LocalEmployeeWikiStore`, `write_employee_wiki_page`, `ensure_people_stub`, `ensure_member_wiki`.
- **Ledger:** `wiki/work_events.py` + `record_linear_work_event()`.
- **Agents:** `agents/employee_wiki/` — `employee_wiki_manager`, `work_event_materializer`.
- **Config:** `employee_wiki.poll_interval_minutes` in `operations.yaml`; gitignore
  `/employee_wiki/`, `/config/work_events.jsonl`; vmspec sibling mount.
- Tests: `tests/test_employee_wiki.py` (9 cases). Platform → ledger hook not wired yet.

## 2026-06-26 — Employee wiki architecture plan drafted (working tree)

- **`docs/plans/employee-wiki.md`**: full build plan (Phases A–I) for
  `employee_wiki/{member}/` substrate — ledger + materializers, Notion `sync:` labels
  (incl. admin_only → admin teamspace), zip import + duplicate detection (#6), manager
  citation-only query, offboarding, deferred Notion↔MD pull (Phase I).
- Converges with future project onboarding + company wiki generation; MD-first scope
  larger than any single platform integration.

## 2026-06-26 — Remove Granola 18:00 EOD backstop (working tree)

- Granola pipeline is now purely calendar-driven: post-meeting ingest + weekly
  `miss_check` safety net. Removed `_maybe_eod_backstop` from
  `meeting_watch` (+ its `eod_backstop` return field and `is_workday` import).
- Removed dead `_loop` / `_should_run_today` from `ingest` and the now-unused
  `cfg.ingest_time()` helper + `schedule.ingest_time` config key.
- Updated docs (README, operations handbook diagrams/tables, project_install) and
  `test_task` to drop the backstop. Also refreshed README operations platform
  map (Slack + Notion task platform) during the prior coherence pass.

## 2026-06-26 — Linear task platform Phase 5 + Notion task DBs (working tree)

- **`operations/notion/`**: `task_config`, `notion_db`, `task_scanner`, `task_sync`.
- **`config/notion.yaml`**: `task_databases` + `task_routing`; `notion_platform` poll in `operations.yaml`.
- **`task_bindings`**: `find_by_notion_page`, `attach_notion_platform`; wiki index/detail show Notion links.
- **`task_propagate`**: Linear status → Notion fan-out; **`linear_completed`** dispatches `task_sync`.
- **`task`**: creates Notion row on ingest when `meeting_action` fan-out includes notion.
- **`linear_onboarding`**: starts `task_scanner` when task DBs configured.
- Doctor allowlist for Notion task platform modules in `operations/notion/`.
- Tests: `tests/test_notion_task_platform.py`.

## 2026-06-26 — Linear task platform Phase 4 + Slack (working tree)

- **`operations/slack/`**: `slack_client`, `slack_thread_watcher`, `slack_action_items`.
- **`linear_completed/slack_thread_respond`**: Linear Done → thread reply.
- **`task_bindings.create_slack_binding`**; wired in `linear_completed` dispatcher.
- Config: `slack_platform` in `operations.yaml`; doctor allowlist for `slack_client`.
- Tests: `tests/test_slack_action_items.py`.

## 2026-06-26 — Linear task platform Phase 3 + Granola pipeline (working tree)

- **`meeting_watch`**, **`task`**, **`miss_check`**;
  refactored **`ingest`** as dispatched specialist (+ 18:00 backstop via watch).
- **`granola_onboarding`** starts `meeting_watch` instead of ingest loop.
- **`task_bindings.create_granola_binding`** for meeting-sourced tasks.
- Tests: `tests/test_task.py`; updated `test_granola_onboarding.py`.

## 2026-06-26 — Linear task platform Phase 2 (working tree)

- **`structure_organization`**, **`linear_onboarding`**, **`stale_audit`**,
  **`request_manual_management`** under `engineering/linear/`.
- **`linear_manager`**: weekly Monday stale audit dispatch.
- **`linear_client`**: `list_open_issues`, `list_workflow_states`, `resolve_state_id`.
- Config: `linear.manual`, `linear.slack_channel`, `linear.stale_audit.stale_days`.
- Tests: `tests/test_linear_phase2.py`, `tests/test_linear_manual.py`.

## 2026-06-26 — Linear task platform Phase 0 + 1 (working tree)

- **`engineering/linear/`**: `task_bindings`, `task_propagate`, `task_standards`,
  `linear_manager` (30min poll), `linear_completed/` + `archive_gmail`, `slot_check`.
- **`config/task_bindings.json`**, extended `config/engineering.yaml` (`task_classes`,
  poll interval).
- **`inbox_task`** / **`team_on_it`**: create wiki binding + `task_id` on Linear issue create.
- Tests: `tests/test_task_bindings.py`, `test_task_propagate.py`, `test_task_standards.py`.
- Build plan: `docs/plans/linear-task-platform.md` (Phase 2 next: onboarding, stale audit).

## 2026-06-25 — Revert Excalidraw diagrams (working tree)

- Removed `docs/diagrams/`, excalidraw skill, PNG renders, playwright render tooling.
- Restored **Mermaid** flowcharts in each `docs/agents/` handbook file.

## 2026-06-24 — Doctor registry + no-sus protocol (working tree)

- **`src/company_brain/doctor/`**: scored doctors — `connect`, `agents`, `wiki`,
  `ops`; CLI group `company-brain doctor [code|all|…]`; history in
  `config/doctor-history.json`.
- **`.cursor/rules/platform-boundary.mdc`** + **`.cursor/skills/no-sus-agent-doctor/`**
  for pre-ship audits (Kevin Liu doctor pattern).
- **CI**: `.github/workflows/ci.yml` — ruff, pytest, `doctor code --min-score 85`.
- **`.pre-commit-config.yaml`** — ruff + pytest.
- **`docs/development.md`** — fix loop, doctor registry, no-sus triggers.
- **README Expectations** — creator disclaimer on agent limits and user accountability
  (from `notepad.md`).

## 2026-06-23 — Receipt forwarding for Ramp inbox (working tree)

- **`receipt_forward.py`**: copies missing subscription receipts from sibling
  company-domain mailboxes into `receipt_router.destination_mailbox` via Gmail
  insert (no send). Policy: `company_domain` + `forward_enabled` in config.
- **`receipt_router`** refocused: route mail for Ramp auto-attach, not transaction
  reconciliation.

## 2026-06-23 — Google Calendar + meeting scheduler (working tree)

- Added **`operations/gcal/`**: `gcal_client.py` (official Calendar MCP), `gcal_rest.py`
  (REST), `calendar_availability.py`, `book_meeting.py`, optional `daily_agenda.py`
  (Slack DM, off by default).
- **`ext_meeting_scheduler.py`** in Gmail: proposes times via draft or books confirmed
  meetings; dispatched by `gmail_manager`. `doctor` + `vmspec.toml` updated.

## 2026-06-23 — Granola onboarding agent (working tree)

- Added **`granola_onboarding.py`**: runs `ingest` once per day across a
  configurable backfill window (default 30 days), then `get_runtime().start(IngestAgent)`.
- `granola.onboarding.backfill_days` in `config/operations.yaml`; docs updated.

## 2026-06-23 — Granola meeting-notes ingest (working tree)

- Added **`operations/granola/`** platform: `granola_client.py` (REST read-only against
  `public-api.granola.ai`), `ingest.py` (persistent daily 6pm ingest, no manager).
- Supports **business** (per-member API keys + roster) and **enterprise** (single public-notes
  key) modes via `config/operations.yaml` → `granola` + `GRANOLA_*` env vars.
- Writes raw entries for absorb plus a daily compiled wiki page at
  `operations/granola/meeting/{date}.md`. `doctor` checks Granola; `vmspec.toml` allow_hosts updated.

## 2026-06-21 — Linear connection under engineering (working tree)

- Moved Linear from `operations/linear/` to **`engineering/linear/linear_client.py`**
  (GraphQL + official MCP + optional community CLI). Added read helpers
  (`viewer`, `list_teams`, `list_issues`, `get_issue`) and `check_connection()` for
  `doctor`. New `config/engineering.yaml` + `engineering/shared/` config loaders.
- Operations Gmail agents (`inbox_task`, `team_on_it`) import the engineering client;
  misplaced gmail helpers moved from `operations/shared/linear_config.py` into
  `gmail_config.py`. No new Linear agents yet.

## 2026-06-21 — Consistency pass + notification gating enforced (working tree)

- **Lint clean**: `ruff check .` now passes (was 61 errors). Removed dead code
  (`gh.list_recent_commits` rewrite, `asset_compile` unused `latest`), unused
  imports, unsorted imports, and wrapped 50 over-length lines (string content
  preserved via implicit concatenation).
- **One YAML loader**: added `config.load_yaml_config(name)` / `save_yaml_config`;
  `load_finance_config` / `load_operations_config` are now thin wrappers. New YAML
  configs should read through this helper.
- **Removed `customer_crm_path()` alias** (callers use `customers_wiki_path()`).
- **"Detect everything, notify selectively" is now mandatory for every human-facing
  notification.** `operations_slack` exposes only `Notifier`-returning builders
  (`ingest_notifier()`, `customer_support_notifier()`, `events_notifier()`,
  `growth_notifier()`, `partnership_digest_notifier()`, `channel_notifier()`); the
  Slack SDK is just transport. Converted `team_on_it`, `growth_inbound`,
  `partnership_digest`, `ingest_queue_review`, `customer_support` to emit
  `Signal`s. `request_manual_accounting` no longer calls Slack directly (routed via
  `from_finance_config().emit(Signal(...))`); removed the now-dead
  `SlackNotifier.post_with_link`. Strengthened the `agent-eval` rule; updated README,
  operations/finance handbooks.
- **notepad.md de-linked**: nothing in the repo links to the gitignored scratchpad;
  removed the reference from `operations.md` and the gmail reference block from
  `notepad.md` (its content already lives in the operations handbook).

## 2026-06-18 — Agent handbook split (`docs/agents/`) (working tree)

- Replaced monolithic `agent_list.md` HTML tables with **department handbooks**:
  `docs/agents/engineering.md`, `finance.md`, `operations.md` (+ README index).
- Operations handbook includes Gmail architecture, routing records, **label taxonomy**,
  service profiles, schedules, and per-agent runbooks.
- Root `agent_list.md` is now a short index; README and `agent-onboarding` rule updated.

## 2026-06-18 — Gmail Phase 5: service profiles + classifier eval (working tree)

- **Profiles** (`shared/profiles.py`, `config/operations.yaml`): `executive_assistant`
  (full EA for founders), `employee` (flat cold inbound/newsletters, no Investor/Warm
  intro, reduced agents), `service_account` (1–3 attention, per-purpose overrides via
  `mailbox_profiles`). `gmail_manager` for all accounts; triage + dispatch respect profile.
- **Cost gate** on `draft_reply` (`is_simple_reply_message` + `changed_since` / `mark_handled`).
- **Classifier eval**: `tests/fixtures/gmail_classify_cases.yaml` + expanded unit tests.
- Docs: README, `agent_list.md`, `project_install.md`, `GMAIL_PROFILE` in `.env.example`.

## 2026-06-18 — Gmail executive assistant Phases 0–4 + Linear (`e1a0635`)

Full CEO inbox agent fleet under `operations/` (54 files, 15 tests):

- **Phase 0 plumbing**: `gmail_rest`, `gmail_state`, `labels`, `routing`, `classify`,
  `scheduling`, `triage_apply`, expanded `config/operations.yaml`.
- **Phase 1 core loop**: persistent `inbox_triage` + `thread_watcher`, `gmail_manager`,
  `inbox_sweep`, `gmail_onboarding`.
- **Phase 2 writers**: `draft_reply`, `decision_propagate`, `ingest`,
  `ingest_queue_review`, `attachment_router`.
- **Phase 3 CRM/notifications**: investor/customer/growth/vendor/people/recruiting CRM
  agents, `partnership_digest`, Slack channels, wiki CRM seed pages.
- **Phase 4 cross-platform**: `inbox_task` + `team_on_it` (Linear), `duplicate_across_mailboxes`,
  `receipt_router`; **Linear** via GraphQL + MCP + optional CLI (`linear_client.py`).

`doctor` checks Gmail + Linear; `vmspec.toml` allow_hosts updated; docs in README,
`agent_list.md`, `project_install.md`.

## 2026-06-18 — LLM provider abstraction + open-source GLM-5 option (`21242f4`)

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
  agents (absorb, card_spend, budget_report, subscription_audit) — wired to
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
  caching knob; `vmspec.toml` allow_hosts (api.openai.com + GLM host placeholder);
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
  `operations/shared/config.py`; `.env.example` Gmail/Composio vars; `vmspec.toml`
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
  (optional VM sandboxed verification).
- Open-source onboarding: `config.resolve_mode()` (local vs cloud), `company-brain
  doctor` command, root `AGENTS.md` setup runbook, README slimmed to human-facing.
- Mercury/Ramp documented read-only at client + rule + README.
- Cleanup: removed `scripts/setup_wiki.py` and `wiki-gen-skill.md`.

## 2026-06-16 — Markdown wiki source of truth + Notion mirror + runtime (`9de72b2`)

- The wiki is now a directory of Markdown files (source of truth); Notion is a synced
  mirror. New `WikiStore`/`MarkdownDoc`, `NotionSync`, `wiki/absorb.py` LLM writer loop,
  `wiki/indexer.py` (`_index.md` + `_backlinks.json`), and `wiki/publish.py` helper.
- Ingestion writes `raw/entries/*.md`; absorb log moved to `wiki/_absorb_log.json`.
- Added `runtime/` (AgentRuntime/AgentDeployer: local now, cloud VM later) and
  `vmspec.toml`; agents write MD-first then sync.
- Renamed `manual_request` -> `request_manual_accounting`.

## 2026-06-15 — Finance department + department reorganization (`a8434a8`)

- Reorganized agents into department -> platform; GitHub moved under `engineering/`
  with a `github_manager`.
- Added the finance department: Mercury (read-only CLI) and Ramp (read-only MCP)
  platforms, specialists (asset_compile, bank_transaction, card_spend,
  card_spend), persistent managers (monthly_expense, quarterly_calculation),
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
