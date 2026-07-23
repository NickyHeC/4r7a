# Tabled Features

Canonical backlog of **deferred** work — features specced or discussed but not built.
The agent reads this file when starting work in a matching department/platform.

**2026-07 tabled revisit (sessions A–L):** shipped and folded into handbooks /
`memory.md`; plan file removed. Remaining rows below are still deferred.

**Not here:** intentional out-of-scope items in README (nudge/chase agents).
**Scratch pad:** `notepad.md` (migrate rows here when a deferral is real).

Format for new rows:

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|

---

## Explicitly out of scope / removed

Won’t build unless product explicitly reverses:

- In-wiki versioning + rollback agents (GitHub via `wiki_commit` is enough; volume restore stays manual admin)
- Bidirectional GitHub ↔ wiki **content** sync (wiki edits via CLI/agents only)
- Bookface API, X/Twitter write API, Luma/Partiful integrations
- Full Ramp receipt cross-check (platform boundary)
- Per-page Notion ACL automation, cross-member comparative query, auto-promote employee → company wiki
- Workspace / Notion **account deletion** from 4r7a (manual checklist only)
- Customer newsletter Gmail draft (wiki MD draft only; delivery channel TBD below)

---

## Cross-cutting / runtime

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Weave coding beyond allow-list / auto-merge | admin/weave | Real use + explicit product ask | Draft PR + no auto-merge stays |
| Latent Briefing (KV cache handoff) | LLM / runtime | Self-hosted GLM-5 / Kimi (or equiv.) | Needs internal KV access — not hosted API-only |
| Semantic / embedding hybrid search | wiki + `@wiki` + bridge | Lexical retrieve inadequate in practice | **Shipped v1:** TF+IDF+title+age in `wiki/retrieve.py` |
| Live custom-source query plugins | ingest / `@wiki` | After scheduled ingest connectors prove useful | Connectors remain ingest-only; live query stays here |
| Cloud builder maintenance loop | runtime | Multi-VM fleet real | Self-heal v1 queues / optional draft PR shipped; builder loop stays deferred |
| Admin console SPA / public expose | `admin_console` | Product ask after private-mesh HTMX limits | Stay Tailscale / private mesh |

---

## Bridge (member MCP)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Local → cloud bridge migration | Admin / bridge | First NAS → cloud VM move | rsync, re-issue tokens, URL change |
| Senior `propose_practice_update` via MCP | Engineering / bridge | Read-only bridge stable | Tabled |

---

## Employee wiki / Notion sync

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Notion ↔ employee wiki sync (all) | `employee_wiki` | Explicit product ask | Includes Notion→MD write-back; tabled as a block (2026-07 debate) |
| Work logs in Notion | `employee_wiki` | When admin wants Notion mirror of work-log | Depends on employee Notion pull |

---

## Growth / Ads

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Google Ads mutates / recommendation apply | `growth/google_ads` | Explicit write approval | v1 read-only snapshots |
| Google Ads product-true CPA | `growth/google_ads` | Eng + Ads conversion setup | v1 uses Ads-reported CPA only |
| Google Ads keyword / Smart Bidding tools | `growth/google_ads` | Ads config session | |

---

## Product / PostHog / billing

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Richer PostHog agents (replay, retention, persons) | `product/posthog` | Heavy PostHog use | v1: audit, usage, experiments, signup funnel |
| PostHog write-back (flags/experiments) | `product/posthog` | Explicit write approval | v1 read-only private REST |
| Daily experiment watch | `product/posthog` | Weekly cadence too slow | |
| Auto-sync feature↔event naming contract | `product/posthog` | Eng naming conventions stable | v1 heuristic vs `product/feature.md` |
| Company admin API analytics | `product/admin_api` | Concrete API + env contract | Yaml stub only |
| Billing / margin provider | `product/billing` | Provider API chosen | Yaml stub only |
| Customer newsletter delivery | `product/update` | Delivery channel chosen | Wiki MD draft only; no Gmail/ESP until decided |

---

## HR

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Roster scopes by employment type | `hr` / `config/roster.yaml` | Explicit product ask | Department scope shipped |
| Hiring log auto-track (inbound) | `hr` or `operations/gmail` | CRM inbound stable | Manual/seed + LinkedIn bio shipped |
| Additional social pullers | `hr` | Per-platform WebSearch puller | `hr.social_profiles[]` stub shipped; LinkedIn only implemented |

---

## External wiki (v2)

| Item | Department / platform | Trigger to build | Notes |
|------|----------------------|------------------|-------|
| Live sync / bidirectional pull | `external_wiki` | v2 explicit scope | v1 remains one-shot, including personal sources |
| Member-initiated mounts | `external_wiki` | Policy decision | Admin-only; members submit zip for review |
| Cryptographic provenance | `external_wiki` | Compliance ask | Provenance frontmatter today |
