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
- **Markdown first.** The wiki Markdown **volume on the wiki host** is the source of
  truth; Notion is a mirror. Agents write Markdown via `write_wiki_page`, then sync.
  An admin-only GitHub **company-wiki** repo is a daily backup / version history —
  not a live read or write plane.
- **Two GitHub repos (company org).** (1) Private **company-brain / 4r7a** — agent
  code; Weave opens draft PRs here; admin merges when free. (2) Private **admin-only
  company-wiki** — MD backup from `wiki_commit`. Employees do not get GitHub access
  to the wiki repo. Upstream public 4r7a sync into the private fork is admin-driven
  (not Weave-auto).
- **Two bots, least privilege.** Wiki git bot (`COMPANY_BRAIN_WIKI_GIT_TOKEN`) —
  push to company-wiki only. Weave / `gh` bot — branches/PRs on the agent repo only;
  no merge; no wiki-repo write. Never one god-token for both.
- **Write only to the system of record.** Agents write to the wiki/Notion or a
  ledger doc as proposals a human reviews — never to a bank/card platform.
- **Never commit secrets.** Tokens go in `.env` (gitignored). Never print full
  tokens back to the user or place them in tracked files.
- **Verify with `company-brain doctor`** after each connection step.

## Step 0 — Choose deployment mode

**Preferred (coding agent):** follow
[`.cursor/skills/4r7a-install/SKILL.md`](.cursor/skills/4r7a-install/SKILL.md) and:

```bash
company-brain install profile          # decisions → config/install_profile.yaml
company-brain install credentials      # keys/OAuth for enabled platforms only
company-brain install foundation       # repos + Notion + wiki_git checks
company-brain install onboard          # eng → ops → product → growth → finance → hr
company-brain install status
```

Ask the user: local or cloud?

- **local** (default): wiki Markdown lives in `./wiki` (gitignored). Good for a
  single machine / trying it out.
- **cloud**: wiki Markdown lives on the cloud VM's persistent storage at
  `/workspace/wiki`. Set `COMPANY_BRAIN_MODE=cloud` and
  `COMPANY_BRAIN_WIKI_DIR=/workspace/wiki`. Default VM provider is
  **smol cloud** (Smol Machines); install the smolvm CLI and configure smol
  cloud credentials when using the default fleet.

Runtime is co-located: one host runs the **private agent checkout** and mounts the
**MD volume** (`COMPANY_BRAIN_WIKI_DIR`, employee wiki, `raw/`). GitHub separation
does not require two machines.

**Repos repos (admin creates these):** private company **4r7a** clone (brain) and
an empty private **company-wiki**. Paste both URLs into
`company-brain install profile` — the installer validates access; it does not
create GitHub repos.

Copy `.env.example` to `.env` and fill values as you go (or from
`install credentials`).

### Wiki GitHub backup (`wiki_commit`) — optional but recommended

1. Admin creates a **private** `{org}/company-wiki` repo (admin-only GitHub ACL).
2. Clone it on the wiki host to `./.wiki_git` (or `COMPANY_BRAIN_WIKI_GIT_DIR`).
   First-push / empty-repo bootstrap UX is still tabled — pre-create and clone manually.
3. Set `COMPANY_BRAIN_WIKI_GIT_TOKEN` (contents:write on company-wiki only).
4. In `config/operations.yaml` → `admin.wiki_commit`: set `enabled: true`,
   `remote_url` to the HTTPS clone URL, optional `hour_utc` (default 6).
5. Start: `company-brain admin wiki-commit --loop` (or `--force` for a one-shot test).

Daily job mirrors `wiki/`, `employee_wiki/`, and `raw/` into the clone and pushes
one commit to `main` when dirty (never force-push). Failures notify `#wiki-admin`.

**Recovery (manual):** stop writers → restore volume trees from a company-wiki
commit into the configured wiki dirs → rebuild indexes (`company-brain` index /
absorb control rebuild as needed) → resume agents. Do **not** auto-overwrite a
healthy volume from GitHub. Automated rollback agents are tabled.

### Admin console — logged-in ops cockpit (wiki host)

Private-mesh web UI for agent status, LLM costs, wiki search/edit, allow-listed
dispatch, and Assist. **Not** the member bridge; do not share console credentials
with member coding agents.

1. `pip install 'company-brain[admin-console]'`
2. Set in `.env`:
   - `ADMIN_CONSOLE_PASSWORD` (required)
   - `ADMIN_CONSOLE_SESSION_SECRET` (recommended; otherwise derived from password)
3. Adjust `config/admin_console.yaml` (bind host/port, manager catalog, dispatch allow-list)
4. Start: `company-brain admin console` (default `127.0.0.1:8780`)
5. Reach via Tailscale/SSH tunnel — do not bind publicly without a reverse proxy + TLS

**CLI:** `admin console [--host] [--port]`

Handbook: [`docs/agents/admin.md`](docs/agents/admin.md) → Admin console.

## Step 1 — Install and check

```bash
pip install -e .
company-brain doctor
```

For VM-backed runs (sandbox verification or cloud fleet), install the default
[smolvm](https://github.com/smol-machines/smolvm) CLI (Smol Machines):

```bash
curl -sSL https://smolmachines.com/install.sh | bash
smolvm --help
```

Local sandbox: set `COMPANY_BRAIN_SANDBOX=smolvm`. Cloud fleet (default provider):
set `COMPANY_BRAIN_MODE=cloud`, `COMPANY_BRAIN_RUNTIME=cloud`, and configure smol
cloud credentials when the `smol machine` integration ships. To use a different
cloud VM provider, set `COMPANY_BRAIN_VM_PROVIDER` to your provider key.

`doctor` prints the mode, wiki dir, runtime, and which platforms are connected.
Re-run it after each step below to confirm progress.

**Web search (recommended on always-on hosts):** agents default to
[local-search](https://github.com/Kevin-Liu-01/local-search) (`lsearch`) — free
structured search via a local Chrome profile. Install Rust/`cargo`, then:

```bash
cargo install local-search
lsearch launch          # once — managed Chromium profile; sign in if needed
lsearch doctor --pretty
```

Config: `config/web_search.yaml` (`backend: auto` prefers `lsearch`, else Claude
`WebSearch`). Cloud VMs without a browser keep working via the Claude fallback.

## Step 2 — Connect platforms

Do these in any order the user wants; only connect what they use. After each,
run `company-brain doctor` to confirm.

### Notion (required — early; the wiki visualizer)

Default teamspaces: **admin** (finance/legal/admin) and **company** (engineering,
product, growth). Optional department splits later via `config/notion.yaml`.

1. Install the Notion CLI (`ntn`) and run `ntn login`.
2. Set `teamspaces.admin` / `teamspaces.company` parent page IDs in `config/notion.yaml`
   (or run `company-brain init` for interactive discovery).
3. `company-brain notion onboarding run` — ingests existing Notion pages into MD.
   If the workspace already has content, structured mirror is **not** established until
   you re-run with `--confirm-mirror` (alongside 4r7a tree + Archive parents; old tree
   left for admin to delete after review).
4. Start steady-state: `company-brain notion manager` (or rely on onboarding handoff).

CLI: `notion sync-pull`, `notion manager [--once]`, `notion onboarding run [--confirm-mirror]`.

Verify: `doctor` shows Notion CLI authenticated; wiki pages bind via `notion_page_id`.
Handbook: [docs/agents/operations.md](docs/agents/operations.md) → Notion.

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

Finance agents post to Slack via `config/operations.yaml` → `gmail.slack` channel
names (e.g. `#customer-support`). They reuse the wiki bot token below.

### Slack (operations platform) — **required wiki bot**; Weave optional

Two Slack apps:

| App | Env | Purpose |
|-----|-----|---------|
| **Wiki bot** | `SLACK_WIKI_BOT_TOKEN` (required) | Passive ingest, `@wiki`, customer support, open threads |
| | `SLACK_WIKI_APP_TOKEN` | Socket Mode (local default) for `company-brain slack events` |
| | `SLACK_WIKI_SIGNING_SECRET` | HTTP mode only |
| **Weave bot** (optional) | `SLACK_WEAVE_BOT_TOKEN`, `SLACK_WEAVE_APP_TOKEN` | `@weave` system-change requests |

Legacy `SLACK_BOT_TOKEN` is accepted as a fallback for the wiki bot only.

1. Create the **wiki** Slack app with Events + `app_mention`, `message`, `reaction_added`,
   `member_joined_channel`, `user_change` (for offboard signals). Install to workspace.
2. Set `SLACK_WIKI_BOT_TOKEN` and `SLACK_WIKI_APP_TOKEN` (Socket Mode).
3. `company-brain slack sync-channels` — populate `config/slack_channels.json`.
4. `company-brain slack onboarding estimate` then `company-brain slack onboarding run`
   (default 30-day backfill; optional `--absorb`).
5. Start hot lane: `company-brain slack events` (persistent listener).
6. Start steady-state manager: `slack_manager` (or rely on onboarding handoff).
   Daily `thread_absorb` enqueues internal threads into `raw/entries` (manual:
   `company-brain slack thread-absorb [--force]`).

**Weave (optional):** second Slack app with `app_mention` only → set `SLACK_WEAVE_*`
tokens → `company-brain weave events`. Populate `config/notion.yaml`
`change_request_database` after Notion connect. W2 members in `members.yaml` only;
roster (`config/roster.yaml`) cannot invoke Weave.

**Weave builder (implement+prove):** default backend is Codex on the [smol registry](https://smolmachines.com/registry)
image (`slack_platform.weave.builder: codex`). Set `COMPANY_BRAIN_SANDBOX=smolvm`,
install `smolvm`, and provide `OPENAI_API_KEY` (or `WEAVE_OPENAI_API_KEY`) for guest
runs. Opt into the in-house builder with `WEAVE_BUILDER=in_house` or
`company-brain weave poll-approvals --builder in_house`. Disable with `builder: off`
(proposal markdown PR only). Builder egress is GitHub + model host only — never bank
or Slack tokens in the VM.

**Admin CLI:** `slack channel list|tag|enable-connect`, `weave poll-approvals [--builder …]`.

**HR lifecycle:** fill `config/hr_seed.yaml` (current employees + past hires), then
`company-brain hr onboard --seed`. New joiners: add to `members.yaml` /
`roster.yaml` (include `linkedin_url` + `department`) →
`company-brain hr onboard {key}`. Departure: Slack signal or
`hr offboard {key}` proposes; admin actuates with
`hr confirm-offboard {key}` (bridge revoke + T+30 wiki archive). Steady-state:
`company-brain hr manager`. Also: `hr promote {roster_key}`.

Verify with `doctor` (Slack wiki / Weave lines). Handbook:
`docs/agents/operations.md` (Slack), `docs/agents/admin.md` (Weave), `docs/agents/hr.md`.

### Discord (growth department) — read-only community bot

Open-source developer community ingest. The bot **reads only** — it never posts to
Discord. Draft replies for humans go to Slack `#discord`.

1. Create a Discord application + bot at https://discord.com/developers/applications
2. Enable **Message Content Intent** (privileged) under Bot settings
3. Invite the bot to your community server with read/view permissions
4. Set `DISCORD_BOT_TOKEN` in `.env`
5. Set `discord.guild_id` in `config/growth.yaml` (right-click server → Copy Server ID)
6. Adjust `discord.exclude_channels` (default includes `off-topic`)
7. Sync channel registry: `company-brain discord sync-channels`
8. Estimate backfill: `company-brain discord onboarding estimate`
9. Run onboarding: `company-brain discord onboarding run` (default 30-day backfill; starts `discord_manager`)
10. Start Gateway: `company-brain discord gateway` (WebSocket hot lane — run alongside manager)

Add per-member `bindings.discord_id` (and optional `discord_handle`) in
`config/members.yaml` so the system can detect when a team member is already in a thread.

**CLI:** `discord gateway`, `discord manager`, `discord sync-channels`, `discord channel list`,
`discord onboarding estimate|run` (`--days`, `--all`, `--no-manager`, `--absorb`).

Handbook: [`docs/agents/growth.md`](docs/agents/growth.md).

### PostHog (product department) — read-only snapshots

Weekly wiki snapshots (tracking audit, feature usage, experiments, signup funnel).
The client **reads only** — no flag, experiment, or capture mutates. Admin connects
PostHog; instrumentation stays in the product app / PostHog UI.

1. In PostHog, create a **personal API key** with read scopes for query, feature flags,
   and experiments (Project settings → Personal API keys).
2. Note the **project ID** and cloud host (`https://us.posthog.com` or
   `https://eu.posthog.com`).
3. Optionally create a Signup dashboard and a funnel insight named
   `Landing to signup` (landing → create account). Event names can match
   `config/product.yaml` → `posthog.signup_funnel` or override there.
4. Set in `.env`:
   - `POSTHOG_PERSONAL_API_KEY`
   - `POSTHOG_PROJECT_ID`
   - `POSTHOG_HOST` (optional; default `https://us.posthog.com`)
5. Adjust `posthog:` in `config/product.yaml` (timezone, Monday 09:00 run,
   `min_exposures`, funnel names/steps). Ensure Slack channel `#product` exists
   (or change `slack.product_channel`).
6. Snapshot + start manager: `company-brain posthog onboarding run`
   (30-day lookback when prior events exist; `--no-manager` to skip handoff).
7. Or run the persistent loop alone: `company-brain posthog manager`
8. Product **workstreams** (newsletter, use cases, docs audit, progress,
   attribution): `company-brain product onboarding`. Optional:
   `docs.base_url` and `attribution.signup_source` in `config/product.yaml`.

**CLI:** `posthog manager`, `posthog onboarding run` (`--no-manager`);
`product onboarding`, `product *-manager [--once]`,
`product newsletter|docs-audit|progress|signup-match|use-cases`.

Handbook: [`docs/agents/product.md`](docs/agents/product.md).

### Google Ads (growth department) — read-only snapshots

Weekly wiki snapshots (campaign status, budget pacing, Ads-reported CPA). The
client **reads only** — no campaign, budget, bid, or recommendation mutates.

1. Create a Google Cloud OAuth client (Desktop or Web) and complete the Ads API
   OAuth consent flow for a user with **read** access to the Ads account
   (prefer a read-only Google Ads user role).
2. Apply for a Google Ads **developer token** and note the Ads **customer ID**
   (and MCC login customer ID if the account sits under a manager).
3. Install the client library: `pip install 'company-brain[google-ads]'` (or
   `pip install google-ads`).
4. Set in `.env`:
   - `GOOGLE_ADS_DEVELOPER_TOKEN`
   - `GOOGLE_ADS_CLIENT_ID`
   - `GOOGLE_ADS_CLIENT_SECRET`
   - `GOOGLE_ADS_REFRESH_TOKEN`
   - `GOOGLE_ADS_CUSTOMER_ID`
   - `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (optional, MCC)
5. Adjust `google_ads:` in `config/growth.yaml` (timezone, Monday 08:00 run,
   pacing alert threshold default `0.9`).
6. Snapshot + start manager: `company-brain google-ads onboarding run`
7. Or run the persistent loop alone: `company-brain google-ads manager`

**CLI:** `google-ads manager`, `google-ads onboarding run` (`--no-manager`).

Handbook: [`docs/agents/growth.md`](docs/agents/growth.md).

### Growth workstreams — activity / content / competitor / leads

Complements Discord + Ads. No Luma/Partiful API; content agents never post.

1. Set `competitor.keywords` in `config/growth.yaml` (company core-product terms).
2. Seed pages + start workstream managers:
   `company-brain growth onboarding` (or `--no-managers` then start individually).
3. Register events only via human entry:
   - CLI: `company-brain growth event register "Demo Night" --date 2026-08-01`
   - Slack: `@wiki register event Demo Night on 2026-08-01`
   - Admin console Dispatch / Assist (allow-listed)
4. Plan / partner / wrap: `growth event plan|partner|wrap`, or matching `@wiki` commands.
5. Lead CSV after events: `growth event wrap <slug> --attendees-csv path.csv` or
   `growth leads enqueue --source attendee_csv --csv path.csv`.
6. Drafts: `growth draft blog|x|linkedin "…"`. Published pull:
   `growth published-pull --item 'x|Title|url|final text'`.

**CLI:** `growth onboarding`, `growth event …`, `growth activity-manager|content-manager|competitor-manager|lead-manager`,
`growth leads enqueue`, `growth draft`, `growth published-pull`.

Handbook: [`docs/agents/growth.md`](docs/agents/growth.md).

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

**Onboarding (once):** after `LINEAR_API_KEY` and `config/engineering.yaml` are set, run
`linear_onboarding` — it backfills Gmail task bindings, writes a **Structure Proposal**
proposal to the wiki (Notion mirror), runs slot_check, and starts the persistent
`linear_manager`. It does not wait for structure approval.

### Granola (operations department) — read-only meeting notes
Granola supplies AI meeting notes and transcripts. The persistent
**`meeting_watch`** agent polls the calendar and dispatches **`ingest`**
after each meeting ends, with a weekly **`miss_check`** as the backstop.

Pick a deployment mode (`granola.mode` in `config/operations.yaml`, or auto-detected from env):

- **Business plan — per-member keys.** Each teammate who uses Granola creates an API key
  in Granola → Settings → Connectors → API keys with **Personal notes** scope. List
  members in `granola.members` (label + email) and set keys via
  `GRANOLA_MEMBER_KEYS=alice:grn_...,bob:grn_...` or `GRANOLA_API_KEY_<LABEL>`.
- **Enterprise plan — company-wide key.** Create one API key with **Public notes** scope
  (notes must live in Team-space folders visible to the workspace). Set `GRANOLA_API_KEY`.

Docs: https://docs.granola.ai/introduction · Connection layer:
`operations/granola/granola_client.py`. On first connect, run **`granola_onboarding`**
(default **30-day** backfill via `granola.onboarding.backfill_days`, then starts the
persistent `meeting_watch`). Verify with `doctor` ("Granola meeting notes …").

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

### LLM provider and model tiers

During wiki onboarding, configure how agents use LLMs:

```bash
company-brain models configure
```

Ask the user to choose:

1. **performance** — reasoning tier (most powerful model) for every LLM agent.
2. **balanced** (recommended) — per-agent tier tradeoff (absorb/reports on
   reasoning; draft replies and routine audits on standard).

This writes `config/models.yaml` (`mode`, `tiers`, `agents`, `agent_providers`).

**Mixed providers (strategy B):** MCP-native agents (absorb, draft_reply,
card_spend, subscription_audit) run on Anthropic; `budget_report` runs on
OpenAI when both keys are set. Set both `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY` in `.env`.

**Token budget (optional):** enable in `config/models.yaml` under
`token_budget` — monthly USD cap ($250 default pool), runtime/builder guidance
split, alert at 80%, optional hard stop. Usage is tracked automatically from
LLM API responses; per-run caps (`run_limits`) enforce USD/steps/tool-call
limits outside the model.

```bash
company-brain models budget              # status + per-agent run caps
company-brain models budget --reconcile  # compare tracked usage vs Mercury vendor bills
company-brain models spot-check          # vibe eval samples → #wiki
company-brain admin manager              # monthly LLM expense + maintain (one pass)
company-brain admin wiki-commit --loop   # daily MD volume → company-wiki backup
```

**Monthly LLM ops:** `admin_manager` writes `admin/llm-expense/{YYYY-MM}.md` and
`admin/maintain/{YYYY-MM}.md`, refreshes `admin/agent-runtime.md`, and requests an
admin coding session on `#wiki-admin` when budget/duration/verify drift. Schedule in
`config/operations.yaml` → `admin.llm_ops`. Handbook: `docs/agents/admin.md`.

**Wiki commit:** persistent `wiki_commit` (independent of `admin_manager`). Config
`admin.wiki_commit`; token `COMPANY_BRAIN_WIKI_GIT_TOKEN`. See Step 0 above.

**Model health:** `company-brain doctor llm` pings configured models, auto-falls
back within `fallback_chains`, persists overrides in `models.yaml`, alerts
`#wiki-admin` on substitution, and (when budget enabled) reconciles tracked
spend against Anthropic/OpenAI card charges.

Hosted provider keys for local installs; GLM-5 self-host option unchanged below.

One knob — `COMPANY_BRAIN_LLM_PROVIDER` (legacy default provider) —
still selects the fallback when an agent has no explicit `agent_providers` entry.
Confirm API keys with the user.

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
     to the exact Ollama model tag you pulled (e.g. `glm-5`). Add the host to
     `Smolfile` `[network] allow_hosts` only if Ollama runs off-VM.
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
- Granola: **`granola_onboarding`** (default 30-day backfill, starts `meeting_watch`).
- Slack: **`slack_onboarding`** (`company-brain slack onboarding run` — estimate,
  backfill, starts `slack_manager`; run `company-brain slack events` for the hot lane).
- Employee wiki (optional): for each person in `config/members.yaml`, run the
  `employee_wiki_onboarding` agent — it creates the company `people/` stub and the
  member's `employee_wiki/{member}/_index.md`, then discovers/creates their Notion
  personal teamspace and syncs the index. Start `employee_wiki_manager` to
  materialize work events (Linear/Granola/Gmail/Slack) into per-member work logs.
  Members import existing notes as a zip of `.md` files via `employee_wiki_import`
  (quarantined, scanned, and admin-reviewed before promotion).
- External wiki (admin): mount a one-shot external Markdown wiki (zip of `.md`) via
  `external_wiki_import` into `wiki/external/{source}/`. Register the source in
  `config/external_sources.yaml`, review at `admin/mount-review/{id}.md`,
  approve with `ExternalWikiImportAgent.approve(...)`. Rebuild the fleet catalog with
  `company-brain catalog` (`admin/content-catalog.md` → admin Notion teamspace).

## Step 4 — Operate and verify

- Run or schedule the managers (e.g. `github_manager`, `monthly_expense`,
  `quarterly_calculation`, `employee_wiki_manager`). Locally they run in-process;
  in cloud they target VMs.
- Confirm the wiki Markdown appears under the wiki dir and mirrors to Notion;
  per-member pages appear under the employee wiki dir.
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
