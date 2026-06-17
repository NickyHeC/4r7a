# project_install.md — Onboarding runbook for the assisting AI coding agent

You are an AI coding agent helping a human set up **company-brain**: a company
wiki "brain" (Markdown source of truth, mirrored to Notion) operated by a fleet
of specialist agents across their platforms. Follow this runbook step by step.

> **Read `memory.md` first.** It is a reverse-chronological development log that
> gives you the current architecture and recent decisions without reading the
> whole codebase — start there for context, then open specific files as needed.
> After making meaningful changes, prepend a new entry to it.

## Operating principles (read first)

- **The installer is the company admin.** They have access to all company
  accounts/providers and own access scoping. The full Markdown wiki is
  admin-only; **members read through Notion teamspaces** (the admin sets each
  teamspace's access level in Notion). The admin maps each wiki section to a
  teamspace in `config/notion.yaml` (`teamspaces` + `section_teamspace`), using
  `admin_only` to keep sensitive sections MD-only (never mirrored). The admin
  also sets each member's **ingest scope** (which of their accounts feed the
  wiki). Validated writes/ingests are generally allowed; reads are enforced by
  Notion. See the `access-control` rule.
- **Confirm before connecting each platform.** Tell the user what a step does and
  what token/scope it needs; wait for their go-ahead.
- **Finance is read-only.** Mercury and Ramp use read-only tokens. Never set up
  or attempt money movement, payments, card issuance, or limit changes.
- **Markdown first.** The wiki Markdown files are the source of truth; Notion is a
  mirror. Agents write Markdown via `write_wiki_page`, then sync.
- **Write only to the system of record.** Agents write to the wiki/Notion or a
  ledger doc as proposals a human reviews — never to a bank/card platform.
- **Never commit secrets.** Tokens go in `.env` (gitignored). Never print full
  tokens back to the user or place them in tracked files.
- **Verify with `company-brain doctor`** after each connection step.

## Step 0 — Choose deployment mode

Ask the user: local or cloud?

- **local** (default): wiki Markdown lives in `./wiki` (gitignored). Good for a
  single machine / trying it out.
- **cloud**: wiki Markdown lives on the smol cloud VM's persistent storage at
  `/workspace/wiki`. Set `COMPANY_BRAIN_MODE=cloud` and
  `COMPANY_BRAIN_WIKI_DIR=/workspace/wiki`.

Copy `.env.example` to `.env` and fill values as you go.

## Step 1 — Install and check

```bash
pip install -e .
company-brain doctor
```

`doctor` prints the mode, wiki dir, runtime, and which platforms are connected.
Re-run it after each step below to confirm progress.

## Step 2 — Connect platforms

Do these in any order the user wants; only connect what they use. After each,
run `company-brain doctor` to confirm.

### Notion (required — the wiki mirror)
1. Install the Notion CLI (`ntn`) and run `ntn login`.
2. `company-brain init` — discovers existing workspace content and sets up the
   wiki structure (the user picks a merge strategy).
- Verify: `doctor` shows "Notion CLI authenticated" and "Wiki initialized".

### GitHub (engineering department) — read-only
1. Install GitHub CLI (`gh`) and authenticate (`gh auth login`); read-only is enough.
2. The engineering agents (open PRs, feature updates, product features) will use it.

### Mercury (finance) — READ-ONLY token
1. Create a **read-only** Mercury API token; set `MERCURY_TOKEN` (and
   `MERCURY_ENV=production`). Install the Mercury CLI if available.
2. Never use a token with payment/transfer scope.

### Ramp (finance) — READ-ONLY via MCP
1. Create a **read-only** Ramp token; set `RAMP_TOKEN`.
2. Configure the Ramp MCP server (`RAMP_MCP_COMMAND`/`RAMP_MCP_ARGS`, or
   `RAMP_MCP_URL`). See https://docs.ramp.com/developer-api/v1/ramp-mcp.

### Slack (finance notifications)
1. Create a Slack bot token; set `SLACK_BOT_TOKEN`.
2. Set the finance channel id in `config/finance.yaml` (`slack.channel_id`).

### Anthropic (LLM agents)
- Set `ANTHROPIC_API_KEY` (used by the absorb writer and LLM-backed agents).

## Step 3 — Onboard each connected platform

Run the one-time onboarding agents to backfill history for platforms the user
connected (these seed the wiki + Notion):
- GitHub: the `github_onboarding` agent.
- Finance: the `finance_onboarding` agent (backfills monthly + quarterly reports).

## Step 4 — Operate and verify

- Run or schedule the managers (e.g. `github_manager`, `monthly_expense`,
  `quarterly_calculation`). Locally they run in-process; in cloud they target VMs.
- Confirm the wiki Markdown appears under the wiki dir and mirrors to Notion.
- `company-brain status` shows article counts and sync state.

## Adding a new platform later

When the user wants a new platform, follow the project rules in `.cursor/rules/`:
- `agent-organization.mdc` — department → platform → agents layout.
- `agent-construction.mdc` — which SDK/integration to use; finance is read-only.
- `wiki-data-flow.mdc` — Markdown-first, then sync to Notion.
- `agent-eval.mdc`, `agent-runtime.mdc`, `agent-scheduling.mdc`,
  `agent-onboarding.mdc`, `agent-lifecycle.mdc` — eval/cost gates, runtime,
  scheduling, onboarding, and lifecycle conventions.

Keep both docs in sync: `README.md` is for humans; this `project_install.md` is
the onboarding runbook for the assisting agent.
