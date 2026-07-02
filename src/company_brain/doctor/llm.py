"""Doctor — LLM tier health, budget, and fallback state."""

from __future__ import annotations

from company_brain.config import load_models_config
from company_brain.doctor.types import CheckResult, DoctorReport
from company_brain.llm.budget import budget_status
from company_brain.llm.health import run_model_health
from company_brain.llm.tiers import LLM_AGENTS, resolve_agent_model


def run_llm_doctor(*, apply_fallbacks: bool = True) -> DoctorReport:
    report = DoctorReport(name="llm")
    cfg = load_models_config()

    report.checks.append(
        CheckResult(
            "llm_mode",
            "pass",
            f"Model mode: {cfg.mode or 'balanced'}",
        ),
    )

    for agent in LLM_AGENTS:
        binding = resolve_agent_model(agent, cfg)
        report.checks.append(
            CheckResult(
                f"llm_agent:{agent}",
                "pass",
                (f"{agent} → {binding.provider_key}/{binding.tier} ({binding.model_id})"),
            ),
        )

    budget = budget_status()
    if budget["enabled"]:
        status = "pass"
        if budget["over_budget"]:
            status = "fail"
        elif budget["near_limit"]:
            status = "warn"
        report.checks.append(
            CheckResult(
                "llm_budget",
                status,
                (
                    f"Budget {budget['month']}: ${budget['spent_usd']:.2f} / "
                    f"${budget['limit_usd']:.2f} ({budget['percent_used']}%)"
                ),
                hint="Adjust token_budget in config/models.yaml",
            ),
        )
    else:
        report.checks.append(
            CheckResult(
                "llm_budget",
                "pass",
                "Token budget disabled",
                hint="Set token_budget.enabled in config/models.yaml",
            ),
        )

    health = run_model_health(apply_fallbacks=apply_fallbacks, notify=True, cfg=cfg)
    for probe in health.probes:
        status = "pass" if probe.ok else "warn"
        report.checks.append(
            CheckResult(
                f"llm_health:{probe.provider_key}:{probe.tier}",
                status,
                f"{probe.model_id}: {probe.detail or 'reachable'}",
                hint="Doctor will auto-fallback when possible",
            ),
        )

    for msg in health.fallbacks_applied:
        report.checks.append(
            CheckResult("llm_fallback", "warn", msg, hint="Persisted in models.yaml overrides"),
        )

    return report
