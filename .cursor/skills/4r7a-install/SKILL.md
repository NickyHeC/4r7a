---
name: 4r7a-install
description: >-
  Guided first-run install of company-brain (4r7a) for an admin and their coding
  agent. Use when installing or re-scoping 4r7a, compiling install decisions,
  gathering credentials, validating foundation (repos/Notion/wiki git), running
  department onboarding in order, cleaning up unused platforms, or adding a new
  platform later. Prefer this over improvising from project_install.md alone.
---

# 4r7a Install (admin + coding agent)

You are helping an **admin** install or re-scope company-brain. Do **not** invent
credentials, create GitHub/Notion resources silently, or delete platform code
without an explicit admin confirm.

Human map (same facts): [`project_install.md`](../../../project_install.md).
Machine profile: `config/install_profile.yaml`.

## Flow

0. **Redeploy cue (if set)** — run `company-brain admin fleet status`. If a
   redeploy cue is pending: confirm agent-code PR merged →
   `admin fleet pause` → pull/restart 4r7a + persistent managers →
   `admin fleet resume` → `admin fleet clear-redeploy`. Then continue.
1. **Profile** — compile decisions (best-practice defaults; granular overrides)
2. **Credentials** — checklist for enabled platforms only
3. **Foundation** — MD volume, brain + wiki repo URLs/access, Notion init, wiki_commit
   (may auto-create empty `{org}/company-wiki` via `gh` when missing)
4. **Onboard** — engineering → operations → product → growth → finance → HR
5. **Cleanup** — optional unused-platform removal on the **private fork** only
6. **Steady state** — start wiki_commit / admin_manager / hot lanes as enabled

## Commands

```bash
company-brain install profile [--interactive] [--runtime local|cloud] \
  --brain-repo-url … --wiki-repo-url … \
  [--disable-platform NAME] [--disable-department NAME]
company-brain install credentials
company-brain install foundation
company-brain install verify
company-brain install onboard [--strict] [--no-managers] [--confirm-cleanup]
company-brain install status
company-brain install cleanup --confirm   # prints checklist only; never rm
```

Progress wiki page: `admin/install-progress.md` (`sync: admin_only`).

## Repo topology

1. Private **4r7a** clone (company brain / agent code) — admin creates; set URL in profile
2. Empty private **company-wiki** (MD backup only) — admin creates **or**
   `install foundation` creates `{org}/company-wiki` when missing
   (`wiki_repo_name` overridable; `--no-create-wiki-repo` to skip)
3. Ask admin for brain URL (+ wiki URL if already exists) → `install profile`
4. Validate / ensure via `install foundation` / `gh`

## Defaults

- `notion_sync` / `employee_wiki` / `wiki_git_backup`: on
- `bridge`: off (deferred)
- Notify install failures + investor drafts to `#wiki-admin`
  (`config/models.yaml` → `token_budget.admin_channel`)
- Unused platforms: **skip**, do not delete unless admin confirms cleanup review

## New platform / agent protocol

When the company needs a platform not in the profile:

1. Check private fork vs `upstream/main` for an existing implementation
2. If found upstream → merge/cherry-pick; enable in `install_profile.yaml`; run that
   platform’s onboarding CLI
3. If missing → open a design thread with [`docs/design_process.md`](../../../docs/design_process.md);
   use neighbor agents under `src/company_brain/agents/` as patterns (manager +
   specialists, read-only boundaries, wiki paths, notify, Smolfile hosts)
4. After build → enable in profile, `install credentials`, onboard, update progress
5. **Optional:** ask the admin whether to open a PR contributing the new platform
   back to the public upstream 4r7a repo (never push without their yes)

## Content operators (admin)

```bash
company-brain admin investor-newsletter [--month YYYY-MM] [--force]
company-brain admin knowledge paste --title "…" --body "…"   # or --file / stdin
company-brain admin knowledge approve --import-id … [--dest PATH] [--to-raw]
```

Paste always quarantines + scans first. Broader company-wiki dest only when
`--dest` / sync label specified. Never use console Wiki save for untrusted paste.

## Hard rules

- Secrets stay in `.env` — never YAML or wiki
- Dispatch onboarding via CLI / `get_runtime().run` — do not call specialist
  `.execute()` from ad-hoc scripts when an onboarding agent exists
- Confirm before any platform/department **deletion** checklist execution
- Bridge MCP, wiki volume rollback automation, and process mining are out of scope
  for this skill (see `docs/tabled.md`)
