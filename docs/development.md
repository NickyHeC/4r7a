# Development

How to change company-brain safely: lint, test, and the doctor registry.

**Solo maintainer:** deferred features → [`tabled.md`](tabled.md); doc format →
[`doc-style.md`](doc-style.md); agent governance → [`.cursor/rules/solo-maintainer.mdc`](../.cursor/rules/solo-maintainer.mdc).

## Fix loop

After agent or platform work:

```bash
ruff check .
ruff format --check .
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
| `agents` | Filename conventions, docstrings, handbook coverage, `Smolfile` allow_hosts |
| `wiki` | MD-first flow — no direct Notion imports in agents |
| `ops` | Notifier transport, receipt forward policy, Gmail send surface |
| `naming` | Agent/wiki slug conventions, legacy path drift vs `name_migrate.py` |
| `llm` | Model tier bindings, token budget + vendor reconcile, run caps, model health ping + auto-fallback (needs keys; may write `models.yaml` overrides + alert `#wiki-admin`) |
| `bridge` | Bridge MCP config, tokens, index readiness |
| `all` | Every doctor (default when you run `company-brain doctor`) |
| `code` | `agents` + `wiki` + `ops` + `naming` (CI; no tokens) |

Options:

- `--json` — machine-readable report
- `--min-score N` — exit 1 if aggregate score is below N (CI uses 85 for code doctors)
- `--no-history` — skip append to `config/doctor-history.json`

History and baselines live under `config/`:

- `doctor-history.json` — last 200 runs (timestamp + per-doctor scores)
- `doctor-baseline.json` — known fail rules for regression diffing (optional)

## Post-feature hygiene checklist

After a **large feature section** ships (new platform, new subsystem, multi-file
refactor), run these three passes. The pre-ship checklist above is the subset that
runs on **every** ship; this is the deeper sweep for big builds. Per
[`solo-maintainer.mdc`](../.cursor/rules/solo-maintainer.mdc) §7, offer it — don't
auto-run destructive cleanup.

### 1. Cleanliness

```bash
ruff check .              # style, unused imports (F401), redefs (F811)
ruff format --check .     # canonical layout (Black-compatible)
pytest -q                 # full suite green
pre-commit run -a         # whitespace, EOF, merge markers, large files, YAML, private-key
git status --short        # only intended files changed
git diff                  # self-review the change before commit
```

- No stray generated files tracked (egg-info, `__pycache__`, `*.pyc`, run history).
  New local-only state (markers, history, ledgers) belongs in `.gitignore`, not the tree.
- No `docs/plans/*` left behind for shipped work (delete when steady-state docs are updated).
- No debug leftovers: `rg -n 'breakpoint\(|import pdb|pdb.set_trace|print\('` in touched
  `src/` files (logging via `self.logger`, not `print`).
- **Formatting:** `ruff format` is adopted project-wide. Run `ruff format .` before
  commit if pre-commit is not installed; CI runs `ruff format --check .`.

### 2. Coherence

```bash
company-brain doctor code   # agents + wiki + ops + naming (no tokens)
company-brain doctor llm    # tier bindings, budget, model health (needs keys)
company-brain models budget              # monthly spend + per-agent run caps
company-brain models budget --reconcile  # tracked usage vs Mercury LLM vendor bills
company-brain models spot-check          # vibe eval fixtures → #wiki
```

Enable enforcement in `config/models.yaml` (`token_budget.enabled: true`).
Per-run caps apply via `run_limits` regardless of monthly budget toggle.

Then confirm **docs match code** (drift is silent):

| Surface | Check |
|---------|-------|
| Department handbook (`docs/agents/<dept>.md`) | New/removed agents + schedules reflected |
| `README.md` | High-level map still accurate (no per-agent detail) |
| `project_install.md` | Connect/onboard steps cover new platforms/config |
| `config/*.yaml` | Every new key is read by code; no orphaned keys |
| `memory.md` | Dated entry prepended for the feature |
| `docs/tabled.md` | Shipped rows removed; new deferrals added |

### 3. Dead code

```bash
ruff check . --select F    # unused imports/vars, redefinitions
```

Ruff does not catch unused *functions/classes/modules*. For those, sweep manually:

- For each new public symbol, grep for callers (`rg 'name\('`); a definition with no
  caller outside its own file/tests is dead — remove it or wire it.
- Delete placeholder/zero-logic modules; capture "concept only" work as a
  [`docs/tabled.md`](tabled.md) row instead of a dead `.py` file.
- Watch for **duplicate helpers** (e.g. two notifiers for one channel) and **config
  keys** with no reader — consolidate to one source of truth.
- Optional deeper scan: `pipx run vulture src/ --min-confidence 80` (not a project dep).

### 4. Safety and dependencies

Highest priority here because company-brain handles tokens for every platform and the
`access-control` rule forbids committing secrets.

```bash
# Secret scan — never commit .env values, tokens, or keys
pipx run detect-secrets scan            # or: gitleaks detect --no-banner
git diff --cached                       # eyeball staged diff for tokens before commit

# Dependency vulnerabilities (run when pyproject deps changed)
pip-audit                               # or: pipx run pip-audit
```

- New API host / egress? Add it to the `Smolfile` `[network] allow_hosts` (the `agents` doctor checks this).
- New dependency? Pin a floor in `pyproject.toml`, confirm it is actually imported
  (no orphan deps), and re-run `pip-audit`.

### Optional deeper passes (not project deps; run via `pipx`/`uvx`)

| Pass | Command | When |
|------|---------|------|
| Type check | `pipx run mypy src/` or `pyright` | Complex new typed surface |
| Coverage | `pytest --cov=company_brain` | Verify new code is exercised |
| Spell check | `pipx run codespell src/ docs/ *.md` | Docs-heavy feature |
| Extended lint | `ruff check --select B,UP,SIM .` | Opt-in bugbear / pyupgrade / simplify |

Ship the feature at `doctor code` score 100 (or document accepted debt). Fold the
outcome into `memory.md`.

## No-sus review

Before shipping auth, billing, Gmail actuation, receipt routing, onboarding, or
security-sensitive agent changes, run the **no-sus-agent-doctor** skill
(`.cursor/skills/no-sus-agent-doctor/SKILL.md`). Ship at score 100 or document
accepted debt in the PR.

Hard blockers include: platform duplication, Notifier bypass, wiki bypass,
runtime bypass in managers, Gmail send without dual opt-in, finance writes at
source, and new API hosts missing from `Smolfile` `[network] allow_hosts`.

## Pre-commit

```bash
pip install pre-commit
pre-commit install
pre-commit run -a          # run against the whole tree once
```

Hooks: standard file checks (trailing whitespace, EOF newline, merge-conflict
markers, large-file guard, YAML validity, `detect-private-key`), `ruff check --fix`,
`ruff format`, and `pytest -q`.

Optional (once per clone): `git config blame.ignoreRevsFile .git-blame-ignore-revs`
so `git blame` skips the one-time format commit.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs ruff, pytest, and
`company-brain doctor code --min-score 85`. Connectivity checks are
local-only (they need your tokens).
