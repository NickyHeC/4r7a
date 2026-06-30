# Development

How to change company-brain safely: lint, test, and the doctor registry.

**Solo maintainer:** deferred features → [`tabled.md`](tabled.md); doc format →
[`doc-style.md`](doc-style.md); agent governance → [`.cursor/rules/solo-maintainer.mdc`](../.cursor/rules/solo-maintainer.mdc).

## Fix loop

After agent or platform work:

```bash
ruff check .
pytest -q
company-brain doctor all
```

For connectivity-only changes (tokens, OAuth, new platform env vars):

```bash
company-brain doctor connect
```

## Doctor registry

`company-brain doctor` runs scored, deterministic checks. Each doctor returns
checks tagged `pass`, `warn`, or `fail`. Score formula (unique rules only):

```
score = 100 − 1.5 × fails − 0.75 × warns
```

| Doctor | Scope |
|--------|--------|
| `connect` | Env tokens, CLI tools, platform auth (read-only) |
| `agents` | Filename conventions, docstrings, handbook coverage, `sfile` allow_hosts |
| `wiki` | MD-first flow — no direct Notion imports in agents |
| `ops` | Notifier transport, receipt forward policy, Gmail send surface |
| `naming` | Agent/wiki slug conventions, legacy path drift vs `name_migrate.py` |
| `all` | Every doctor (default when you run `company-brain doctor`) |
| `code` | `agents` + `wiki` + `ops` + `naming` (CI; no tokens) |

Options:

- `--json` — machine-readable report
- `--min-score N` — exit 1 if aggregate score is below N (CI uses 85 for code doctors)
- `--no-history` — skip append to `config/doctor-history.json`

History and baselines live under `config/`:

- `doctor-history.json` — last 200 runs (timestamp + per-doctor scores)
- `doctor-baseline.json` — known fail rules for regression diffing (optional)

## No-sus review

Before shipping auth, billing, Gmail actuation, receipt routing, onboarding, or
security-sensitive agent changes, run the **no-sus-agent-doctor** skill
(`.cursor/skills/no-sus-agent-doctor/SKILL.md`). Ship at score 100 or document
accepted debt in the PR.

Hard blockers include: platform duplication, Notifier bypass, wiki bypass,
runtime bypass in managers, Gmail send without dual opt-in, finance writes at
source, and new API hosts missing from `sfile` `allow_hosts`.

## Pre-commit

```bash
pip install pre-commit
pre-commit install
```

Hooks: `ruff check` and `pytest -q`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs ruff, pytest, and
`company-brain doctor code --min-score 85`. Connectivity checks are
local-only (they need your tokens).
