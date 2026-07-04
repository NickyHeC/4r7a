---
name: no-sus-agent-doctor
description: >-
  Strict self-audit for agent-authored company-brain changes before commit or PR.
  Use when the user says strict review, no sus, ship this, quality doctor, or
  prove this works; or before shipping auth, billing, Gmail actuation, receipt
  routing, onboarding, or security-sensitive agent changes.
---

# No-Sus Agent Doctor

Score the diff 0–100. Ship only at **100** (no fail blockers, no unproven claims).

## Source order

When rules conflict, **record the conflict** — do not silently pick the convenient rule.

1. `.cursor/rules/*.mdc` (especially `agent-eval`, `agent-runtime`, `wiki-data-flow`, `platform-boundary`)
2. `docs/agents/<department>.md` + `project_install.md`
3. `memory.md` (recent entries only)
4. Platform docs (Granola, Gmail, Ramp MCP, etc.)

## Workflow

1. **State the invariant** — one sentence (e.g. "Receipts reach Ramp inbox; Ramp documents").
2. **Freeze scope** — minimum diff; no drive-by refactors.
3. **Map ownership** — which platform owns each behavior (`platform-boundary.mdc`).
4. **Smell-scan** — fallbacks, generic catches, duplication, bypasses (list below).
5. **Read diff linearly** — file by file.
6. **Prove** — run checks in order:
   - `ruff check .`
   - `pytest` (targeted tests for touched modules; full suite if small)
   - `company-brain doctor all` (or `agents` / `wiki` / `ops` for scoped changes)
   - `company-brain doctor connect` if env/platform connection changed
7. **Fix fails serially** — one blocker, re-run proof, revert on failure.
8. **Batch warnings** — apply warn-class fixes together, re-run once.
9. **Re-score** until 100 or document accepted debt in the PR/test plan.

## Hard blockers

- Hidden fallback or best-effort path that looks like success
- **Platform duplication** — reimplementing Ramp/Gmail/Notion/Granola features they already own
- Generic `except Exception` on actuation (Gmail insert, calendar book, wiki publish, receipt forward) without logging + surfaced failure
- **Notifier bypass** — new `chat_postMessage` or raw Slack in agents (use `operations_slack` / `from_finance_config`)
- **Wiki bypass** — writing Notion or wiki MD outside `write_wiki_page` / publish path
- **Runtime bypass** — manager dispatching specialists via `.execute()` instead of `get_runtime().run()` (onboarding backfill excepted)
- Gmail **send** without dual opt-in (`gmail.allow_send` + `GMAIL_ALLOW_SEND`)
- Finance **writes at source** (Mercury/Ramp mutations)
- New external API host without `vmspec.toml` `allow_hosts` entry
- New agent file without handbook + README + `project_install` update
- PR or summary claims behavior **without test or doctor proof**
- Multiple sources of truth for one decision

## Warnings (fix or justify)

- Duplicate helpers across agent files (extract to `shared/`)
- Missing module docstring / SDK choice in new agent
- `ensure_*` creating state outside the owning subsystem
- Opportunistic retries/sleeps masking ordering bugs
- Weak test names (prefer invariant names: `test_forward_skips_external_domain`)

## Scoring

Use the same formula as `company-brain doctor`:

```
score = 100 − 1.5 × (unique fail rules) − 0.75 × (unique warn rules)
```

Unique rules only — 200 occurrences of one smell = one hit.

## Output template

```markdown
## No-sus audit — <branch or topic>

**Invariant:** …
**Score:** …/100

### Blockers
- [ ] …

### Warnings
- …

### Proof
- [ ] ruff check .
- [ ] pytest …
- [ ] company-brain doctor …
```
