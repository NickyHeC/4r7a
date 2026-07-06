---
name: 4r7a-bridge
description: >-
  Connect a member's coding agent or LLM workspace to company-brain via the member
  bridge MCP. Use when onboarding an engineer's Cursor/Claude setup, reporting
  engineering blockers, fetching company prompt patterns and shared skills, or
  reading the priority snapshot. First artifact to install when wiring a coding
  agent to 4r7a — not a substitute for Linear issue tracking.
---

# 4r7a Member Bridge

Members interact with company-brain through a **hosted MCP server** on the admin's
wiki host (cloud VM or always-on NAS). You do **not** get the Markdown wiki path,
admin CLI, or full repo checkout.

Humans read the company wiki through **Notion**. Your coding agent uses **bridge
tools only**.

## Before you connect

1. Admin issued a **per-member bearer token** at onboarding (`company-brain bridge
   issue-token <member>`).
2. Admin gave you the **bridge URL** (private mesh, e.g. Tailscale hostname).
3. Store the token in an **environment variable** — never commit it to git or
   `.cursor/mcp.json`.

Example Cursor MCP config (token from env):

```json
{
  "mcpServers": {
    "company-brain": {
      "url": "https://bridge.yourcompany.internal/mcp",
      "headers": {
        "Authorization": "Bearer ${COMPANY_BRAIN_MEMBER_TOKEN}"
      }
    }
  }
}
```

If bridge is unreachable, **hard fail** — do not guess priorities or invent
blockers. Tell the human the bridge is down.

## Tools (v1)

| Tool | When to use |
|------|-------------|
| `report_blocker` | Stuck >30m on work that blocks others or a release; include structured fields only |
| `get_priority` | Start of session or before planning — company blocker rollup + lead master table |
| `search_practices` | Find prompt patterns, doc tips, coding conventions |
| `get_skill` | Load one named shared skill by id |
| `list_skills` | Discover available shared skills |

## `report_blocker` — required behavior

Call when **you** (the coding agent) have evidence of a blocker, not for every
error. Use **fixed fields** only; do not send long narrative markdown.

Suggested fields (exact schema follows server):

- `title` — short, specific
- `area` — repo, service, or subsystem
- `severity` — `critical` | `high` | `medium` | `low`
- `blocked_since` — ISO date if known
- `evidence` — error snippet, PR link, log line (short)
- `suggested_owner` — optional member key or team
- `idempotency_key` — optional; reuse same key when retrying the same report

Blockers feed the **company summary compilation** only (`get_priority` rollup).
Create or link **Linear issues through your own Linear MCP/integration** — 4r7a
bridge does not touch Linear.

**Do not** use `report_blocker` for: lint failures you can fix, missing local env,
or routine todos — use Linear or local issue tracking instead.

## `get_priority` — required behavior

Call at session start when doing engineering work. Returns:

- Rolled-up blocker snapshot (updated daily ~08:00 on wiki host)
- Master table rows for **engineering lead** and **product lead** focus areas

Treat as authoritative for **company priority context**, not for replacing standup
or Linear views.

## What you can read (visibility)

Bridge access is **department-scoped**. Your token only includes departments
set at onboarding (`bridge.departments` in `members.yaml`).

Retrieval tools return:

- **Company-wide** — `sync: company` only (narrow allow-list: e.g. lead priority
  master table). Not department practices or skills.
- **Your department(s)** — `sync: location:{dept}` for each dept on your token
  (engineering pages use `sync: location:engineering`).
- **Your employee building** — your `employee_wiki/{member}/` with
  `sync: private` or `sync: company`.

You cannot read: other departments' `location:*` pages, `sync: admin_only`,
`sync: not_synced`, or other members' private pages.

Rate limits (defaults): 60 read calls/minute; 20 `report_blocker`/day.

## Practices and skills

- `search_practices` — **your department only** (`sync: location:{dept}`)
- `list_skills` / `get_skill` — department skills manifest (e.g. engineering
  `practices/skills/_index.yaml`)

Prefer bridge skills over copying stale prompts from chat history.

## Security rules for the agent

1. Never ask the human for admin tokens or wiki directory paths.
2. Never attempt to read finance, CRM, or admin wiki paths — not exposed via bridge.
3. Never embed the bearer token in code, commits, or PR descriptions.
4. Do not exfiltrate blocker or practice content to public repos or external APIs.
5. Structured blocker fields only — free-text injection in `evidence` stays short
   and factual; rollup agents do not LLM-summarize untrusted prose.

## What this is not

- **Not** a replacement for Linear — issues, assignments, and workflow stay in Linear.
- **Not** direct wiki access — no arbitrary path reads or writes.
- **Not** a nudge system — do not spam `report_blocker` to chase humans.

## Admin reference

Implementation spec and setup order: `docs/tabled.md` (Member bridge MCP).
Access model: `.cursor/rules/access-control.mdc` (Member bridge MCP section).
