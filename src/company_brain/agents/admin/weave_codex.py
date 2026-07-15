"""Weave builder backend A — Codex CLI inside a smol registry guest VM."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field

from company_brain.agents.admin.change_request import ChangeRequest
from company_brain.agents.admin.weave_builder_config import weave_builder_config
from company_brain.agents.admin.weave_worktree import WeaveWorktree
from company_brain.runtime.builder_session import (
    builder_env_for_backend,
    builder_runtime_available,
    ensure_codex_image,
    run_in_builder_vm,
)

logger = logging.getLogger(__name__)


@dataclass
class BuilderResult:
    status: str  # ok | failed | escalate
    reason: str = ""
    changed_paths: list[str] = field(default_factory=list)
    output: str = ""


def _codex_prompt(request: ChangeRequest) -> str:
    return (
        "You are implementing an approved company-brain Weave change request.\n"
        "Constraints:\n"
        "- Only modify files under config/ that end in .yaml, .yml, or .json\n"
        "- You may also write docs/weave-requests/ bookkeeping files\n"
        "- Do not modify Python source, wiki content, secrets, or Smolfile allow_hosts\n"
        "- Prefer the smallest diff that satisfies the request\n"
        "- If the request cannot be done within those paths, make no edits and print ESCALATE\n\n"
        f"Request id: {request.request_id}\n"
        f"Title: {request.title}\n"
        f"Class: {request.change_class}\n"
        f"Requester: {request.requester_member}\n\n"
        f"Request body:\n{request.body}\n"
    )


def implement_with_codex(
    request: ChangeRequest,
    worktree: WeaveWorktree,
    *,
    force_unavailable: bool | None = None,
) -> BuilderResult:
    """Run Codex in a guest VM against ``worktree``.

    When the builder runtime is unavailable, returns ``failed`` (caller fail-closes).
    """
    available = builder_runtime_available() if force_unavailable is None else not force_unavailable
    if not available:
        return BuilderResult(status="failed", reason="builder_unavailable")

    cfg = weave_builder_config()
    env = builder_env_for_backend("codex")
    if "OPENAI_API_KEY" not in env:
        return BuilderResult(status="failed", reason="missing_openai_api_key")

    image = ensure_codex_image(str(cfg.get("codex_image") or ""))
    prompt = _codex_prompt(request)
    # Non-interactive Codex; image ships `codex` on PATH.
    quoted = shlex.quote(prompt)
    command = [
        "bash",
        "-lc",
        f"cd /workspace && codex exec --full-auto {quoted}",
    ]
    code, output = run_in_builder_vm(
        command,
        worktree=worktree.path,
        image=image,
        allow_hosts=list(cfg.get("builder_allow_hosts") or []),
        env=env,
        timeout=1800,
    )
    if code != 0:
        logger.warning("codex builder failed (exit %s): %s", code, output[-500:])
        if "ESCALATE" in output.upper():
            return BuilderResult(
                status="escalate",
                reason="codex_requested_escalate",
                output=output[-4000:],
            )
        return BuilderResult(status="failed", reason="codex_failed", output=output[-4000:])

    if "ESCALATE" in output.upper() and not worktree.changed_paths():
        return BuilderResult(
            status="escalate",
            reason="codex_requested_escalate",
            output=output[-4000:],
        )

    paths = worktree.changed_paths()
    return BuilderResult(
        status="ok",
        reason="implemented",
        changed_paths=paths,
        output=output[-4000:],
    )
