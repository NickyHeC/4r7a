# HR department — agents

Roster promotion and offboarding proposals. Actuation stays admin-confirmed in v1.

## Roster vs members

| File | Who | Weave | Bridge |
|------|-----|-------|--------|
| `config/roster.yaml` | Trial, intern, contractor | Cannot invoke | N/A until promoted |
| `config/members.yaml` | W2 employees | Can invoke | Token + `bridge.departments` |

## Agents

| Agent | Schedule | Description |
|-------|----------|-------------|
| `hiring_log.py` | On promote / HR events | Append `hr/hiring-log.md` |
| `employee_offboarding.py` | CLI / Slack signal | Proposal at `hr/offboard-proposal/{member}.md` |
| `offboard_signal.py` (`operations/slack/`) | Slack `user_change` | Dispatches offboarding proposal when member deactivated |

**CLI:** `company-brain hr promote {roster_key}`, `company-brain hr offboard {member_key}`

**Stubs (v1):** Google Workspace + Notion removal signals recorded on proposal; manual follow-up.

**Tabled:** Bridge token auto-revoke on offboard — after actuation ships (`docs/tabled.md`).
