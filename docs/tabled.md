# Tabled Features

Canonical backlog of **deferred** work — features specced or discussed but not built.
The agent reads this file when starting work in a matching department/platform.

**Not here:** intentional out-of-scope items in README (nudge/chase agents).  
**Scratch pad:** `notepad.md` (migrate rows here when a deferral is real).

Format for new rows:

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|

---

## Cross-cutting

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Versioning + rollback | Wiki | Security-sensitive write volume justifies it | Listed in `access-control.mdc` Pending |
| Batch absorb by urgency | operations/slack + notion | Slack/Notion agent design session | Split immediate (tasks/platforms) vs deferred (informational); keep current absorb schedules until then |
| LLM eval harness | All | First tier downgrade in prod or quality drift | **Concept only** (this row): fixtures under `tests/fixtures/llm/<agent>/`, golden outputs, future `eval-model <agent> --tier <t>` CLI, quality gate on downgrades; not built |
| Token budget usage tracking | All | Admin enables `token_budget.enabled` | **1)** Hook API response token counts (primary). **2)** Fallback: finance `card_spend` pulls Anthropic/OpenAI vendor bills monthly |
| Ingest existing / personal wikis | External wiki + employee wiki | Admin mount flow stable | Use `migrate-names` on import; see external wiki plan |
| AI pages too long → unread | All writers | Absorb/handbook quality pass | Length targets in absorb prompt + `config/wiki.yaml`; anti-cram split ongoing |

---

## 4r7a onboarding (new admin / member deploy)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Platform connection order | Admin / `project_install.md` | Almost all platforms specced | Canonical connect sequence for new installs; ties stacks together last |
| Quarterly doc pass | Admin / docs | First multi-member deploy or major release | Handbooks vs code paths, `migrate-names`, trim stale plans |

---

## Employee wiki

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Notion → MD write-back | `employee_wiki` | Members edit in Notion regularly | Phase I in employee wiki plan |
| Per-page Notion ACL automation | `employee_wiki` | Beyond personal teamspace + manual share | Sharing stays in Notion UI for v1 |
| Cross-member comparative query | `employee_wiki` | Explicit product ask only | Evaluation territory; citation-only per-member in v1 |
| Auto-promote employee → company wiki | `employee_wiki` | Never without employee submit + admin gate | Materializer ≠ company promotion |
| Citation-only query UI | `employee_wiki` | Manager query workflow defined | Offboarding path TBD |

---

## Operations — Gmail

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| `security_triage` | `operations/gmail` | First auth-alert / wire-transfer incident | Never auto-archive; alert channel |
| Warm intro classifier | `operations/gmail` | EA profile + confident heuristic | Confident cases only |
| `inbox_task` archive on Linear Done | `engineering/linear` | Linear completion flow stable | Not gmail sweep |
| ~~`partnership_inbound` specialist~~ | — | — | **In progress:** `docs/plans/crm-redesign.md` (unified inbound + entity CRM) |
| Full Ramp receipt cross-check | — | **Do not build** unless explicit approval | Platform boundary; router only |

---

## Operations — Slack

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| **Overall agent scheduling design** | operations/slack (+ fleet-wide) | **Slack platform agent build session** | Revisit work-ahead windows, manager cadence, weekend/overnight runs on always-on fleet, batch LLM timing, two-phase verify; `work_ahead.py` + Linear stale audit are v1 only |
| Agent filename rename pass | `operations/slack` | Slack platform build / spec session | `slack_action_items` → `action_items`, `slack_thread_watcher` → `thread_watcher`; naming doctor warns until then |
| Internal meeting scheduler | `operations/slack` | Slack scheduling pain | Distinct from gcal ext_meeting_scheduler |
| Open threads pending response | `operations/slack` | Watcher + action-item flow proven | Extend `slack_thread_watcher` |
| Feedback intake | `operations/slack` | Ops channel for system feedback | Route to wiki or Linear |
| Question the wiki | `operations/slack` | Query UX defined | Read-only; wiki store only |

---

## Operations — Notion

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Conflict resolution / source of truth | `operations/notion` | Multi-DB task sync in production | MD wins; Notion mirrors |
| Feedback & system modification intake | `operations/notion` | Builder dispatch pattern | Meta: dispatch builder agent |
| Human-added pages ingest | `operations/notion` | Notion-first teams | Pull → MD path TBD |
| Version control | Wiki | Same as cross-cutting versioning | |
| Sign-in / account management | Product | Multi-member deploy | Admin vs member model exists |
| Work logs in Notion | `employee_wiki` | Employee wiki Notion pull built | |
| Investor newsletter drafting | Growth / Gmail | Content pipeline exists | |

---

## Operations — other

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| `employee_offboarding` | Cross | Member offboarding runbook | Revoke ingest, archive building |
| Bookface integration | Growth | Platform connected | Department TBD |

---

## Growth / marketing platforms

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Google Ads agent | `growth/google_ads` | Ads account connected | |
| Company activity agent | Growth | Event sources defined | |
| Discord | Community | Discord bot scope defined | |
| X / Twitter | Growth | API access | |

---

## HR

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Hiring log auto-track | `hr` or `operations/gmail` | Recruiting inbound stable | Extend `recruiting_inbound` |

---

## External wiki (v1 gaps)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Live sync / bidirectional pull | `external_wiki` | v2 explicit scope | v1 is one-shot mount |
| Member-initiated mounts | `external_wiki` | Policy decision | Admin-only in v1 |
| Cryptographic provenance | `external_wiki` | Compliance ask | Provenance frontmatter today |

---

## Wiki operators (future)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Wiki-level operators | Admin | Catalog + mount stable | Cross-building maintenance agents |
