"""Configuration loading and validation for company-brain."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
PROJECT_ROOT = CONFIG_DIR.parent


def resolve_wiki_dir() -> Path:
    """Directory holding the Markdown wiki (the source of truth).

    Override with ``COMPANY_BRAIN_WIKI_DIR`` (e.g. ``/workspace/wiki`` on a cloud
    VM, pointing at the mounted persistent volume). Defaults to ``<root>/wiki``.
    """
    env = os.getenv("COMPANY_BRAIN_WIKI_DIR")
    return Path(env) if env else PROJECT_ROOT / "wiki"


def resolve_employee_wiki_dir() -> Path:
    """Directory holding per-member employee wikis (sibling to company wiki).

    Override with ``COMPANY_BRAIN_EMPLOYEE_WIKI_DIR`` (e.g.
    ``/workspace/employee_wiki``). Defaults to ``<wiki_parent>/employee_wiki``.
    """
    env = os.getenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR")
    if env:
        return Path(env)
    wiki = resolve_wiki_dir()
    if wiki.name == "wiki":
        return wiki.parent / "employee_wiki"
    return wiki / "employee_wiki"


def resolve_raw_dir() -> Path:
    """Directory holding raw ingested Markdown entries."""
    env = os.getenv("COMPANY_BRAIN_RAW_DIR")
    return Path(env) if env else PROJECT_ROOT / "raw"


def resolve_runtime() -> str:
    """Agent runtime selector: ``local`` (in-process) or ``cloud`` (VM fleet)."""
    return os.getenv("COMPANY_BRAIN_RUNTIME", "local").strip().lower()


def resolve_vm_provider() -> str:
    """VM backend when agents run inside VMs.

    Defaults: ``smolvm`` in local mode (smolvm microVMs for sandbox/local VM work),
    ``smolcloud`` in cloud mode (Smol Machines hosted fleet via ``smol machine``).
    Override with ``COMPANY_BRAIN_VM_PROVIDER`` to use another service that meets
    the same requirements (CLI, nested VM spin-up, persistent VMs, cron or persistent
    managers).
    """
    explicit = os.getenv("COMPANY_BRAIN_VM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    return "smolcloud" if resolve_mode() == "cloud" else "smolvm"


def resolve_mode() -> str:
    """Deployment mode: ``local`` or ``cloud``.

    Explicit ``COMPANY_BRAIN_MODE`` wins. Otherwise inferred as ``cloud`` when the
    wiki dir lives under ``/workspace`` (the mounted cloud VM volume), else
    ``local`` (wiki Markdown stored inside the project folder, gitignored).
    """
    explicit = os.getenv("COMPANY_BRAIN_MODE", "").strip().lower()
    if explicit in ("local", "cloud"):
        return explicit
    return "cloud" if str(resolve_wiki_dir()).startswith("/workspace") else "local"


def resolve_sandbox() -> str:
    """Sandbox backend for verification: ``off`` (in-process) or ``smolvm``.

    When ``smolvm`` is selected, state-changing agents can verify/reproduce a
    change inside an ephemeral smolvm microVM before committing it.
    """
    return os.getenv("COMPANY_BRAIN_SANDBOX", "off").strip().lower()


def resolve_llm_provider() -> str:
    """Active LLM provider key: ``anthropic`` | ``openai`` | ``glm`` (or custom).

    Explicit ``COMPANY_BRAIN_LLM_PROVIDER`` wins; otherwise falls back to the
    ``default_provider`` declared in ``config/models.yaml``. This is the single
    knob that switches the model powering every agent (hosted provider keys, or a
    self-hosted/remote open-source GLM-5 endpoint).
    """
    env = os.getenv("COMPANY_BRAIN_LLM_PROVIDER", "").strip().lower()
    if env:
        return env
    return (load_models_config().default_provider or "anthropic").strip().lower()


class ArticleTypeConfig(BaseModel):
    structure: list[str] = Field(default_factory=list)
    length_target: list[int] = Field(default_factory=lambda: [20, 80])


class SectionConfig(BaseModel):
    label: str
    description: str = ""
    article_type: str
    icon: str = ""


class WritingStandards(BaseModel):
    tone: str = "factual"
    organize_by: str = "theme"
    max_quotes_per_article: int = 3
    banned_words: list[str] = Field(default_factory=list)


class WikiConfig(BaseModel):
    wiki_name: str = "Company Wiki"
    sections: dict[str, SectionConfig] = Field(default_factory=dict)
    article_types: dict[str, ArticleTypeConfig] = Field(default_factory=dict)
    writing_standards: WritingStandards = Field(default_factory=WritingStandards)

    def get_section_for_type(self, article_type: str) -> str | None:
        """Return the section key that houses a given article type."""
        for key, section in self.sections.items():
            if section.article_type == article_type:
                return key
        return None

    def get_type_config(self, article_type: str) -> ArticleTypeConfig:
        return self.article_types.get(article_type, ArticleTypeConfig())


class DiscoveryState(BaseModel):
    strategy: str | None = None
    scanned_at: str | None = None
    existing_page_count: int = 0
    adopted_page_ids: list[str] = Field(default_factory=list)


class TaskDatabaseColumns(BaseModel):
    """Notion property names for a task database (values vary per workspace)."""

    title: str = "Name"
    status: str = "Status"
    assignee: str = "Owner"
    due: str = "Due"
    linear: str = "Linear ID"


class TaskDatabaseSpec(BaseModel):
    database_id: str = ""
    columns: TaskDatabaseColumns = Field(default_factory=TaskDatabaseColumns)


class CrmDatabaseColumns(BaseModel):
    """Notion property names for CRM database rows (contacts or inbound)."""

    title: str = "Name"
    segment: str = "Segment"
    email: str = "Email"
    main_connection: str = "Main connection"
    status: str = "Status"
    contact: str = "Contact"
    score: str = "Score"
    received: str = "Received"


class CrmDatabaseSpec(BaseModel):
    database_id: str = ""
    columns: CrmDatabaseColumns = Field(default_factory=CrmDatabaseColumns)


class TaskRoutingRule(BaseModel):
    match: dict[str, str] = Field(default_factory=dict)
    database: str = ""


class NotionConfig(BaseModel):
    workspace_id: str | None = None
    root_page_id: str | None = None
    section_page_ids: dict[str, str] = Field(default_factory=dict)
    tracking_database_id: str | None = None
    task_databases: dict[str, TaskDatabaseSpec] = Field(default_factory=dict)
    task_routing: list[TaskRoutingRule] = Field(default_factory=list)
    discovery: DiscoveryState = Field(default_factory=DiscoveryState)
    # Member read access is delegated to Notion teamspaces (access levels are set
    # in Notion by the admin). ``teamspaces`` maps a teamspace key -> the parent
    # page id pages sync under; ``section_teamspace`` maps a wiki section (exact or
    # path prefix) -> a teamspace key, or the literal "admin_only" to keep that
    # section MD-only (never mirrored to Notion).
    teamspaces: dict[str, str] = Field(default_factory=dict)
    section_teamspace: dict[str, str] = Field(default_factory=dict)
    crm_databases: dict[str, CrmDatabaseSpec] = Field(default_factory=dict)
    change_request_database: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_initialized(self) -> bool:
        return self.root_page_id is not None

    def teamspace_for_section(self, section: str) -> str | None:
        """Return the teamspace key (or 'admin_only') for a section, by longest path prefix."""
        if not self.section_teamspace:
            return None
        section = (section or "").strip("/")
        candidates = [
            k
            for k in self.section_teamspace
            if section == k or section.startswith(k + "/") or k == ""
        ]
        if not candidates:
            return None
        best = max(candidates, key=len)
        return self.section_teamspace[best]


class ProviderSpec(BaseModel):
    """One entry in ``config/models.yaml`` ``providers``.

    ``sdk`` declares which agent SDK drives this provider: ``claude`` (Anthropic
    Claude Agent SDK) or ``openai`` (OpenAI Agents SDK, also used for any
    OpenAI-compatible endpoint such as a self-hosted/remote GLM-5 server).
    ``model`` is an optional default model id (overridable via
    ``COMPANY_BRAIN_LLM_MODEL``); blank means the SDK's own default.
    """

    sdk: str = "claude"
    model: str | None = None


class TokenBudgetSpec(BaseModel):
    """Monthly LLM spend cap for 4r7a operations.

    Covers all API token spend for running the product:
    - **runtime** — specialist agents (absorb, draft_reply, finance LLM agents, …)
    - **builder** — autonomous coding agents that edit 4r7a from human feedback
      (future cloud Inspect-style agent; same monthly pool, tagged separately in usage)

    ``guidance_usd`` is for doctor reporting only (soft targets); enforcement uses
    ``monthly_usd`` as one hard pool. Per-run caps live in ``run_limits``.
    """

    enabled: bool = False
    monthly_usd: float = 250.0
    alert_threshold_percent: int = 80
    hard_stop: bool = True
    admin_channel: str = "#wiki-admin"
    guidance_usd: dict[str, float] = Field(
        default_factory=lambda: {"runtime": 200.0, "builder": 50.0},
    )


class ModelRateSpec(BaseModel):
    """USD per 1M tokens for cost estimation when APIs omit dollar amounts."""

    input_per_million: float = 3.0
    output_per_million: float = 15.0


class SpendCategoriesSpec(BaseModel):
    """Maps agent names to spend buckets (``runtime`` or ``builder``)."""

    default: str = "runtime"
    agents: dict[str, str] = Field(default_factory=lambda: {"builder": "builder"})


class RunLimitValues(BaseModel):
    """Per-run runtime caps (enforced outside the agent, not in prompts)."""

    max_usd_per_run: float | None = None
    max_steps_per_run: int | None = None
    max_tool_calls_per_run: int | None = None


class RunLimitsSpec(BaseModel):
    """Resolved per agent: defaults ← tier ← agent override ← builder profile."""

    defaults: RunLimitValues = Field(
        default_factory=lambda: RunLimitValues(
            max_usd_per_run=0.50,
            max_steps_per_run=20,
            max_tool_calls_per_run=40,
        ),
    )
    tiers: dict[str, RunLimitValues] = Field(default_factory=dict)
    agents: dict[str, RunLimitValues] = Field(default_factory=dict)
    builder: RunLimitValues = Field(
        default_factory=lambda: RunLimitValues(
            max_usd_per_run=10.0,
            max_steps_per_run=80,
            max_tool_calls_per_run=200,
        ),
    )


class EvalSpotcheckSpec(BaseModel):
    """Periodic vibe evals posted to Slack for human spot-checking."""

    enabled: bool = True
    channel: str = "#wiki"
    agents: list[str] = Field(
        default_factory=lambda: ["budget_report", "draft_reply", "absorb"],
    )


class ModelsConfig(BaseModel):
    """LLM provider configuration loaded from ``config/models.yaml``."""

    default_provider: str = "anthropic"
    mode: str = "balanced"  # balanced | performance
    tiers: dict[str, dict[str, str]] = Field(default_factory=dict)
    agents: dict[str, str] = Field(default_factory=dict)
    agent_providers: dict[str, str] = Field(default_factory=dict)
    fallback_chains: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    token_budget: TokenBudgetSpec = Field(default_factory=TokenBudgetSpec)
    spend_categories: SpendCategoriesSpec = Field(default_factory=SpendCategoriesSpec)
    run_limits: RunLimitsSpec = Field(default_factory=RunLimitsSpec)
    model_rates: dict[str, ModelRateSpec] = Field(default_factory=dict)
    eval_spotcheck: EvalSpotcheckSpec = Field(default_factory=EvalSpotcheckSpec)
    providers: dict[str, ProviderSpec] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Top-level config holding both wiki and notion configs."""

    wiki: WikiConfig
    notion: NotionConfig

    def section_notion_id(self, section_key: str) -> str | None:
        return self.notion.section_page_ids.get(section_key)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data or {}


def load_yaml_config(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load ``config/<name>.yaml`` as a plain dict (empty dict if absent).

    The single loader for non-secret department/feature YAML configs (finance,
    operations, ...). New YAML configs should read through this instead of
    re-implementing a loader. Secrets stay in the environment, never these files.
    """
    return _load_yaml((config_dir or CONFIG_DIR) / f"{name}.yaml")


def save_yaml_config(name: str, data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Persist a plain-dict YAML config back to ``config/<name>.yaml``."""
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_wiki_config(config_dir: Path | None = None) -> WikiConfig:
    path = (config_dir or CONFIG_DIR) / "wiki.yaml"
    return WikiConfig(**_load_yaml(path))


def load_notion_config(config_dir: Path | None = None) -> NotionConfig:
    path = (config_dir or CONFIG_DIR) / "notion.yaml"
    return NotionConfig(**_load_yaml(path))


def load_models_config(config_dir: Path | None = None) -> ModelsConfig:
    """Load LLM provider config from ``config/models.yaml`` (defaults if absent)."""
    path = (config_dir or CONFIG_DIR) / "models.yaml"
    data = _load_yaml(path)
    if not data:
        return ModelsConfig()
    return ModelsConfig(**data)


def save_models_config(config: ModelsConfig, config_dir: Path | None = None) -> None:
    """Persist ``config/models.yaml``."""
    path = (config_dir or CONFIG_DIR) / "models.yaml"
    data = config.model_dump(mode="json", exclude_none=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_config(config_dir: Path | None = None) -> AppConfig:
    return AppConfig(
        wiki=load_wiki_config(config_dir),
        notion=load_notion_config(config_dir),
    )


def save_notion_config(config: NotionConfig, config_dir: Path | None = None) -> None:
    """Write the notion config back to disk."""
    path = (config_dir or CONFIG_DIR) / "notion.yaml"
    data = config.model_dump(mode="json")
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
