"""Agents doctor — naming, docs, vmspec drift, handbook coverage."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from company_brain.config import PROJECT_ROOT
from company_brain.doctor.types import CheckResult, DoctorReport

AGENTS_ROOT = PROJECT_ROOT / "src" / "company_brain" / "agents"
HANDBOOK_DIR = PROJECT_ROOT / "docs" / "agents"
VMSPEC = PROJECT_ROOT / "vmspec.toml"

_SKIP_FILES = frozenset({"base.py", "gates.py", "result.py", "__init__.py"})
_SKIP_SUFFIXES = ("_client.py",)
_HOST_ASSIGN_RE = re.compile(
    r'^(?:[A-Z][A-Z0-9_]*)\s*=\s*["\']https://([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,})'
)


def _is_api_surface(path: Path) -> bool:
    name = path.name
    return name.endswith("_client.py") or name.endswith("_rest.py") or name == "gh.py"


def _iter_agent_py_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(AGENTS_ROOT.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        if path.name.endswith(_SKIP_SUFFIXES):
            continue
        if "shared" in path.relative_to(AGENTS_ROOT).parts:
            continue
        out.append(path)
    return out


def _defines_agent_class(path: Path) -> bool:
    """True when the module defines a ``BaseAgent`` subclass (i.e. a real agent)."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
            if name == "BaseAgent":
                return True
    return False


def _iter_handbook_agent_files() -> list[Path]:
    """Files expected in docs/agents/ — modules that define an agent (BaseAgent subclass).

    Config/standards/propagation helpers and REST/client wrappers are not agents and
    are not required in the handbook (platform helpers live under the platform folder
    per agent-organization.mdc).
    """
    return [p for p in _iter_agent_py_files() if _defines_agent_class(p)]


def _load_vmspec_hosts() -> set[str]:
    if not VMSPEC.exists():
        return set()
    text = VMSPEC.read_text()
    return {m.group(1).strip().lower() for m in re.finditer(r'"([^"]+)"', text)}


def _extract_api_hosts(path: Path) -> set[str]:
    if not _is_api_surface(path):
        return set()
    hosts: set[str] = set()
    for line in path.read_text().splitlines():
        match = _HOST_ASSIGN_RE.match(line.strip())
        if match:
            hosts.add(match.group(1).lower())
    return hosts


def _has_module_docstring(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return False
    return ast.get_docstring(tree) is not None


def _handbook_text() -> str:
    parts: list[str] = []
    for md in sorted(HANDBOOK_DIR.glob("*.md")):
        parts.append(md.read_text())
    return "\n".join(parts)


def _manager_runtime_bypasses() -> list[str]:
    """Managers calling specialist .execute() instead of get_runtime().run()."""
    hits: list[str] = []
    for path in _iter_agent_py_files():
        if not path.name.endswith("_manager.py") and path.name not in {
            "monthly_expense.py",
            "quarterly_calculation.py",
            "subscription_audit.py",
        }:
            continue
        text = path.read_text()
        if ".execute(" in text and "get_runtime().run(" not in text:
            hits.append(path.relative_to(AGENTS_ROOT).as_posix())
        elif ".execute(" in text:
            # Mixed — still flag inline .execute in managers
            for line in text.splitlines():
                if ".execute(" in line and "get_runtime" not in line:
                    hits.append(f"{path.relative_to(AGENTS_ROOT)}: inline .execute()")
                    break
    return hits


def run_agents_doctor() -> DoctorReport:
    report = DoctorReport(name="agents")
    agent_files = _iter_agent_py_files()
    handbook_files = _iter_handbook_agent_files()
    handbook = _handbook_text()
    vmspec_hosts = _load_vmspec_hosts()

    hyphen_files = [p.name for p in agent_files if "-" in p.name]
    if hyphen_files:
        report.checks.append(
            CheckResult(
                "agent_hyphen_filenames",
                "fail",
                f"Agent files use hyphens: {', '.join(sorted(hyphen_files))}",
                "rename to underscore per agent-organization.mdc",
            )
        )
    else:
        report.checks.append(
            CheckResult("agent_hyphen_filenames", "pass", "Agent filenames use underscores")
        )

    missing_docs = [
        p.relative_to(AGENTS_ROOT).as_posix()
        for p in agent_files
        if p.name.endswith(".py") and not _has_module_docstring(p)
    ]
    if missing_docs:
        report.checks.append(
            CheckResult(
                "agent_module_docstrings",
                "warn",
                f"Missing module docstrings: {', '.join(sorted(missing_docs)[:8])}"
                + (" …" if len(missing_docs) > 8 else ""),
                "add docstring explaining SDK choice / purpose",
            )
        )
    else:
        report.checks.append(
            CheckResult("agent_module_docstrings", "pass", "Agent modules have docstrings")
        )

    missing_handbook = [
        p.stem
        for p in handbook_files
        if p.stem not in handbook and f"`{p.stem}.py`" not in handbook
    ]
    if missing_handbook:
        report.checks.append(
            CheckResult(
                "agent_handbook_coverage",
                "warn",
                f"Not in docs/agents/: {', '.join(sorted(missing_handbook)[:10])}"
                + (" …" if len(missing_handbook) > 10 else ""),
                "update docs/agents/<dept>.md + README + project_install.md",
            )
        )
    else:
        report.checks.append(
            CheckResult("agent_handbook_coverage", "pass", "Agent files referenced in handbook")
        )

    api_hosts: set[str] = set()
    for path in AGENTS_ROOT.rglob("*.py"):
        api_hosts |= _extract_api_hosts(path)
    # Google Calendar REST uses www.googleapis.com; vmspec lists calendar.googleapis.com.
    if "calendar.googleapis.com" in vmspec_hosts and "www.googleapis.com" in api_hosts:
        api_hosts.discard("www.googleapis.com")
    drift = sorted(h for h in api_hosts if h not in vmspec_hosts)
    if drift:
        report.checks.append(
            CheckResult(
                "vmspec_allow_hosts",
                "warn",
                f"API hosts in code missing from vmspec.toml: {', '.join(drift)}",
                "add hosts to vmspec.toml [network] allow_hosts",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "vmspec_allow_hosts", "pass", "vmspec.toml allow_hosts covers agent API hosts"
            )
        )

    bypasses = _manager_runtime_bypasses()
    if bypasses:
        report.checks.append(
            CheckResult(
                "manager_runtime_dispatch",
                "warn",
                f"Inline .execute() in managers: {', '.join(bypasses[:5])}",
                "dispatch specialists via get_runtime().run()",
            )
        )
    else:
        report.checks.append(
            CheckResult("manager_runtime_dispatch", "pass", "Managers use runtime dispatch")
        )

    return report
