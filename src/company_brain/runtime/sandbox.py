"""Sandboxed verification via smolvm.

Inspired by Ramp's self-maintaining system: reproduce/verify a change inside a
sandbox and only treat it as good once the check passes. The default local VM
backend is an ephemeral [smolvm](https://github.com/smol-machines/smolvm) microVM
(Smol Machines) with the wiki (or a copy of it) mounted at ``/workspace`` and egress
locked to an allow-list.

All smolvm use is optional: if ``COMPANY_BRAIN_SANDBOX`` is not ``smolvm`` or the
``smolvm`` binary is absent, ``SmolSandbox.available()`` is False and callers
fall back to in-process verification. Other VM backends can implement the same
contract when ``COMPANY_BRAIN_VM_PROVIDER`` points at a different local provider.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from company_brain.config import resolve_sandbox

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.12"
GUEST_MOUNT = "/workspace"
SMOLVM_BINARY = "smolvm"


class SmolSandbox:
    """Runs a command in an ephemeral smolvm microVM with a mounted directory."""

    def __init__(self, image: str = DEFAULT_IMAGE):
        self.image = image

    def available(self) -> bool:
        return resolve_sandbox() == "smolvm" and shutil.which(SMOLVM_BINARY) is not None

    def run(
        self,
        command: list[str],
        *,
        mount: Path,
        allow_hosts: list[str] | None = None,
        timeout: int = 600,
    ) -> tuple[int, str]:
        """Run ``command`` in an ephemeral VM with ``mount`` at /workspace.

        Returns (exit_code, combined_output). The VM is cleaned up on exit.
        """
        args = [SMOLVM_BINARY, "machine", "run", "--net"]
        for host in allow_hosts or []:
            args += ["--allow-host", host]
        args += ["--image", self.image, "-v", f"{mount}:{GUEST_MOUNT}", "--", *command]
        logger.debug("smolvm sandbox: %s", " ".join(args))
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("smolvm sandbox unavailable/timed out: %s", e)
            return 1, str(e)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# Alias kept for provider-agnostic call sites.
VMSandbox = SmolSandbox


def verify_in_sandbox(
    check_command: list[str],
    *,
    mount: Path,
    allow_hosts: list[str] | None = None,
) -> bool | None:
    """Run a verification command in a VM sandbox (default: smolvm).

    Returns True/False on the check result, or None when no sandbox is available
    (caller should then fall back to in-process verification).
    """
    sandbox = SmolSandbox()
    if not sandbox.available():
        return None
    code, output = sandbox.run(check_command, mount=mount, allow_hosts=allow_hosts)
    if code != 0:
        logger.info("Sandbox verification failed (exit %d): %s", code, output[-500:])
    return code == 0
