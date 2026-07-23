"""Agents doctor — naming, docs, Smolfile drift, handbook coverage."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from company_brain.config import PROJECT_ROOT
from company_brain.doctor.types import CheckResult, DoctorReport

AGENTS_ROOT = PROJECT_ROOT / "src" / "company_brain" / "agents"
SRC_ROOT = PROJECT_ROOT / "src" / "company_brain"
HANDBOOK_DIR = PROJECT_ROOT / "docs" / "agents"
VMSPEC = PROJECT_ROOT / "Smolfile"

_SKIP_FILES = frozenset({"base.py", "gates.py", "result.py", "__init__.py"})
_SKIP_SUFFIXES = ("_client.py",)
_HOST_ASSIGN_RE = re.compile(
    r'^(?:[A-Z][A-Z0-9_]*)\s*=\s*["\']https://([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,})'
)
_EXPENSIVE_MARKERS = (
    "run_openai_sync",
    "iter_claude_query",
    "claude_websearch_prompt",
    "gather_markdown(",
    "Runner.run_sync",
    "Runner.run(",
)
_INTERACTIVE_COST_GATE_EXEMPT = frozenset({"ask_wiki"})


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


def _load_smolfile_hosts() -> set[str]:
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


def _direct_agent_run_bypasses() -> list[str]:
    """Agents calling another agent lifecycle method outside the runtime."""
    hits: set[str] = set()
    lifecycle_methods = {"execute", "run", "run_once"}
    for path in _iter_agent_py_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue

        agent_vars: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            constructor = value.func
            name = constructor.id if isinstance(constructor, ast.Name) else ""
            if name.endswith(("Agent", "Manager")):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                agent_vars.update(target.id for target in targets if isinstance(target, ast.Name))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in lifecycle_methods:
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Call):
                constructor = receiver.func
                name = constructor.id if isinstance(constructor, ast.Name) else ""
                is_agent = name.endswith(("Agent", "Manager"))
            else:
                is_agent = isinstance(receiver, ast.Name) and receiver.id in agent_vars
            if is_agent:
                hits.add(f"{path.relative_to(AGENTS_ROOT)}:{node.lineno}")
    return sorted(hits)


def _wiki_writer_mode_gaps() -> list[str]:
    """Wiki-writing agent classes must declare their write mode explicitly."""
    gaps: list[str] = []
    for path in _iter_handbook_agent_files():
        text = path.read_text()
        if "write_wiki_page(" not in text and "write_employee_wiki_page(" not in text:
            continue
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if "BaseAgent" not in bases:
                continue
            fields = {
                target.id
                for item in node.body
                if isinstance(item, (ast.Assign, ast.AnnAssign))
                for target in (item.targets if isinstance(item, ast.Assign) else [item.target])
                if isinstance(target, ast.Name)
            }
            if "WRITE_MODE" not in fields:
                gaps.append(f"{path.relative_to(AGENTS_ROOT)}:{node.name}")
    return gaps


def _expensive_agent_gate_gaps() -> list[str]:
    """LLM/web-search agents need a cheap gate unless each call is human-requested."""
    gaps: list[str] = []
    for path in _iter_handbook_agent_files():
        text = path.read_text()
        if not any(marker in text for marker in _EXPENSIVE_MARKERS):
            continue
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if "BaseAgent" not in bases:
                continue
            agent_name = ""
            for item in node.body:
                if (
                    isinstance(item, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "name"
                        for target in item.targets
                    )
                    and isinstance(item.value, ast.Constant)
                ):
                    agent_name = str(item.value.value)
            if agent_name in _INTERACTIVE_COST_GATE_EXEMPT:
                continue
            if not any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "should_run"
                for item in node.body
            ):
                gaps.append(f"{path.relative_to(AGENTS_ROOT)}:{node.name}")
    return gaps


def run_agents_doctor() -> DoctorReport:
    report = DoctorReport(name="agents")
    agent_files = _iter_agent_py_files()
    handbook_files = _iter_handbook_agent_files()
    handbook = _handbook_text()
    smolfile_hosts = _load_smolfile_hosts()

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
    # Google Calendar REST uses www.googleapis.com; Smolfile lists calendar.googleapis.com.
    if "calendar.googleapis.com" in smolfile_hosts and "www.googleapis.com" in api_hosts:
        api_hosts.discard("www.googleapis.com")
    drift = sorted(h for h in api_hosts if h not in smolfile_hosts)
    if drift:
        report.checks.append(
            CheckResult(
                "smolfile_allow_hosts",
                "warn",
                f"API hosts in code missing from Smolfile: {', '.join(drift)}",
                "add hosts to Smolfile [network] allow_hosts",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "smolfile_allow_hosts",
                "pass",
                "Smolfile allow_hosts covers agent API hosts",
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

    direct_runs = _direct_agent_run_bypasses()
    if direct_runs:
        report.checks.append(
            CheckResult(
                "agent_runtime_dispatch",
                "warn",
                f"Direct Agent/Manager .run() calls: {', '.join(direct_runs[:8])}",
                "dispatch through get_runtime().run() so lifecycle gates apply",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "agent_runtime_dispatch",
                "pass",
                "Agent-to-agent calls use runtime dispatch",
            )
        )

    mode_gaps = _wiki_writer_mode_gaps()
    if mode_gaps:
        report.checks.append(
            CheckResult(
                "agent_write_mode",
                "warn",
                f"Wiki writers missing class WRITE_MODE: {', '.join(mode_gaps[:8])}",
                "declare WRITE_MODE and pass it to the publish helper",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "agent_write_mode",
                "pass",
                "Wiki-writing agents declare WRITE_MODE",
            )
        )

    gate_gaps = _expensive_agent_gate_gaps()
    if gate_gaps:
        report.checks.append(
            CheckResult(
                "agent_cost_gate",
                "warn",
                f"Expensive agents missing should_run: {', '.join(gate_gaps[:8])}",
                "add a cheap deterministic gate or document an interactive exemption",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "agent_cost_gate",
                "pass",
                "Expensive agents have cheap cost gates",
            )
        )

    return report
