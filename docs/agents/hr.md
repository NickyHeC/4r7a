# HR department — agents

Roster promotion and offboarding proposals. Actuation stays admin-confirmed in v1.

| Agent | Schedule | Description |
|-------|----------|-------------|
| `hiring_log.py` | On promote / HR events | Append `hr/hiring-log.md` |
| `employee_offboarding.py` | CLI / Slack signal | Proposal at `hr/offboard-proposal/{member}.md` |

**CLI:** `company-brain hr promote {roster_key}`, `company-brain hr offboard {member_key}`

**Roster:** `config/roster.yaml` — non-W2; promote moves entry to `members.yaml`.

**Stubs (v1):** Google Workspace + Notion removal signals recorded on proposal; manual follow-up.
