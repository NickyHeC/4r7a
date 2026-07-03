"""Doctor — LLM tier health, budget, and fallback state."""

from __future__ import annotations

from company_brain.config import load_models_config
from company_brain.doctor.types import CheckResult, DoctorReport
from company_brain.llm.budget import budget_status, resolve_run_limits
from company_brain.llm.health import run_model_health
from company_brain.llm.reconcile import format_reconciliation, reconciliation_report
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
        limits = resolve_run_limits(agent, cfg)
        cap_bits = []
        if limits.max_usd_per_run is not None:
            cap_bits.append(f"${limits.max_usd_per_run:.2f}/run")
        if limits.max_steps_per_run is not None:
            cap_bits.append(f"{limits.max_steps_per_run} steps")
        if limits.max_tool_calls_per_run is not None:
            cap_bits.append(f"{limits.max_tool_calls_per_run} tools")
        cap = f" caps: {', '.join(cap_bits)}" if cap_bits else ""
        report.checks.append(
            CheckResult(
                f"llm_agent:{agent}",
                "pass",
                (f"{agent} → {binding.provider_key}/{binding.tier} ({binding.model_id}){cap}"),
            ),
        )

    budget = budget_status()
    if budget["enabled"]:
        status = "pass"
        if budget["over_budget"]:
            status = "fail"
        elif budget["near_limit"]:
            status = "warn"
        guidance = budget.get("guidance_usd") or {}
        detail = (
            f"Budget {budget['month']}: ${budget['spent_usd']:.2f} / "
            f"${budget['limit_usd']:.2f} ({budget['percent_used']}%) — "
            f"runtime ${budget['runtime_usd']:.2f}"
        )
        if guidance.get("runtime"):
            detail += f" / ~${guidance['runtime']:.0f} guidance"
        detail += f", builder ${budget['builder_usd']:.2f}"
        if guidance.get("builder"):
            detail += f" / ~${guidance['builder']:.0f} guidance"
        report.checks.append(
            CheckResult(
                "llm_budget",
                status,
                detail,
                hint="Adjust token_budget in config/models.yaml",
            ),
        )
        try:
            recon = reconciliation_report()
            recon_status = "warn" if recon["warn"] else "pass"
            if recon["vendor_usd"] <= 0 and recon["tracked_usd"] <= 0:
                recon_status = "pass"
                recon_detail = f"Reconcile {recon['month']}: no vendor or tracked spend yet"
            else:
                recon_detail = format_reconciliation(recon)
            report.checks.append(
                CheckResult(
                    "llm_budget_reconcile",
                    recon_status,
                    recon_detail,
                    hint="Tracked usage from API hooks; vendor bills from Mercury card spend",
                ),
            )
        except Exception as exc:
            report.checks.append(
                CheckResult(
                    "llm_budget_reconcile",
                    "warn",
                    f"Reconciliation skipped: {exc}",
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
