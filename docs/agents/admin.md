# Admin department — agents

System-change intake via **Weave** (`@weave` Slack app), plus monthly **LLM ops**
maintenance (expense report + coding-session request). Wiki MD is source of truth;
Notion mirrors when configured.

## LLM ops — how it runs

Monthly maintenance period (default 1st at 09:00, `config/operations.yaml` → `admin.llm_ops`).
Persistent **`admin_manager`** dispatches two specialists in order.

```mermaid
flowchart TD
  AM[admin_manager] -->|1 expense| EXP[llm_expense_report]
  AM -->|2 maintain| MNT[admin_maintain]
  SPEC[ephemeral specialists] -->|usage + duration + verify| ST[(StateStore)]
  ST --> EXP
  ST --> MNT
  EXP -->|write_wiki_page| W1[admin/llm-expense/YYYY-MM.md]
  MNT -->|write_wiki_page| W2[admin/maintain/YYYY-MM.md]
  MNT -->|refresh| W3[admin/agent-runtime.md]
  MNT -->|actionable if drift| SL[#wiki-admin]
```

| Agent | Schedule | Description |
|-------|----------|-------------|
| `admin_manager.py` | Monthly (`admin.llm_ops`) | Dispatch expense then maintain |
| `llm_expense_report.py` | Via manager | Month spend by agent/category; verify + duration summary |
| `admin_maintain.py` | Via manager | Drift list + agent-runtime page; request admin coding session |

**CLI:** `company-brain admin manager`, `company-brain admin expense-report`, `company-brain admin maintain`

**Notify:** `#wiki-admin` actionable only on budget pressure, duration drift, or verify fail rates; quiet months stay silent.

**Tabled:** Monthly optimization scout — see `docs/tabled.md`.

---

## Weave — how it runs

```mermaid
flowchart LR
  M["@weave mention"] --> WT[weave_triage]
  WT --> MD["admin/change-request/id.md"]
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
