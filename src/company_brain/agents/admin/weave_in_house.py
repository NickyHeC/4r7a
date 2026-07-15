"""Weave builder backend B — in-house coding agent on an ephemeral worktree.

Opt-in via ``weave.builder: in_house`` / ``WEAVE_BUILDER=in_house``. Edits only
the guest worktree (never the host checkout). Prefer running inside smolvm when
available; falls back to worktree-local deterministic edits when no LLM key is
configured (tests / offline).
"""

from __future__ import annotations

import logging
import re
import textwrap
from pathlib import Path

from company_brain.agents.admin.change_request import ChangeRequest
from company_brain.agents.admin.weave_allowlist import path_allowed
from company_brain.agents.admin.weave_codex import BuilderResult
from company_brain.agents.admin.weave_worktree import WeaveWorktree
from company_brain.runtime.builder_session import (
    builder_env_for_backend,
    builder_runtime_available,
    run_in_builder_vm,
)

logger = logging.getLogger(__name__)


def _extract_config_targets(body: str) -> list[str]:
    """Heuristic: paths mentioned under config/ in the request body."""
    found: list[str] = []
    for match in re.finditer(r"(config/[A-Za-z0-9_./-]+\.(?:ya?ml|json))", body or ""):
        rel = match.group(1)
        if rel not in found and path_allowed(rel):
            found.append(rel)
    return found


def _apply_yaml_comment_marker(path: Path, request: ChangeRequest) -> bool:
    """Minimal deterministic edit for tests / no-LLM: append a Weave marker comment."""
    if not path.exists() or not path.is_file():
        return False
    text = path.read_text()
    marker = f"# weave:{request.request_id} — {request.title[:80]}\n"
    if marker in text:
        return True
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + marker)
    return True


def _guest_script(request: ChangeRequest) -> str:
    """Self-contained guest script — allow-listed touch + escalate hint for LLM installs."""
    return textwrap.dedent(
        f'''\
        """Weave in-house guest runner (generated)."""
        from pathlib import Path
        import re
        import sys

        ROOT = Path("/workspace")
        REQUEST_ID = {request.request_id!r}
        TITLE = {request.title!r}
        BODY = {request.body!r}

        def allowed(rel: str) -> bool:
            if rel.startswith("docs/weave-requests/"):
                return True
            if not rel.startswith("config/"):
                return False
            return rel.endswith((".yaml", ".yml", ".json"))

        targets = re.findall(r"(config/[A-Za-z0-9_./-]+\\.(?:ya?ml|json))", BODY)
        targets = [t for t in targets if allowed(t)]
        if not targets:
            print("ESCALATE: no allow-listed config path in request")
            sys.exit(2)

        edited = []
        for rel in targets:
            path = ROOT / rel
            if not path.is_file():
                continue
            marker = f"# weave:{{REQUEST_ID}} — {{TITLE[:80]}}\\n"
            text = path.read_text()
            if marker not in text:
                if not text.endswith("\\n"):
                    text += "\\n"
                path.write_text(text + marker)
            edited.append(rel)

        if not edited:
            print("ESCALATE: targets missing in worktree")
            sys.exit(2)
        print("edited:", ", ".join(edited))
        '''
    )


def implement_in_house(
    request: ChangeRequest,
    worktree: WeaveWorktree,
    *,
    use_vm: bool | None = None,
) -> BuilderResult:
    """Implement ``request`` on ``worktree`` using the in-house builder path."""
    env = builder_env_for_backend("in_house")
    vm = builder_runtime_available() if use_vm is None else use_vm

    if vm and (env.get("ANTHROPIC_API_KEY") or env.get("OPENAI_API_KEY")):
        script = _guest_script(request)
        script_path = worktree.path / ".weave_in_house_runner.py"
        script_path.write_text(script)
        code, output = run_in_builder_vm(
            ["python", "/workspace/.weave_in_house_runner.py"],
            worktree=worktree.path,
            image="python:3.12",
            env=env,
            timeout=1800,
        )
        script_path.unlink(missing_ok=True)
        if code != 0:
            logger.warning("in_house builder failed: %s", output[-500:])
            if "ESCALATE" in output.upper():
                return BuilderResult(
                    status="escalate",
                    reason="in_house_escalate",
                    output=output[-4000:],
                )
            return BuilderResult(
                status="failed",
                reason="in_house_failed",
                output=output[-4000:],
            )
        return BuilderResult(
            status="ok",
            reason="implemented",
            changed_paths=worktree.changed_paths(),
            output=output[-4000:],
        )

    targets = _extract_config_targets(request.body)
    if not targets:
        return BuilderResult(status="escalate", reason="no_allowlisted_target")

    edited: list[str] = []
    for rel in targets:
        dest = worktree.path / rel
        if _apply_yaml_comment_marker(dest, request):
            edited.append(rel)
    if not edited:
        return BuilderResult(status="escalate", reason="targets_missing_in_worktree")
    return BuilderResult(status="ok", reason="deterministic_edit", changed_paths=edited)
