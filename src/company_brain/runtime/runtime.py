"""Agent runtime + deployment abstraction.

Managers dispatch specialist agents through an ``AgentRuntime`` instead of
instantiating and running them directly. Today the only runtime is
``LocalRuntime`` (in-process). The target state runs each agent in its own smol
cloud VM: ``SmolCloudRuntime`` will use the forthcoming ``smol machine`` CLI
(via an ``AgentDeployer``) to spin up a VM, mount the shared wiki volume, deploy
the agent, run it, and tear the VM down - all without changing agent code.

Because agents keep state only in the shared wiki volume (and env), the same
agent runs identically in-process or on a spun-up VM.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from company_brain.config import AppConfig, resolve_runtime

logger = logging.getLogger(__name__)


@dataclass
class VMSpec:
    """Description of a VM to run an agent in (maps to a Smolfile/`smol machine`)."""

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


class SmolCloudDeployer(AgentDeployer):
    """Deploys agents to smol cloud VMs via the `smol machine` CLI.

    Placeholder: the smol cloud service and `smol machine` CLI are still being
    built. When available this will shell out to `smol machine` to create/start
    a VM from a VMSpec (Smolfile), mount the shared wiki volume, run the agent,
    and stop/destroy the VM. Invokable from a developer machine or from another
    cloud VM (a manager VM spinning up specialist VMs on demand).
    """

    def ensure_vm(self, spec: VMSpec) -> str:
        raise NotImplementedError(_SMOL_PENDING)

    def spin_up(self, spec: VMSpec) -> str:
        raise NotImplementedError(_SMOL_PENDING)

    def deploy(self, agent_cls: type, vm: str, **kwargs: Any) -> Any:
        raise NotImplementedError(_SMOL_PENDING)

    def teardown(self, vm: str) -> None:
        raise NotImplementedError(_SMOL_PENDING)


class SmolCloudRuntime(AgentRuntime):
    """Run an agent on a smol cloud VM (spin up, deploy, run, tear down).

    Placeholder until the `smol machine` CLI lands; falls back to local execution
    so the system keeps working today.
    """

    def __init__(self, deployer: AgentDeployer | None = None):
        self._deployer = deployer or SmolCloudDeployer()

    def run(self, agent_cls: type, config: AppConfig, /, **kwargs: Any) -> Any:
        logger.warning(
            "SmolCloudRuntime not available yet (smol machine CLI pending); "
            "running '%s' locally instead.", getattr(agent_cls, "name", agent_cls.__name__)
        )
        return LocalRuntime().run(agent_cls, config, **kwargs)


_SMOL_PENDING = (
    "smol cloud deployment is not available yet; the `smol machine` CLI and cloud "
    "service are in development. Set COMPANY_BRAIN_RUNTIME=local for now."
)


def get_runtime(name: str | None = None) -> AgentRuntime:
    """Return the configured runtime (``local`` default, ``smolcloud`` when ready)."""
    name = (name or resolve_runtime()).lower()
    if name == "smolcloud":
        return SmolCloudRuntime()
    return LocalRuntime()
