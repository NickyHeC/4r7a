"""Agent runtime: run agents in-process today, on cloud VMs tomorrow."""

from company_brain.runtime import fleet_gate
from company_brain.runtime.builder_session import (
    builder_env_for_backend,
    builder_runtime_available,
    run_in_builder_vm,
)
from company_brain.runtime.runtime import (
    AgentDeployer,
    AgentRuntime,
    CloudDeployer,
    CloudRuntime,
    LocalDeployer,
    LocalRuntime,
    SmolCloudDeployer,
    get_runtime,
)
from company_brain.runtime.sandbox import SmolSandbox, VMSandbox, verify_in_sandbox

__all__ = [
    "AgentRuntime",
    "AgentDeployer",
    "LocalRuntime",
    "LocalDeployer",
    "CloudRuntime",
    "CloudDeployer",
    "SmolCloudDeployer",
    "get_runtime",
    "SmolSandbox",
    "VMSandbox",
    "verify_in_sandbox",
    "builder_runtime_available",
    "builder_env_for_backend",
    "run_in_builder_vm",
    "fleet_gate",
]
