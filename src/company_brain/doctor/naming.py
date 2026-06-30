"""Naming doctor — agent filenames, wiki slugs, legacy path drift."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from company_brain.config import PROJECT_ROOT
from company_brain.doctor.types import CheckResult, DoctorReport
from company_brain.wiki.name_migrate import EXACT_PATH_RENAMES, PREFIX_PATH_RENAMES

AGENTS_ROOT = PROJECT_ROOT / "src" / "company_brain" / "agents"
SCAN_ROOTS = (
    PROJECT_ROOT / "src" / "company_brain",
    PROJECT_ROOT / "config",
    PROJECT_ROOT / "docs",
)
_SKIP_SCAN = frozenset({"name_migrate.py"})
_LEGACY_PATHS = sorted(
    {old for old, new in EXACT_PATH_RENAMES.items() if old != new}
    | {old for old, _ in PREFIX_PATH_RENAMES},
    key=len,
    reverse=True,
)
_WIKI_PATH_RE = re.compile(r'WIKI_PATH\s*=\s*["\']([^"\']+)["\']')
_KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PLURAL_SLUG_SUFFIXES = ("-reports", "-updates", "-features", "-notes", "-prs", "-reviews")
_NON_AGENT_SUFFIXES = ("_client.py", "_config.py", "_rest.py")
_SKIP_FILES = frozenset({"base.py", "gates.py", "result.py", "__init__.py"})


def _iter_agent_modules() -> list[Path]:
    out: list[Path] = []
    for path in sorted(AGENTS_ROOT.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        if path.name.endswith(_NON_AGENT_SUFFIXES):
            continue
        if "shared" in path.relative_to(AGENTS_ROOT).parts:
            continue
        out.append(path)
    return out


def _scan_roots_text() -> str:
    parts: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".yaml", ".yml", ".md", ".mdc"}:
                continue
            if path.name in _SKIP_SCAN:
                continue
            try:
                parts.append(path.read_text())
            except OSError:
                continue
    return "\n".join(parts)


def _legacy_path_hits(corpus: str) -> list[str]:
    hits: list[str] = []
    for legacy in _LEGACY_PATHS:
        if legacy in corpus:
            hits.append(legacy)
    return hits


def _wiki_path_violations() -> list[str]:
    hits: list[str] = []
    for path in _iter_agent_modules():
        text = path.read_text()
        for rel in _WIKI_PATH_RE.findall(text):
            slug = PurePosixPath(rel).name.removesuffix(".md")
            if "_" in rel:
                hits.append(f"{path.relative_to(AGENTS_ROOT)}: {rel} (use kebab-case)")
                continue
            if not _KEBAB_SLUG_RE.match(slug):
                hits.append(f"{path.relative_to(AGENTS_ROOT)}: {rel} (invalid slug)")
                continue
            for suffix in _PLURAL_SLUG_SUFFIXES:
                if slug.endswith(suffix):
                    hits.append(f"{path.relative_to(AGENTS_ROOT)}: {rel} (plural slug)")
                    break
    return hits


def _redundant_platform_prefixes() -> list[str]:
    hits: list[str] = []
    for path in _iter_agent_modules():
        rel = path.relative_to(AGENTS_ROOT)
        parts = rel.parts
        # Only platform subfolders: department/platform/agent.py (3+ parts).
        if len(parts) < 3:
            continue
        platform = parts[-2]
        if platform in {"shared", "linear_completed"}:
            continue
        stem = path.stem
        if path.name.endswith("_onboarding.py"):
            continue
        if path.name.endswith("_manager.py") and stem == f"{platform}_manager":
            continue
        if stem.startswith(f"{platform}_"):
            hits.append(rel.as_posix())
    return hits


def _agent_suffix_files() -> list[str]:
    return [
        p.relative_to(AGENTS_ROOT).as_posix()
        for p in _iter_agent_modules()
        if p.stem.endswith("_agent")
    ]


def run_naming_doctor() -> DoctorReport:
    report = DoctorReport(name="naming")
    corpus = _scan_roots_text()

    suffix_files = _agent_suffix_files()
    if suffix_files:
        report.checks.append(
            CheckResult(
                "agent_agent_suffix",
                "fail",
                f"Agent files use _agent suffix: {', '.join(sorted(suffix_files)[:8])}",
                "drop _agent per naming.mdc",
            )
        )
    else:
        report.checks.append(
            CheckResult("agent_agent_suffix", "pass", "No _agent suffix in agent filenames")
        )

    redundant = _redundant_platform_prefixes()
    if redundant:
        report.checks.append(
            CheckResult(
                "agent_redundant_platform_prefix",
                "warn",
                f"Redundant platform prefix: {', '.join(sorted(redundant)[:8])}",
                "e.g. gmail/ingest.py not gmail/gmail_ingest.py",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "agent_redundant_platform_prefix",
                "pass",
                "No redundant platform prefix in agent filenames",
            )
        )

    legacy = _legacy_path_hits(corpus)
    if legacy:
        report.checks.append(
            CheckResult(
                "legacy_wiki_paths",
                "warn",
                f"Legacy paths still referenced: {', '.join(legacy[:8])}"
                + (" …" if len(legacy) > 8 else ""),
                "rename to canonical slugs or run company-brain migrate-names",
            )
        )
    else:
        report.checks.append(
            CheckResult("legacy_wiki_paths", "pass", "No legacy wiki path slugs in code/docs")
        )

    wiki_violations = _wiki_path_violations()
    if wiki_violations:
        report.checks.append(
            CheckResult(
                "wiki_path_constants",
                "warn",
                "; ".join(wiki_violations[:6]) + (" …" if len(wiki_violations) > 6 else ""),
                "WIKI_PATH slugs: kebab-case, singular per naming.mdc",
            )
        )
    else:
        report.checks.append(
            CheckResult("wiki_path_constants", "pass", "WIKI_PATH constants follow slug rules")
        )

    return report
