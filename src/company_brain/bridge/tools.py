"""Bridge tool implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.bridge.config import BridgeConfig, load_bridge_config
from company_brain.bridge.events import BridgeEvent, BridgeEventStore
from company_brain.bridge.index import load_index, rebuild_index, search_entries
from company_brain.bridge.rate_limit import RateLimiter
from company_brain.bridge.read_gate import ReadGate
from company_brain.config import CONFIG_DIR, resolve_wiki_dir
from company_brain.members_config import load_members_config
from company_brain.wiki.employee_store import LocalEmployeeWikiStore
from company_brain.wiki.store import LocalWikiStore


@dataclass
class ToolContext:
    member: str
    bridge_cfg: BridgeConfig
    gate: ReadGate
    events: BridgeEventStore
    rate_limiter: RateLimiter
    config_dir: Path | None = None

    @classmethod
    def for_member(cls, member: str, config_dir: Path | None = None) -> ToolContext:
        cfg = load_bridge_config(config_dir)
        return cls(
            member=member,
            bridge_cfg=cfg,
            gate=ReadGate(member, bridge_cfg=cfg),
            events=BridgeEventStore(cfg, config_dir),
            rate_limiter=RateLimiter(
                reads_per_minute=cfg.rate_limits.reads_per_minute,
                report_blocker_per_day=cfg.rate_limits.report_blocker_per_day,
            ),
            config_dir=config_dir,
        )


def _audit(ctx: ToolContext, tool: str, detail: str) -> None:
    path = ctx.bridge_cfg.config_path(ctx.bridge_cfg.audit_log_path, ctx.config_dir or CONFIG_DIR)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "member": ctx.member,
            "tool": tool,
            "detail": detail,
        }
    )
    with path.open("a") as f:
        f.write(line + "\n")


def _read_page_body(rel_path: str, volume: str) -> tuple[str, str]:
    if volume == "employee":
        store = LocalEmployeeWikiStore()
    else:
        store = LocalWikiStore(root=resolve_wiki_dir())
    if not store.exists(rel_path):
        return "", ""
    doc = store.read(rel_path)
    sync = str((doc.frontmatter or {}).get("sync") or "")
    return sync, doc.body


def report_blocker(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if not ctx.rate_limiter.check_report(ctx.member):
        raise PermissionError("report_blocker daily limit exceeded")

    idem = str(arguments.get("idempotency_key") or "")
    if idem:
        existing = ctx.events.find_by_idempotency(ctx.member, idem)
        if existing:
            return {"status": "duplicate", "event_id": existing.event_id}

    event = BridgeEvent.create_blocker(
        member=ctx.member,
        title=str(arguments.get("title") or ""),
        area=str(arguments.get("area") or ""),
        severity=str(arguments.get("severity") or "medium"),
        blocked_since=str(arguments.get("blocked_since") or ""),
        evidence=str(arguments.get("evidence") or ""),
        suggested_owner=str(arguments.get("suggested_owner") or ""),
        idempotency_key=idem,
    )
    ctx.events.append(event)
    ctx.rate_limiter.record_report(ctx.member)
    _audit(ctx, "report_blocker", event.event_id)
    return {"status": "accepted", "event_id": event.event_id}


def get_priority(ctx: ToolContext, _arguments: dict[str, Any]) -> dict[str, Any]:
    rollup_path = ctx.bridge_cfg.rollup.blockers_path
    lead_path = ctx.bridge_cfg.rollup.lead_focus_path

    blockers_sync, blockers_body = _read_page_body(rollup_path, "company")
    lead_sync, lead_body = _read_page_body(lead_path, "company")

    out: dict[str, Any] = {"blockers": None, "lead_focus": None}

    if ctx.gate.can_read(rollup_path, blockers_sync, volume="company"):
        out["blockers"] = {"path": rollup_path, "body": blockers_body}

    if ctx.gate.can_read(lead_path, lead_sync, volume="company"):
        out["lead_focus"] = {"path": lead_path, "body": lead_body}

    _audit(ctx, "get_priority", rollup_path)
    return out


def search_practices(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "")
    limit = min(int(arguments.get("limit") or 20), 50)
    index = load_index(ctx.bridge_cfg, ctx.config_dir)
    if not index.entries:
        index = rebuild_index(bridge_cfg=ctx.bridge_cfg, config_dir=ctx.config_dir)
    hits = search_entries(index, ctx.gate, query, limit=limit)
    practice_hits = [h for h in hits if "practices" in h.rel_path]
    _audit(ctx, "search_practices", query[:80])
    return {
        "results": [
            {"path": h.rel_path, "title": h.title, "sync": h.sync, "volume": h.volume}
            for h in practice_hits
        ]
    }


def list_skills(ctx: ToolContext, _arguments: dict[str, Any]) -> dict[str, Any]:
    index = load_index(ctx.bridge_cfg, ctx.config_dir)
    if not index.skills:
        index = rebuild_index(bridge_cfg=ctx.bridge_cfg, config_dir=ctx.config_dir)
    visible: dict[str, list[dict[str, str]]] = {}
    for dept, skills in index.skills.items():
        if not ctx.gate.department_allowed(dept):
            continue
        visible[dept] = list(skills)
    _audit(ctx, "list_skills", ",".join(visible.keys()))
    return {"departments": visible}


def get_skill(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(arguments.get("id") or arguments.get("skill_id") or "").strip()
    department = str(arguments.get("department") or "").strip()
    if not skill_id:
        raise ValueError("id is required")

    index = load_index(ctx.bridge_cfg, ctx.config_dir)
    if not index.skills:
        index = rebuild_index(bridge_cfg=ctx.bridge_cfg, config_dir=ctx.config_dir)

    for dept, skills in index.skills.items():
        if department and dept != department:
            continue
        if not ctx.gate.department_allowed(dept):
            continue
        for sk in skills:
            if sk.get("id") != skill_id:
                continue
            path = sk.get("path") or ""
            if not path:
                raise ValueError(f"skill {skill_id} has no path")
            sync, body = _read_page_body(path, "company")
            if not ctx.gate.can_read(path, sync, volume="company"):
                raise PermissionError("skill not readable")
            _audit(ctx, "get_skill", skill_id)
            return {"id": skill_id, "department": dept, "path": path, "body": body}
    raise ValueError(f"skill not found: {skill_id}")


def dispatch_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "report_blocker":
        if not ctx.rate_limiter.check_read(ctx.member):
            raise PermissionError("read rate limit exceeded")
        ctx.rate_limiter.record_read(ctx.member)

    tools = {
        "report_blocker": report_blocker,
        "get_priority": get_priority,
        "search_practices": search_practices,
        "list_skills": list_skills,
        "get_skill": get_skill,
    }
    fn = tools.get(name)
    if fn is None:
        raise ValueError(f"unknown tool: {name}")

    spec = load_members_config(ctx.config_dir).get(ctx.member)
    if spec is None or not spec.is_active:
        raise PermissionError("member inactive or unknown")

    return fn(ctx, arguments)
