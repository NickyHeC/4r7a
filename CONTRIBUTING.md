# Contributing to FourSeven

FourSeven (company-brain) is a docs-first codebase designed to be extended with **AI
coding agents**. You do not need deep familiarity with the internals — or to be an
expert prompter — to add a feature reliably. Point your agent at the two process docs
below and it knows how to run the whole design → build → test loop with you.

## The loop

Extending the system is two phases, one doc each:

1. **Design — [`docs/design_process.md`](docs/design_process.md)**
   Iron out scope *before* any code: your agent researches the repo, raises concerns
   (one at a time, in batches, or all at once — your choice), and records decisions into
   a temporary plan file. Nothing is built until scope is settled.

2. **Build, test, clean — [`docs/hygiene_checklist.md`](docs/hygiene_checklist.md)**
   Implement in small slices and prove each one: lint, tests, the `company-brain doctor`
   registry, cleanliness passes, and a security review for sensitive changes.

Start by writing a short vision (a few lines in a scratch file or issue), then tell your
agent:

```text
[link or paste your vision]

Design a new feature for 4r7a. Follow docs/design_process.md. Presentation mode: batch.
```

## For AI coding agents

Invariants load automatically from [`.cursor/rules/`](.cursor/rules) — start with
[`governance.mdc`](.cursor/rules/governance.mdc), which points to everything else. Read
[`memory.md`](memory.md) first for recent context; it is a reverse-chronological log
that saves you from reading the whole tree.

## Ground rules

- **One source of truth.** Each fact lives in exactly one doc; link to it, don't restate it.
- **Prove your claims.** Ship at `company-brain doctor code` score 100 or document accepted debt.
- **Never commit secrets.** No `.env` values, tokens, or keys — see [`access-control.mdc`](.cursor/rules/access-control.mdc).
- **Respect platform boundaries.** If a connected platform already owns a behavior, integrate — don't reimplement.

Setup and platform connection steps live in [`project_install.md`](project_install.md);
documentation conventions live in [`docs/doc_style.md`](docs/doc_style.md).
