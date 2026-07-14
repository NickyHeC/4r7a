# Design process (phase 1 of 2)

How to iron out a new feature or platform in company-brain **before** any code is
written. This is the first half of the extend-the-system loop:

> **design_process.md** (agree scope) → **[hygiene_checklist.md](hygiene_checklist.md)** (build, test, clean)

**Who this is for:** anyone extending 4r7a with an AI coding agent — you do not need to
be the original maintainer or a strong prompter. Point your agent at this file and it
knows how to run the whole design debate for you.

**The one rule of phase 1:** no production code until scope is settled and you explicitly
start a build. The agent's job here is to *disagree well* — surface concerns, propose
defaults, and record decisions — not to start typing.

---

## How to start (copy-paste)

Write a short **vision** first (a few lines is fine — a paragraph in `notepad.md`, a
GitHub issue, or just the chat). Then tell the agent:

```text
[link or paste your vision]

Design a new [feature / platform] for 4r7a. Follow docs/design_process.md.
Presentation mode: batch.   # or: one-by-one / all-at-once
```

### Choose how concerns are presented

People differ: some want to think about one question at a time, others want every
open question up front. Pick the mode that fits you (default: **batch**).

| Mode | Agent presents | You reply |
|------|----------------|-----------|
| **one-by-one** | Exactly **one** concern per message; waits for you | Answer each before the next |
| **batch** *(default)* | Up to **3** numbered concerns per round | Answer in batches; skip the obvious ones |
| **all-at-once** | **Every** concern it can find in the first message | Answer in any order, across one or more replies |

**Interaction style:** plain text back-and-forth. Ask the agent not to use IDE
multiple-choice popups unless you want them.

---

## Phase 1 — Research (agent does this before debating)

The agent reads and briefly summarizes:

1. **Your vision** — the doc / issue / chat that kicked this off
2. **[`docs/tabled.md`](tabled.md)** — deferred work for this area; which rows belong in *this* build vs stay deferred
3. **`memory.md`** — recent decisions and how similar platforms were shipped
4. **Current code** — what already exists; the gap versus your vision
5. **Neighbors** — similar platforms under `src/company_brain/agents/` (managers, specialists, sync, notify patterns to copy)
6. **Invariants** — the relevant [`.cursor/rules/`](../.cursor/rules) (agent-organization, agent-construction, wiki-data-flow, access-control, platform-boundary, naming)

It opens with a short framing paragraph: why this matters, what shifts, and which
tabled items to decide now.

---

## Phase 2 — Design debate (2–3 rounds is typical)

Each concern uses this shape:

```markdown
### Concern N — Short title

- **Context:** what exists / what you asked for
- **Tension:** the decision or risk
- **Proposal:** the agent's recommended default (1–2 alternatives only if the fork is real)
```

**What the agent should do:**

- **Be proactive** — raise issues, clarifications, and improvements without being asked
- **Be concrete** — cite files, agents, config keys, and invariants
- **Respect platform boundaries** — if a connected platform already owns a behavior, integrate or note the gap; do not reimplement it without your explicit OK ([`platform-boundary.mdc`](../.cursor/rules/platform-boundary.mdc))
- **Decide tabled items** — for each relevant row: *include in v1 or still defer?*
- **Answer what the code already answers** — if the repo settles a concern, say so and move on; do not invent work
- **Flag rule drift** — if your request conflicts with an invariant:

  > **Rule drift:** `<rule>` — `<what violates it>` — suggest a fix, or ask to change the rule if the conflict is intentional

**After each of your replies**, the agent:

1. Records decisions under a **Settled this round** list
2. Carries unsettled concerns into the next round
3. Does not re-open settled items unless you do

### Concern checklist (agent's scan list — adapt per feature)

Not every item applies; used to make sure nothing obvious is missed:

- [ ] Source of truth / write path / human-override policy
- [ ] Read path / access control / who sees what
- [ ] Manager vs specialist split and schedules
- [ ] Onboarding vs steady-state (onboarding is one-time; excluded from flow diagrams)
- [ ] Notifications — silent vs actionable (`company_brain.notify`)
- [ ] Cost gates / when a run should skip itself
- [ ] Conflict or review queues vs auto-resolve
- [ ] Config surface (`config/*.yaml`, env vars, `Smolfile` allow_hosts)
- [ ] v1 ship order and explicit out-of-scope
- [ ] Extend an existing agent vs add a new file
- [ ] Wiki path, article title, agent filename ([`naming.mdc`](../.cursor/rules/naming.mdc))

---

## Phase 3 — Lock scope → write the plan file

When concerns are resolved (or only minor defaults remain), the agent writes
**`docs/plans/<topic>.md`** — a temporary build script containing:

1. **Weight** — why this build matters
2. **Settled decisions** — grouped by theme (data contract, UX, access, scheduling, …)
3. **Architecture** — manager(s), specialists, config touchpoints
4. **Steady-state flow** — one mermaid diagram under `## {Platform} — how it runs` (no onboarding in the diagram — see [`doc_style.md`](doc_style.md))
5. **Ship order** — numbered **build sessions**, each a small reviewable slice
6. **Per session** — files to touch, tests, doc updates
7. **Deferred** — what stays in [`docs/tabled.md`](tabled.md) and why

The agent may bake in minor implementation defaults that follow directly from settled
decisions, without re-asking.

Planning ends with:

> Scope locked. Say **Session 1** (or name a slice) to start building.

Plans are **temporary** and deleted after the build ships (see [`doc_style.md`](doc_style.md)).

---

## Phase 4 — Handoff to build

Building happens one **ship unit per thread** (one plan session or one agent slice),
following the plan's session order. For the mechanics of building, testing, and
cleaning each slice — the fix loop, doctor checks, pre-ship gate, and post-feature
hygiene — follow **[`hygiene_checklist.md`](hygiene_checklist.md)**.

After the full build ships, the plan file is deleted and its outcomes are folded into
the steady-state docs (handbook, `memory.md`, `README.md`, `project_install.md`), with
shipped rows removed from [`docs/tabled.md`](tabled.md) and any new deferrals added —
per the "when to update what" table in [`doc_style.md`](doc_style.md).

---

## Example kickoffs

**Batch (how the Notion platform was designed):**

```text
[vision] — a build as important as our Slack integration.
Design it per docs/design_process.md. Batch mode, plain text.
```

**One-by-one:**

```text
Same vision. One concern at a time; don't advance until I answer.
```

**All-at-once:**

```text
Same vision. Raise every concern in your first message; I'll reply in batches.
```

---

## Reference builds

Real designs that used this process (plan files were deleted after ship; the outcomes
live in the handbooks and `memory.md`):

| Platform | Pattern |
|----------|---------|
| Notion | MD source-of-truth + bidirectional sync; 9 build sessions; batch-of-3 rounds |
| Discord | New `growth/` department; Gateway ingest; multi-round design |
| Slack | Manager + specialists; ingest tiers; `@wiki` |

When in doubt, read `memory.md` for how a similar platform was shipped.
