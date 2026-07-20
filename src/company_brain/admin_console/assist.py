"""Console Assist LLM — propose wiki edits / dispatches; never auto-apply."""

from __future__ import annotations

import json
from typing import Any

from company_brain.admin_console import audit
from company_brain.admin_console.config import dispatch_jobs
from company_brain.admin_console.costs import costs_snapshot
from company_brain.admin_console.heartbeats import status_rows
from company_brain.admin_console.wiki_ops import get_page, search_wiki


def _tool_wiki_search(query: str) -> str:
    hits = search_wiki(query, limit=8)
    return json.dumps(
        [
            {"path": h.get("rel_path"), "title": h.get("title"), "score": h.get("score")}
            for h in hits
        ],
        indent=2,
    )


def _tool_wiki_read(rel_path: str) -> str:
    page = get_page(rel_path)
    body = page["body"]
    if len(body) > 6000:
        body = body[:6000] + "\n\n…[truncated]"
    return json.dumps(
        {
            "rel_path": page["rel_path"],
            "title": page["title"],
            "sync_conflict": page["sync_conflict"],
            "body": body,
        },
        indent=2,
    )


def _tool_budget() -> str:
    return json.dumps(costs_snapshot(reconcile=False)["budget"], indent=2)


def _tool_status() -> str:
    return json.dumps(status_rows(), indent=2)


def _tool_list_dispatch() -> str:
    return json.dumps(
        [{"id": j["id"], "label": j["label"]} for j in dispatch_jobs()],
        indent=2,
    )


INSTRUCTIONS = """You are the company-brain admin console assistant.
You help the admin monitor agents, review LLM costs, search/edit the wiki, and
propose allow-listed dispatches.

Rules:
- Never claim you already edited the wiki or dispatched an agent.
- For edits: return a clear proposal with rel_path, title, and full new body.
- For dispatch: propose a job_id from the allow-list only.
- The admin must confirm writes and dispatches in the UI.
- Prefer concise answers with wiki path citations.
"""


def run_assist(message: str) -> dict[str, Any]:
    """Run one Assist turn; returns reply text + optional structured proposals."""
    audit.append_event("assist", message=message[:500])
    try:
        from agents import Agent, Runner, function_tool

        from company_brain.llm import openai_agents as oa
    except ImportError as exc:
        return {
            "reply": f"Assist unavailable (agents SDK): {exc}",
            "proposals": [],
        }

    @function_tool
    def wiki_search(query: str) -> str:
        """Search the full company wiki (admin scope)."""
        return _tool_wiki_search(query)

    @function_tool
    def wiki_read(rel_path: str) -> str:
        """Read one wiki Markdown page by relative path."""
        return _tool_wiki_read(rel_path)

    @function_tool
    def llm_budget() -> str:
        """Current month LLM budget status."""
        return _tool_budget()

    @function_tool
    def agent_status() -> str:
        """Persistent manager heartbeat status rows."""
        return _tool_status()

    @function_tool
    def list_dispatch_jobs() -> str:
        """List allow-listed manual dispatch jobs."""
        return _tool_list_dispatch()

    @function_tool
    def propose_wiki_edit(rel_path: str, title: str, body: str, rationale: str) -> str:
        """Propose a wiki page overwrite. Does NOT save — admin must confirm in UI."""
        proposal = {
            "type": "wiki_edit",
            "rel_path": rel_path,
            "title": title,
            "body": body,
            "rationale": rationale,
        }
        return json.dumps({"status": "proposed", "proposal": proposal})

    @function_tool
    def propose_dispatch(job_id: str, rationale: str, force: bool = False) -> str:
        """Propose an allow-listed dispatch. Does NOT run — admin must confirm."""
        proposal = {
            "type": "dispatch",
            "job_id": job_id,
            "force": force,
            "rationale": rationale,
        }
        return json.dumps({"status": "proposed", "proposal": proposal})

    agent = Agent(
        name="admin_console_assist",
        instructions=INSTRUCTIONS,
        tools=[
            wiki_search,
            wiki_read,
            llm_budget,
            agent_status,
            list_dispatch_jobs,
            propose_wiki_edit,
            propose_dispatch,
        ],
        model=oa.make_model(),
    )
    result = Runner.run_sync(
        agent,
        message,
        run_config=oa.make_run_config(),
    )
    reply = str(getattr(result, "final_output", None) or result)
    proposals = _extract_proposals_from_result(result)
    return {"reply": reply, "proposals": proposals}


def _extract_proposals_from_result(result: Any) -> list[dict[str, Any]]:
    """Best-effort scrape of propose_* tool JSON from the run."""
    proposals: list[dict[str, Any]] = []
    raw_items = getattr(result, "new_items", None) or getattr(result, "items", None) or []
    for item in raw_items:
        text = ""
        if hasattr(item, "output"):
            text = str(item.output or "")
        elif isinstance(item, dict):
            text = str(item.get("output") or item.get("content") or "")
        else:
            text = str(item)
        text = text.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        prop = data.get("proposal")
        if isinstance(prop, dict) and prop.get("type"):
            proposals.append(prop)
    return proposals
