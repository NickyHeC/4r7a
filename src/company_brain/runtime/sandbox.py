"""Sandboxed verification via ephemeral cloud VMs.

Inspired by Ramp's self-maintaining system: reproduce/verify a change inside a
sandbox and only treat it as good once the check passes. Here the sandbox is an
ephemeral cloud VM with the wiki (or a copy of it) mounted at ``/workspace`` and
egress locked to an allow-list.

All VM sandbox use is optional: if ``COMPANY_BRAIN_SANDBOX`` is not ``vm`` or the
VM provider binary is absent, ``VMSandbox.available()`` is False and callers
fall back to in-process verification.
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
VM_BINARY = "vm"


class VMSandbox:
    """Runs a command in an ephemeral cloud VM with a mounted directory."""

    def __init__(self, image: str = DEFAULT_IMAGE):
        self.image = image

    def available(self) -> bool:
        return resolve_sandbox() == "vm" and shutil.which(VM_BINARY) is not None

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
        args = [VM_BINARY, "run", "--net"]
        for host in allow_hosts or []:
            args += ["--allow-host", host]
        args += ["--image", self.image, "-v", f"{mount}:{GUEST_MOUNT}", "--", *command]
        logger.debug("VM sandbox: %s", " ".join(args))
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("VM sandbox unavailable/timed out: %s", e)
            return 1, str(e)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def verify_in_sandbox(
    check_command: list[str],
    *,
    mount: Path,
    allow_hosts: list[str] | None = None,
) -> bool | None:
    """Run a verification command in a VM sandbox.

    Returns True/False on the check result, or None when no sandbox is available
    (caller should then fall back to in-process verification).
    """
    sandbox = VMSandbox()
    if not sandbox.available():
        return None
    code, output = sandbox.run(check_command, mount=mount, allow_hosts=allow_hosts)
    if code != 0:
        logger.info("Sandbox verification failed (exit %d): %s", code, output[-500:])
    return code == 0
