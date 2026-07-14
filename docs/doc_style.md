# Documentation Style

How human-facing docs in this repo stay consistent. Agents update docs per
[`.cursor/rules/governance.mdc`](../.cursor/rules/governance.mdc).

## Doc layers

| Layer | Path | Audience | Content |
|-------|------|----------|---------|
| Pitch + map | `README.md` | Anyone | Why, data-flow diagram, department one-liners |
| Contributing | `CONTRIBUTING.md` | New contributors | Entry point → the two process docs below |
| Design process | `docs/design_process.md` | Extending the system (phase 1) | Concern debate → temporary plan file |
| Hygiene checklist | `docs/hygiene_checklist.md` | Extending the system (phase 2) | ruff, pytest, doctor, cleanliness, no-sus, CI |
| Runbooks | `docs/agents/*.md` | You + future hires | Per-agent tables, schedules, wiki paths |
| Handbook index | `docs/agents/README.md` | Navigation | Department table, shared conventions |
| Install | `project_install.md` | Admin connecting platforms | OAuth, env, onboarding commands |
| Plans | `docs/plans/*.md` | Design + build session only | **Delete after ship** when handbooks updated |
| Backlog | `docs/tabled.md` | Planning phase | Deferred features; remove row when shipped |
| Memory | `memory.md` | AI + you | Reverse-chronological decision log |
| Rules | `.cursor/rules/*.mdc` | AI | Always-on invariants agents must enforce |

**Rule:** Steady-state truth lives in handbooks + `memory.md`. Plans are **temporary** —
delete after build completes and outcomes are folded into handbooks. Each fact lives in
exactly one layer; other layers link to it rather than restating it.

## Design and build process

The full extend-the-system loop is two docs: design in
[`design_process.md`](design_process.md), then build/test/clean in
[`hygiene_checklist.md`](hygiene_checklist.md). This file only covers how the resulting
docs are **formatted**.

## Handbook page template

Each `docs/agents/<department>.md` file:

1. **Title + one-line scope**
2. **Config links** (`config/*.yaml`, key env vars)
3. **How it runs** — heading `## {Platform} — how it runs`, then one short summary
   paragraph, then the mermaid diagram; onboarding agents stay out of the diagram
4. **Manager(s)** — short table or bullet list
5. **Specialists** — table:

   | Agent | Schedule | Description |

   Per-agent detail blocks (when non-obvious):

   | | |
   |---|---|
   | **State** | persistent / ephemeral |
   | **Schedule** | … |
   | **Source** | … |
   | **Destination** | `wiki/path.md` |
   | **Notion** | Page title (= MD title) |
   | **Write mode** | update / append |

6. **Onboarding** — last in platform section (prose only; not in flow diagrams)
7. **Deferred work** — one link to `docs/tabled.md` (no local backlog tables)

## Naming in docs

- Agent filenames: `` `open_pr.py` `` (code)
- Wiki paths: `` `engineering/github/open-pr.md` `` (kebab slug)
- Notion titles: **Open PRs** (Title Case, may be longer than slug)
- See [`.cursor/rules/naming.mdc`](../.cursor/rules/naming.mdc)

## Diagrams

- Use **mermaid** for steady-state flows with 3+ nodes or branches
- **One diagram per major section** — summary paragraph first under `## … — how it runs`,
  then mermaid; no duplicate ascii + mermaid of the same flow
- **Exclude onboarding agents** — graphs show regular operation after setup (managers,
  persistent loops, dispatch). Onboarding is documented in prose below the diagram.
- Label edges with dispatch triggers (`08:00`, `on demand`, `via manager`)
- Use **ascii** only for simple linear pipelines in README if mermaid is overkill

## Prose

- **Tables for agent specs; short prose; link to code/config for detail** rather than
  restating it. Deferred work links to `docs/tabled.md` — no long "Not yet built" lists
  in handbooks.

## `memory.md` entries

```markdown
## YYYY-MM-DD — Short title (working tree | commit)

- **What:** one-line summary
- **Key changes:** bullet list (paths, agents, config)
- **Tests:** N passing / doctor status if relevant
```

Newest on top. Read `memory.md` first when starting a session.

## When to update what

| Change | memory | handbook | README | project_install | tabled |
|--------|--------|----------|--------|-----------------|--------|
| New agent | ✓ | ✓ | if new dept/platform | if connect step | |
| Rename paths | ✓ | ✓ | | | |
| Defer feature | ✓ | | | | ✓ |
| Ship tabled item | ✓ | ✓ | maybe | maybe | remove row |
| Convention / rule | ✓ | | | | |
