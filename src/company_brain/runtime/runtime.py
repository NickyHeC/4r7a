"""Agent runtime + deployment abstraction.

Managers dispatch specialist agents through an ``AgentRuntime`` instead of
instantiating and running them directly. Today the only runtime is
``LocalRuntime`` (in-process). The target state runs each agent in its own cloud
VM: ``CloudRuntime`` uses a pluggable ``AgentDeployer`` to spin up a VM, mount
the shared wiki volume, deploy the agent, run it, and tear the VM down — all
without changing agent code.

Default VM backends (override with ``COMPANY_BRAIN_VM_PROVIDER``):

- **local mode** — [smolvm](https://github.com/smol-machines/smolvm) (Smol
  Machines) for ephemeral local microVMs.
- **cloud mode** — [smol cloud](https://smolmachines.com/) (Smol Machines hosted
  fleet) via the ``smol machine`` CLI when no other provider is configured.

Any cloud VM service that satisfies the same requirements (CLI, agents can spin
up nested VMs, persistent machines with no idle billing, cron or persistent
managers) can be wired in as an alternate deployer.

Because agents keep state only in the shared wiki volume (and env), the same
agent runs identically in-process or on a spun-up VM.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from company_brain.config import AppConfig, resolve_runtime, resolve_vm_provider

logger = logging.getLogger(__name__)


@dataclass
class VMSpec:
    """Description of a VM to run an agent in (maps to ``Smolfile`` / ``VMSpec``)."""

    name: str
    image: str = "python:3.12"
    cpus: int = 2
    mem_mib: int = 4096
    allow_hosts: list[str] = field(default_factory=list)
    wiki_volume: str = "/workspace/wiki"
    env: dict[str, str] = field(default_factory=dict)


class AgentRuntime(ABC):
    """Runs an agent class with kwargs and returns its result."""

    @abstractmethod
    def run(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any: ...

    def start(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any:
        """Start a persistent/background agent without blocking (handoff).

        Unlike ``run`` (run-to-completion, returns the result), ``start`` launches
        a long-lived agent — typically a persistent manager whose loop idles until
        its next scheduled time — and returns immediately so the caller can start
        others and finish (e.g. an onboarding agent handing off to its managers).

        Default: run it in a daemon thread in-process. ``CloudRuntime`` will
        override this to spin up a dedicated VM per persistent agent.
        """
        import threading

        name = getattr(agent_cls, "name", agent_cls.__name__)

        def _target() -> None:
            try:
                agent_cls(config).execute(**kwargs)
            except Exception:  # pragma: no cover - background thread guard
                logger.exception("Persistent agent '%s' exited with error", name)

        thread = threading.Thread(target=_target, name=f"agent:{name}", daemon=True)
        thread.start()
        logger.info("Started persistent agent '%s' in the background", name)
        return thread


class AgentDeployer(ABC):
    """Manages VM lifecycle for running agents (no-op locally)."""

    @abstractmethod
    def ensure_vm(self, spec: VMSpec) -> str: ...

    @abstractmethod
    def spin_up(self, spec: VMSpec) -> str: ...

    @abstractmethod
    def deploy(self, agent_cls: type, vm: str, **kwargs: Any) -> Any: ...

    @abstractmethod
    def teardown(self, vm: str) -> None: ...


class LocalRuntime(AgentRuntime):
    """Instantiate the agent in-process and run its full lifecycle."""

    def run(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any:
        return agent_cls(config).execute(**kwargs)


class LocalDeployer(AgentDeployer):
    """No-op deployer for local execution."""

    def ensure_vm(self, spec: VMSpec) -> str:
        return "local"

    def spin_up(self, spec: VMSpec) -> str:
        return "local"

    def deploy(self, agent_cls: type, vm: str, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError("LocalDeployer does not deploy; use LocalRuntime.run")

    def teardown(self, vm: str) -> None:
        return None


class CloudDeployer(AgentDeployer):
    """Generic cloud VM deployer for non-default providers.

    Placeholder for alternate cloud VM services. Subclass or replace when wiring a
    provider other than smol cloud.
    """

    def ensure_vm(self, spec: VMSpec) -> str:
        raise NotImplementedError(_cloud_pending(resolve_vm_provider()))

    def spin_up(self, spec: VMSpec) -> str:
        raise NotImplementedError(_cloud_pending(resolve_vm_provider()))

    def deploy(self, agent_cls: type, vm: str, **kwargs: Any) -> Any:
        raise NotImplementedError(_cloud_pending(resolve_vm_provider()))

    def teardown(self, vm: str) -> None:
        raise NotImplementedError(_cloud_pending(resolve_vm_provider()))


class SmolCloudDeployer(AgentDeployer):
    """Deploys agents to smol cloud VMs via the ``smol machine`` CLI.

    Default cloud backend when ``COMPANY_BRAIN_VM_PROVIDER=smolcloud`` (the default
    in cloud mode). Placeholder until the smol cloud ``smol machine`` CLI is fully
    integrated: it will create/start a VM from a ``Smolfile``, mount the shared
    wiki volume, run the agent, and stop/destroy the VM. Invokable from a
    developer machine or from a manager VM spinning up specialist VMs on demand.
    """

    def ensure_vm(self, spec: VMSpec) -> str:
        raise NotImplementedError(_SMOL_CLOUD_PENDING)

    def spin_up(self, spec: VMSpec) -> str:
        raise NotImplementedError(_SMOL_CLOUD_PENDING)

    def deploy(self, agent_cls: type, vm: str, **kwargs: Any) -> Any:
        raise NotImplementedError(_SMOL_CLOUD_PENDING)

    def teardown(self, vm: str) -> None:
        raise NotImplementedError(_SMOL_CLOUD_PENDING)


class CloudRuntime(AgentRuntime):
    """Run an agent on a cloud VM (spin up, deploy, run, tear down).

    Uses the configured VM provider (default: smol cloud). Falls back to local
    in-process execution until the provider integration is ready.
    """

    def __init__(self, deployer: AgentDeployer | None = None):
        self._deployer = deployer or _deployer_for_provider(resolve_vm_provider())

    def run(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any:
        provider = resolve_vm_provider()
        logger.warning(
            "CloudRuntime not available yet (%s integration pending); "
            "running '%s' locally instead.",
            provider,
            getattr(agent_cls, "name", agent_cls.__name__),
        )
        return LocalRuntime().run(agent_cls, config, **kwargs)

    def start(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any:
        provider = resolve_vm_provider()
        logger.warning(
            "CloudRuntime not available yet (%s integration pending); "
            "starting '%s' in a local background thread instead of a dedicated VM.",
            provider,
            getattr(agent_cls, "name", agent_cls.__name__),
        )
        return super().start(agent_cls, config, **kwargs)


_SMOL_CLOUD_PENDING = (
    "smol cloud deployment is not available yet; the `smol machine` CLI integration "
    "is in development. Set COMPANY_BRAIN_RUNTIME=local for now."
)


def _cloud_pending(provider: str) -> str:
    return (
        f"Cloud VM deployment via provider '{provider}' is not integrated yet. "
        "Set COMPANY_BRAIN_RUNTIME=local or COMPANY_BRAIN_VM_PROVIDER=smolcloud."
    )


def _deployer_for_provider(provider: str) -> AgentDeployer:
    if provider == "smolcloud":
        return SmolCloudDeployer()
    return CloudDeployer()


def get_runtime(name: str | None = None) -> AgentRuntime:
    """Return the configured runtime (``local`` default, ``cloud`` when ready)."""
    name = (name or resolve_runtime()).lower()
    if name == "cloud":
        return CloudRuntime()
    return LocalRuntime()
