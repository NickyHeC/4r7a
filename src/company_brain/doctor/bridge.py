"""Bridge MCP readiness checks."""

from __future__ import annotations

from company_brain.bridge.config import load_bridge_config
from company_brain.config import CONFIG_DIR
from company_brain.doctor.types import CheckResult, DoctorReport


def run_bridge_doctor() -> DoctorReport:
    checks: list[CheckResult] = []
    cfg_path = CONFIG_DIR / "bridge.yaml"
    checks.append(
        CheckResult(
            "bridge_config",
            "pass" if cfg_path.is_file() else "fail",
            "config/bridge.yaml present" if cfg_path.is_file() else "missing config/bridge.yaml",
            hint="Add config/bridge.yaml from repo template",
        )
    )

    try:
        cfg = load_bridge_config()
        checks.append(
            CheckResult(
                "bridge_rate_limits",
                "pass",
                f"reads={cfg.rate_limits.reads_per_minute}/min "
                f"reports={cfg.rate_limits.report_blocker_per_day}/day",
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult("bridge_config_parse", "fail", str(exc), hint="Fix bridge.yaml syntax")
        )
        return DoctorReport(name="bridge", checks=checks)

    tokens_path = cfg.config_path(cfg.tokens_path)
    if tokens_path.exists():
        mode = oct(tokens_path.stat().st_mode)[-3:]
        status = "pass" if mode <= "600" else "warn"
        checks.append(
            CheckResult(
                "bridge_tokens_perms",
                status,
                f"{cfg.tokens_path} mode={mode}",
                hint="chmod 600 config/bridge-tokens.json",
            )
        )
    else:
        checks.append(
            CheckResult(
                "bridge_tokens",
                "warn",
                "no tokens issued yet",
                hint="company-brain bridge issue-token <member>",
            )
        )

    index_path = cfg.config_path(cfg.index_path)
    checks.append(
        CheckResult(
            "bridge_index",
            "pass" if index_path.is_file() else "warn",
            "bridge index built" if index_path.is_file() else "index not built",
            hint="company-brain bridge rebuild-index",
        )
    )

    for dept, manifest in (cfg.skills_manifest or {}).items():
        checks.append(
            CheckResult(
                f"bridge_skills_manifest_{dept}",
                "warn",
                f"manifest path configured: {manifest}",
                hint="Create skills _index.yaml under engineering/practices/skills/",
            )
        )

    return DoctorReport(name="bridge", checks=checks)
