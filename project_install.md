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

### Gmail (operations department) — read + labels + DRAFT only, never send
Gmail is reached over MCP. Pick one path (`GMAIL_MCP_PROVIDER`, default `official`):

- **Official Gmail MCP (default, recommended for open source).** The admin uses
  their own Google Cloud project so the trust stays with them. In Google Cloud:
  enable `gmail.googleapis.com` and `gmailmcp.googleapis.com`, configure the OAuth
  consent screen with scopes `gmail.readonly` + `gmail.compose` + `gmail.modify`,
  create an OAuth client, and complete the consent flow. Set `GMAIL_OAUTH_CLIENT_ID`,
  `GMAIL_OAUTH_CLIENT_SECRET`, and `GMAIL_OAUTH_ACCESS_TOKEN` (server URL defaults
  to `https://gmailmcp.googleapis.com/mcp/v1`). Set `GMAIL_MAILBOX=me` (or the
  connected email). The `gmail.modify` scope is required for label/archive/read
  state via `gmail_rest.py` (triage and sweep); MCP handles search/drafts.
  need a super admin to mark the OAuth app Trusted for the restricted scopes.
  Docs: https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server
- **Composio (optional, less setup).** Set `COMPOSIO_API_KEY` and either
  `COMPOSIO_GMAIL_MCP_URL` (a pre-created server/session URL) or let the composio
  SDK mint a Tool Router session for `COMPOSIO_USER_ID`. Adds a vendor dependency.
  Docs: https://composio.dev/toolkits/gmail

Posture: agents only read, label, and draft — **never send**. Keep
`gmail.allow_send: false` in `config/operations.yaml`. Verify with `doctor`
("Gmail connection ... read+draft"). On first connect, run `gmail_onboarding`
(ensures labels, 30-day backfill triage, starts profile-enabled persistent agents
+ `gmail_manager`).

**Service profiles** (`config/operations.yaml` → `gmail.profiles`):

| Profile | Use case |
|---------|----------|
| `executive_assistant` (default) | Full EA package for startup founders — all labels, nested cold inbound/newsletters, every specialist |
| `employee` | Employee Gmail — attention 1–4, flat `Cold Inbound` / `Newsletters`, no Investor or Warm intro; investor/partnership/receipt agents off |
| `service_account` | Purpose-built inboxes — attention 1–3 only; minimal domain labels and agents; override per mailbox |

Set the active profile with `gmail.profile` (default) or `GMAIL_PROFILE=employee` per
deploy. Per-mailbox overrides: `gmail.mailbox_profiles` (see commented examples in config).
`gmail_manager` runs for every connected account; triage labels and dispatched
specialists follow the profile.

### Linear (engineering department)
Linear powers issue tracking for engineering agents (forthcoming) and cross-department
Gmail workflows (`inbox_task`, `team_on_it`). Pick one auth path:

- **Personal API key (recommended).** In Linear → Settings → Account → Security & Access,
  create an API key. Set `LINEAR_API_KEY`. Configure `linear.team_key` (e.g. `ENG`) or
  `linear.team_id` in `config/engineering.yaml`.
  Docs: https://linear.app/developers/graphql
- **Official MCP (optional).** Remote MCP at `https://mcp.linear.app/mcp` with the same
  API key as `Authorization: Bearer …` for Claude Agent SDK agents.
  Docs: https://linear.app/docs/mcp.md
- **Community CLI (optional).** Install [joa23/linear-cli](https://github.com/joa23/linear-cli)
  or similar, run `linear auth login`, and set `LINEAR_USE_CLI=1` to delegate reads/writes
  to the `linear` binary instead of direct GraphQL.

Connection layer: `engineering/linear/linear_client.py`. Verify with `doctor` ("Linear …").
See https://linear.app/llms.txt for the full doc index.

### Granola (operations department) — read-only meeting notes
Granola supplies AI meeting notes and transcripts. The **`granola_ingest`** agent pulls
notes from meetings that happened that day and ingests them at **6pm** (workdays).

Pick a deployment mode (`granola.mode` in `config/operations.yaml`, or auto-detected from env):

- **Business plan — per-member keys.** Each teammate who uses Granola creates an API key
  in Granola → Settings → Connectors → API keys with **Personal notes** scope. List
  members in `granola.members` (label + email) and set keys via
  `GRANOLA_MEMBER_KEYS=alice:grn_...,bob:grn_...` or `GRANOLA_API_KEY_<LABEL>`.
- **Enterprise plan — company-wide key.** Create one API key with **Public notes** scope
  (notes must live in Team-space folders visible to the workspace). Set `GRANOLA_API_KEY`.

Docs: https://docs.granola.ai/introduction · Connection layer:
`operations/granola/granola_client.py`. On first connect, run **`granola_onboarding`**
(default **30-day** backfill via `granola.onboarding.backfill_days`, then starts
`granola_ingest` at its next 6pm wake). Verify with `doctor` ("Granola meeting notes …").

### Google Calendar (operations department) — read + book meetings
Google Calendar uses the same OAuth setup pattern as Gmail. Enable
`calendar-json.googleapis.com` and `calendarmcp.googleapis.com` in your Google Cloud
project, add calendar scopes to the OAuth consent screen, and include them in the
token used by `GMAIL_OAUTH_ACCESS_TOKEN` (or set `GCAL_OAUTH_ACCESS_TOKEN`).

Agents:
- **`calendar_availability`** — open slots for meeting proposals
- **`book_meeting`** — create events with guests and Google Meet links
- **`ext_meeting_scheduler`** (Gmail folder) — drafts time proposals or books confirmed meetings
- **`daily_agenda`** — optional morning Slack DM (`gcal.daily_agenda.enabled: false` by default)

Docs: https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server
· Connection: `operations/gcal/gcal_client.py` + `gcal_rest.py`. Verify with
`doctor` ("Google Calendar …").

### LLM provider (which model powers the agents)
One knob — `COMPANY_BRAIN_LLM_PROVIDER` (resolved against `config/models.yaml`) —
selects the model for every agent. Confirm the choice with the user.

- **local installs → a hosted provider key (default).** Locally installing GLM-5
  is not realistic, so default to `anthropic` (set `ANTHROPIC_API_KEY`) or
  `openai` (set `OPENAI_API_KEY`).
  - *Option:* a local install can still use open-source GLM-5 by **remote-connecting
    to an open-source host** — set `COMPANY_BRAIN_LLM_PROVIDER=glm` and point
    `GLM_BASE_URL` at that host's OpenAI-compatible endpoint (and `GLM_API_KEY`
    if it requires one).
- **cloud installs → GLM-5 self-hosted (open-source, no external tokens) or a
  hosted key.** To run GLM-5 on the GPU VM, use **Ollama** (easier than pulling
  raw weights from the GitHub/HF repo — it handles download, quantization, and
  serving, and exposes an OpenAI-compatible API out of the box):
  1. Install Ollama (https://ollama.com/download) and start it (`ollama serve`).
  2. **Pull the newest GLM-5** from the Ollama model library:
     `ollama pull glm-5` (use the latest GLM-5 tag the library publishes).
  3. Set `COMPANY_BRAIN_LLM_PROVIDER=glm` and point `GLM_BASE_URL` at Ollama's
     OpenAI-compatible endpoint (`http://localhost:11434/v1`); `GLM_API_KEY` can
     be any non-empty value (`ollama` ignores it). Set `COMPANY_BRAIN_LLM_MODEL`
     to the exact Ollama model tag you pulled (e.g. `glm-5`). Add the host to the
     `sfile`/Smolfile `allow_hosts` only if Ollama runs off-VM.
  - GLM-5 is large (744B-A40B); run Ollama on a capable GPU VM. For high-throughput
    production serving, SGLang (RadixAttention) or vLLM (`--enable-prefix-caching`)
    remain alternatives — same `glm` provider, just a different `GLM_BASE_URL`.

The OpenAI Agents SDK specialists run on whichever provider is selected; the
Claude Agent SDK agents (absorb writer, MCP-native reasoning agents) use Anthropic
by default and can be pointed at an open-source model via `ANTHROPIC_BASE_URL`
(a LiteLLM gateway). Verify with `company-brain doctor` (the `LLM:` line shows the
active provider, model, and endpoint).

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
