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
| Batch absorb by urgency | operations/slack + notion | Optional `--absorb` on Slack onboarding | Three-tier lanes shipped; encyclopedia absorb opt-in at backfill |
| Weave hot-reload / agent pause-resume | admin/weave | Weave PR-only v1 stable | Option B from Slack design — pause persistent agents, edit, resume; after structure ships |
| Ramp LLM vendor reconcile | Finance / LLM | Ramp MCP stable in reconcile path | Mercury card vendor bills wired; add Ramp card txns to `llm/reconcile.py` |
| Process artifacts (Architect/Doer) | Cross | Agents living on cloud VMs | Compile reusable Processes (steps, inputs, temporal deps) from observed workflows; second-order automation per Ramp Labs |
| Self-maintaining monitor-driven ops | Cross / runtime | Agents living on cloud VMs | PR-merge monitor generation, alert → sandbox reproduce → propose fix; includes cloud builder agent maintenance loop |
| Latent Briefing (KV cache handoff) | LLM / runtime | Self-hosted GLM-5 (`COMPANY_BRAIN_LLM_PROVIDER=glm`) | Ramp Labs multi-agent memory compaction; needs internal KV access — not for hosted API-only |
| Review queue UX for actionable outputs | operations/notion | Accounting/CRM promotions follow-on | Stale review shipped (Session 6); drafts/accounting/CRM promotions still deferred |
| Ingest existing / personal wikis | External wiki + employee wiki | Admin mount flow stable | Use `migrate-names` on import; see external wiki plan |
| AI pages too long → unread | All writers | Absorb/handbook quality pass | Length targets in absorb prompt + `config/wiki.yaml`; anti-cram split ongoing |

---

## Admin / LLM ops

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Monthly optimization scout | `admin/` | After monthly LLM expense + admin maintain agents ship | Walks system + human behavior signals; proposes workflow optimizations for the admin coding session. Expense report + maintain/session-request agents are **in** the telemetry plan (same monthly period, two agents) — this scout stays deferred |

---

## 4r7a onboarding (new admin / member deploy)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Member bridge MCP | Cross / `bridge/` | First multi-member deploy using coding agents | Co-located with wiki; private mesh; token hashes; ledger → `bridge_manager` → materializer → rollup 08:00; **no Linear**; per-dept bridge index; skills `_index.yaml` per dept; rate limits 60 reads/min + 20 report/day; **read: dept-scoped** — `bridge.departments` required; engineering uses `sync: location:engineering`; `sync: company` only for cross-dept pages (master table); own employee tree; `bridge_readiness` doctor |
| Bridge setup in `project_install.md` | Admin onboarding | Bridge MCP implementation lands | After employee wiki onboarding; Tailscale; `company-brain bridge issue-token`; env-var token in Cursor |
| Bridge token revoke on offboard | operations/slack | Offboard actuation ships | `employee_offboarding` proposal exists; auto-revoke after actuation |
| Local → cloud bridge migration | Admin / bridge | First NAS → cloud VM move | Tabled — rsync, re-issue tokens, URL change |
| Senior `propose_practice_update` via MCP | Engineering / bridge | Read-only bridge stable | Tabled |
| Human vs agent Notion/MD sync lag | Bridge / Notion | Bridge MCP ships | Signature-gated bidirectional sync shipped; bridge citation lag TBD |
| Platform connection order | Admin / `project_install.md` | Almost all platforms specced | Canonical connect sequence for new installs; ties stacks together last |
| Process mining from Loom (evolving agents) | Admin onboarding | Last part of 4r7a onboarding | Observe how admin actually works; suggest/write agents that evolve with behavior — needs design time before build |
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
| Full Ramp receipt cross-check | — | **Do not build** unless explicit approval | Platform boundary; router only |

---

## Operations — Slack

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
## Operations — Notion

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Product progress page (Notion) | `operations/notion` + `product/` | Product asks | Mirror catalog + roadmap; Discord feature dedup v2 |
| Review queue UX for actionable outputs | `operations/notion` | Accounting/CRM promotions follow-on | Stale review shipped; drafts/accounting proposals still deferred |
| Human-added pages ingest | `operations/notion` | Broader ingest polish | Onboarding ingest shipped; live orphan discovery still TBD |
| Version control | Wiki | Same as cross-cutting versioning | |
| Sign-in / account management | Product | Multi-member deploy | Admin vs member model exists |
| Work logs in Notion | `employee_wiki` | Employee wiki Notion pull built | |
| Investor newsletter drafting | Growth / Gmail | Content pipeline exists | |

---

## Operations — other

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Bridge token revoke on offboard | hr / bridge | Offboard actuation ships | Proposal agent exists; auto-revoke tabled |
| Bookface integration | Growth | Platform connected | Department TBD |

---

## Growth / marketing platforms

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Google Ads agent | `growth/google_ads` | Ads account connected | |
| Company activity agent | Growth | Event sources defined | |
| X / Twitter | Growth | API access | |

---

## HR

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Roster scopes by employment type | `hr` / `config/roster.yaml` | HR design session | Roster + promote shipped; per-type scopes TBD |
| Google Workspace offboard signal | `hr` | Full Workspace API integration | v1 stub on offboard proposal |
| Notion user removal signal | `hr` | Notion admin API integration | v1 stub on offboard proposal |
| Hiring log auto-track (inbound) | `hr` or `operations/gmail` | CRM inbound stable | Extend **`inbound_crm`** candidate type |

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
