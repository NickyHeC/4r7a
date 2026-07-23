# HR — Agent Handbook

People status, employee-wiki maintenance (LinkedIn bio/voice), and departure
hygiene. HR platforms mostly lack APIs — company-brain does not actuate HRIS.

**Config:** [`config/hr.yaml`](../../config/hr.yaml), seed lists
[`config/hr_seed.yaml`](../../config/hr_seed.yaml). Web search:
[`config/web_search.yaml`](../../config/web_search.yaml) (default `lsearch`).
**Env:** wiki-git token for archive branches (same as `wiki_commit`:
`COMPANY_BRAIN_WIKI_GIT_TOKEN`).

## HR — how it runs

The persistent HR manager checks monthly public-profile refreshes and daily archive
deadlines; departure state changes remain admin-confirmed.

```mermaid
flowchart TB
  subgraph signals [Departure signals]
    SL[Slack offboard_signal]
    WS[Workspace stub]
    NT[Notion stub]
  end
  signals --> SW[status_watch]
  SW -->|actionable ask| ADMIN[Admin Notifier]
  ADMIN -->|confirm| OC[offboard_confirm]
  OC -->|immediate| BR[bridge revoke + stop ingest]
  OC -->|departed_at| WA[wiki_archive]
  WA -->|T plus 30d| GH["GitHub archive/employee/member"]
  WA --> RM[Unmount employee_wiki tree]
  MGR[hr_manager] -->|monthly| LI[pull]
  LI --> BIO[bio.md UPDATE]
  LI --> VOICE[voice.md APPEND]
  MGR -->|daily due check| WA
```

## Managers

**`hr_manager.py`** — Persistent manager (polls on `hr.manager.poll_interval_minutes`).

- Monthly LinkedIn bio/voice pull for active members with `bindings.linkedin_url`.
- Daily check for departed members due for wiki archive (T+`archive_delay_days`).

## Specialists

| Agent | Schedule | Description |
|-------|----------|-------------|
| `hiring_log.py` | On HR events | Append `hr/hiring-log.md` (join / promote / depart; all employment types) |
| `employee_offboarding.py` | CLI / Slack signal | Proposal at `hr/offboard-proposal/{member}.md` (ask only) |
| `status_watch.py` | Via manager / CLI | Multi-signal deactivation → admin ask |
| `offboard_confirm.py` | Admin CLI | `status: departed`, bridge revoke, stop ingest, set `departed_at` |
| `wiki_archive.py` | Via manager (T+30) | Push `archive/employee/{member}` then unmount employee wiki tree |
| `linkedin/pull.py` | Monthly via manager | Public profile → `bio.md` / posts → `voice.md` via default web search (`lsearch`, Claude fallback) |
| `offboard_signal.py` (`operations/slack/`) | Slack `user_change` | Dispatches offboarding proposal when member deactivated |

### Roster vs members

| File | Who | Weave | Bridge |
|------|-----|-------|--------|
| `config/roster.yaml` | Trial, intern, contractor | Cannot invoke | N/A until promoted |
| `config/members.yaml` | W2 employees | Can invoke | Token + `bridge.departments` |

Department scope is recorded in both files. Employment-type ingest scopes remain
deferred.

**CLI:**

- `company-brain hr onboard --seed` — first run from `hr_seed.yaml`
- `company-brain hr onboard {member_key}` — new joiner (must exist in members/roster)
- `company-brain hr promote {roster_key}`
- `company-brain hr offboard {member_key}` — proposal only
- `company-brain hr confirm-offboard {member_key}` — admin actuation
- `company-brain hr manager [--once]`

Google Workspace and Notion deactivation remain detection/checklist-only. The
offboard proposal lists manual SaaS steps; 4r7a never deletes those accounts.

**Social profiles:** `config/hr.yaml` → `social_profiles[]`. Only `linkedin.pull`
is implemented; other platforms may be listed as stubs.

## Onboarding

**`hr_onboarding.py`** runs once for the initial seed or one new member, bootstraps
the employee wiki, appends the hiring log, optionally pulls LinkedIn, and hands off
to `hr_manager` with `get_runtime().start`.

## Deferred work

See [`docs/tabled.md`](../tabled.md) for employment-type ingest scopes, additional
social pullers, and inbound hiring automation. Workspace and Notion account deletion
are explicitly out of scope.
