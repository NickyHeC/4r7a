"""Allow-listed manual agent dispatch for the admin console."""

from __future__ import annotations

import importlib
from typing import Any

from company_brain.admin_console import audit
from company_brain.admin_console.config import dispatch_job
from company_brain.admin_console.heartbeats import record_dispatch
from company_brain.config import AppConfig, load_config
from company_brain.runtime import get_runtime


class DispatchError(RuntimeError):
    pass


def _load_agent_class(dotted: str) -> type:
    if "." not in dotted:
        raise DispatchError(f"Invalid agent path: {dotted}")
    module_path, cls_name = dotted.rsplit(".", 1)
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise DispatchError(f"Cannot import {module_path}: {exc}") from exc
    cls = getattr(mod, cls_name, None)
    if cls is None:
        raise DispatchError(f"Class {cls_name} not found in {module_path}")
    return cls


def run_dispatch(
    job_id: str,
    *,
    force: bool = False,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    job = dispatch_job(job_id)
    if job is None:
        raise DispatchError(f"Job not allow-listed: {job_id}")
    cls = _load_agent_class(job["agent"])
    config = config or load_config()
    kwargs = dict(job.get("kwargs") or {})
    audit.append_event(
        "dispatch",
        job_id=job_id,
        agent=job["agent"],
        force=force,
        kwargs=kwargs,
    )
    try:
        if force:
            # Bypass should_run cost gate; still use agent.run (not persistent loops).
            result = cls(config).run(**kwargs)
        else:
            result = get_runtime().run(cls, config, **kwargs)
        record_dispatch(job_id, result_status="ok")
        return {"status": "ok", "job_id": job_id, "force": force, "result": result}
    except Exception as exc:
        record_dispatch(job_id, result_status="error")
        audit.append_event("dispatch_error", job_id=job_id, error=str(exc)[:500])
        raise
