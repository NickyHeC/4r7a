"""Operations doctor — Slack notifier, Gmail actuation, receipt policy."""

from __future__ import annotations

import re
from pathlib import Path

from company_brain.agents.operations.shared.gmail_config import (
    receipt_company_domain,
    receipt_forward_enabled,
)
from company_brain.config import PROJECT_ROOT
from company_brain.doctor.types import CheckResult, DoctorReport

AGENTS_ROOT = PROJECT_ROOT / "src" / "company_brain" / "agents"
_SLACK_ALLOW = frozenset(
    {
        "operations/shared/operations_slack.py",
        "finance/shared/slack.py",
    }
)
_SEND_PATTERNS = (
    re.compile(r"messages\.send\b"),
    re.compile(r"\.send_message\b"),
    re.compile(r"gmail.*\.send\b", re.IGNORECASE),
)


def _iter_agent_py_files() -> list[Path]:
    return sorted(AGENTS_ROOT.rglob("*.py"))


def run_ops_doctor() -> DoctorReport:
    report = DoctorReport(name="ops")

    slack_bypass: list[str] = []
    for path in _iter_agent_py_files():
        rel = path.relative_to(AGENTS_ROOT).as_posix()
        if rel in _SLACK_ALLOW:
            continue
        if "chat_postMessage" in path.read_text():
            slack_bypass.append(rel)

    if slack_bypass:
        report.checks.append(
            CheckResult(
                "slack_notifier_bypass",
                "fail",
                f"Raw chat_postMessage outside transport: {', '.join(slack_bypass)}",
                "use operations_slack / from_finance_config Notifier",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "slack_notifier_bypass",
                "pass",
                "Slack posts only in notifier transport modules",
            )
        )

    if receipt_forward_enabled() and not receipt_company_domain():
        report.checks.append(
            CheckResult(
                "receipt_forward_domain",
                "fail",
                "receipt forward enabled but receipt_router.company_domain is empty",
                "set gmail.receipt_router.company_domain in config/operations.yaml",
            )
        )
    else:
        report.checks.append(
            CheckResult(
                "receipt_forward_domain",
                "pass",
                "Receipt forward has company_domain or is disabled",
            )
        )

    send_hits: list[str] = []
    for path in _iter_agent_py_files():
        if path.name == "gmail_client.py":
            continue
        text = path.read_text()
        for pat in _SEND_PATTERNS:
            if pat.search(text):
                send_hits.append(path.relative_to(AGENTS_ROOT).as_posix())
                break

    if send_hits:
        report.checks.append(
            CheckResult(
                "gmail_send_surface",
                "warn",
                f"Possible Gmail send calls: {', '.join(sorted(set(send_hits)))}",
                "Gmail send requires allow_send + GMAIL_ALLOW_SEND dual opt-in",
            )
        )
    else:
        report.checks.append(
            CheckResult("gmail_send_surface", "pass", "No Gmail send calls outside client")
        )

    return report
