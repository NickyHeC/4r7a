"""Thin builder session runner — smolvm/smol cloud guest commands for Weave."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from company_brain.agents.admin.weave_builder_config import weave_builder_config
from company_brain.config import resolve_sandbox
from company_brain.runtime.sandbox import GUEST_MOUNT, SmolSandbox

logger = logging.getLogger(__name__)

# Official smol registry Codex image (coding agent preinstalled).
DEFAULT_CODEX_IMAGE = "registry.smolmachines.com/library/codex:latest"


def builder_runtime_available() -> bool:
    """True when a guest VM runner can be used (local smolvm sandbox mode)."""
    return SmolSandbox().available()


def builder_env_for_backend(backend: str) -> dict[str, str]:
    """Secrets injected into the builder VM (model key only — never bank/Slack)."""
    env: dict[str, str] = {}
    if backend == "codex":
        key = (os.getenv("OPENAI_API_KEY") or os.getenv("WEAVE_OPENAI_API_KEY") or "").strip()
        if key:
            env["OPENAI_API_KEY"] = key
    elif backend == "in_house":
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GLM_BASE_URL", "GLM_API_KEY"):
            val = (os.getenv(name) or "").strip()
            if val:
                env[name] = val
        provider = (os.getenv("COMPANY_BRAIN_LLM_PROVIDER") or "").strip()
        if provider:
            env["COMPANY_BRAIN_LLM_PROVIDER"] = provider
    gh = (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if gh:
        env["GH_TOKEN"] = gh
        env["GITHUB_TOKEN"] = gh
    return env


def run_in_builder_vm(
    command: list[str],
    *,
    worktree: Path,
    image: str | None = None,
    allow_hosts: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> tuple[int, str]:
    """Run ``command`` in a smolvm guest with ``worktree`` mounted at /workspace."""
    cfg = weave_builder_config()
    sandbox = SmolSandbox(image=image or cfg.get("codex_image") or DEFAULT_CODEX_IMAGE)
    hosts = allow_hosts if allow_hosts is not None else list(cfg.get("builder_allow_hosts") or [])
    return sandbox.run(
        command,
        mount=worktree,
        allow_hosts=hosts,
        env=env,
        workdir=GUEST_MOUNT,
        timeout=timeout,
        net=True,
    )


def ensure_codex_image(image: str | None = None) -> str:
    """Return the Codex image ref; optionally ``smolvm pack pull`` when available."""
    cfg = weave_builder_config()
    ref = image or str(cfg.get("codex_image") or DEFAULT_CODEX_IMAGE)
    if shutil.which("smolvm") and resolve_sandbox() == "smolvm":
        # Best-effort warm pull; ignore failures (run may still pull).
        import subprocess

        out = Path("/tmp") / "codex-weave.smolmachine"
        try:
            subprocess.run(
                ["smolvm", "pack", "pull", ref, "-o", str(out)],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("codex pack pull skipped: %s", exc)
    return ref


def session_status() -> dict[str, Any]:
    return {
        "sandbox": resolve_sandbox(),
        "available": builder_runtime_available(),
        "smolvm": bool(shutil.which("smolvm")),
    }
