# Admin department — agents

System-change intake via **Weave** (`@weave` Slack app). Wiki MD is source of truth;
Notion change-request database mirrors when configured.

## Weave — how it runs

```mermaid
flowchart LR
  M[@weave mention] --> WT[weave_triage]
  WT --> MD[admin/change-request/id.md]
  MD --> NDB[Notion change-request DB]
  WT -->|config_only + W2 member| WV[weave]
  WT -->|agent_behavior / security_ingest| WAIT[await admin approve in Notion]
  WAIT -->|poll-approvals| WV
  WV --> PR[draft GitHub PR]
```

| Agent | Schedule | Description |
|-------|----------|-------------|
| `weave_triage.py` | `@weave` mention (Weave Events) | Classify change class; write change-request MD + Notion row |
| `weave.py` | On approval / auto `config_only` | Draft PR + optional VM sandbox verify |

**CLI:** `company-brain weave events`, `company-brain weave poll-approvals`

**Auth:** Active `members.yaml` W2 only — `config/roster.yaml` cannot invoke Weave.

**Change classes:** `config_only` (auto PR for W2), `agent_behavior`, `security_ingest`
(admin Notion approval via `weave poll-approvals`).

Config: `config/notion.yaml` → `change_request_database`; `config/operations.yaml` → `slack_platform.weave`.

**Tabled:** Weave hot-reload / agent pause-resume (option B) — see `docs/tabled.md`.
