# Design before build

How to spec a new feature or platform in company-brain **before** writing production
code. Used for Slack, Notion, Discord, and similar “whole platform” builds.

**Agents:** when the user starts designing something new, follow this process end to
end. Do not implement until design is settled and the user explicitly starts a build
session.

**Humans:** kick off with a vision doc (often `notepad.md`) and tell the agent to
use this file.

Related: [`.cursor/rules/solo-maintainer.mdc`](../.cursor/rules/solo-maintainer.mdc) §0,
[`doc-style.md`](doc-style.md) (design sessions), [`tabled.md`](tabled.md) (backlog).

---

## Kickoff (human → agent)

Point at the vision and set weight:

```text
@notepad.md:3-20

This is a build as important as [Slack / Notion / …].
Proceed with our usual planning process — see docs/design_before_build.md.
```

Add a **presentation mode** (default if omitted: **batch**):

| Mode | Agent presents | Human replies |
|------|----------------|---------------|
| **one-by-one** | Exactly **one** concern per message | Answer each before the next |
| **batch** *(default)* | Up to **3** numbered concerns per round | Answer in batches; may skip obvious ones |
| **all-at-once** | **All** concerns in the first planning message | Answer in any order, one or more messages |

**Interaction:** plain text only — no IDE multiple-choice widgets unless the human asks.

---

## Phase 1 — Research (agent, before debating)

Read and summarize briefly:

1. **Vision** — kickoff doc / notepad / issue
2. **`docs/tabled.md`** — deferred rows for this department or platform; which belong in *this* plan vs stay deferred
3. **`memory.md`** — recent decisions and architecture context
4. **Current code** — what exists; gap vs vision
5. **Neighbors** — similar platforms (managers, specialists, sync, notify patterns under `src/company_brain/agents/`)
6. **Rules** — relevant `.cursor/rules/` (agent-organization, agent-construction, wiki-data-flow, access-control, platform-boundary, naming)

Open with a short framing paragraph: why this matters, what shifts, and which tabled items to decide now.

---

## Phase 2 — Design debate (2–3 rounds typical)

### Concern format

```markdown
### Concern N — Short title

- **Context:** what exists / what was asked for
- **Tension:** the decision or risk
- **Proposal:** recommended default (1–2 alternatives only if the fork is real)
```

### Agent rules

- **Proactive** — surface issues, clarifications, improvements; do not wait to be asked
- **Concrete** — cite files, agents, config keys, invariants
- **Platform boundary** — if the connected platform already owns a behavior, integrate or surface a gap; do not reimplement without explicit approval ([`platform-boundary.mdc`](../.cursor/rules/platform-boundary.mdc))
- **Tabled items** — for each relevant row: *include in v1 or still defer?*
- **Answer when you can** — if the codebase already settles a concern, say so and mark it settled; do not invent work
- **Rule drift** — if the request conflicts with a rule:

  > **Rule drift:** `<rule>` — `<what violates it>` — suggest fix or ask to update the rule

### After each human reply

1. Record settlements under **Settled this round** (bullets)
2. Carry unsettled concerns forward
3. Do not re-litigate settled items unless the human reopens them

---

## Phase 3 — Lock scope → plan file

When concerns are resolved (or only minor defaults remain), write
**`docs/plans/<topic>.md`** with:

1. **Weight** — why this build matters
2. **Settled decisions** — grouped by theme (data contract, UX, access, scheduling, …)
3. **Architecture** — manager(s), specialists, config touchpoints
4. **Steady-state flow** — one mermaid diagram under `## {Platform} — how it runs` (no onboarding in the diagram)
5. **Ship order** — numbered **build sessions** (small, reviewable slices)
6. **Per session** — files to touch, tests, doc updates
7. **Deferred** — what stays in `docs/tabled.md` and why
8. **Post-ship checklist** — handbook, `README.md`, `project_install.md`, `memory.md`, remove shipped tabled rows, **delete this plan file**

Minor implementation defaults may be baked in without asking when they follow directly from settled decisions.

End planning with:

> Scope locked. Say **Session 1** (or name a slice) when you want to build.

Plans are **temporary** — see [`doc-style.md`](doc-style.md).

---

## Phase 4 — Build (only after human says go)

- **One ship unit per thread** when possible (one plan session or one agent slice)
- Follow session order in the plan unless redirected
- Match repo conventions (department → platform → agents, naming, SDK choice, notify gates, MD-first writes)
- After each session: `ruff check .`, `pytest -q`, `company-brain doctor code` when applicable
- **After full ship:** update `docs/agents/<dept>.md`, `memory.md`, `project_install.md` as needed; remove shipped rows from `docs/tabled.md`; delete `docs/plans/<topic>.md`

---

## Concern checklist (adapt per feature)

Not every item applies; use as a scan list when drafting concerns:

- [ ] Source of truth / write path / human override policy
- [ ] Read path / ACL / who sees what
- [ ] Manager vs specialist split and schedules
- [ ] Onboarding vs steady-state (onboarding one-time; excluded from flow diagrams)
- [ ] Notifications — silent vs actionable (`company_brain.notify`)
- [ ] Cost gates / when to skip a run
- [ ] Conflict or review queues vs auto-resolve
- [ ] Config surface (`config/*.yaml`, env vars, `Smolfile` allow_hosts)
- [ ] v1 ship order — explicit out-of-scope
- [ ] Extend existing agent vs new file
- [ ] Wiki path, article title, agent filename ([`naming.mdc`](../.cursor/rules/naming.mdc))

---

## Example kickoffs

**Batch (Notion-style):**

```text
@notepad.md:3-20 — build as important as Slack.
Usual planning per docs/design_before_build.md. Batch mode (3 per round). Plain text only.
```

**One-by-one:**

```text
Same vision. One concern at a time. Do not advance until I answer.
```

**All-at-once:**

```text
Same vision. Raise all concerns in your first message. I will reply in batches.
```

---

## Reference builds

| Platform | Plan (deleted after ship) | Pattern |
|----------|---------------------------|---------|
| Notion | `docs/plans/notion.md` | MD SoT + bidirectional sync; 9 build sessions; batch-of-3 rounds |
| Discord | `docs/plans/discord.md` | New `growth/` department; Gateway ingest; multi-round design |
| Slack | (earlier sessions) | Manager + specialists; ingest tiers; `@wiki` |

When in doubt, read `memory.md` for how a similar platform was shipped.
