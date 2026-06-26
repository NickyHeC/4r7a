"""Tests for Notion task platform (Phase 5)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from company_brain.agents.engineering.linear.linear_completed.dispatcher import (
    LinearCompletedAgent,
)
from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.agents.operations.notion import notion_db, notion_task_config
from company_brain.agents.operations.notion.notion_task_scanner import NotionTaskScannerAgent
from company_brain.agents.operations.notion.notion_task_sync import (
    NotionTaskSyncAgent,
    linear_status_to_notion,
)
from company_brain.config import NotionConfig, TaskDatabaseColumns, TaskDatabaseSpec, TaskRoutingRule


def _notion_config_with_db(db_id: str = "db-eng") -> NotionConfig:
    return NotionConfig(
        task_databases={
            "engineering": TaskDatabaseSpec(
                database_id=db_id,
                columns=TaskDatabaseColumns(),
            ),
        },
        task_routing=[
            TaskRoutingRule(match={"department": "operations"}, database="engineering"),
        ],
    )


def test_resolve_database_key_by_routing():
    notion = _notion_config_with_db()
    key = notion_task_config.resolve_database_key("operations", "general", notion=notion)
    assert key == "engineering"


def test_linear_status_mapping():
    assert linear_status_to_notion("Done") == "Done"
    assert linear_status_to_notion("canceled") == "Canceled"


def test_scanner_links_existing_row(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_granola_binding(
        note_id="n1:action",
        meeting_date="2026-06-01",
        linear_issue={"id": "l1", "identifier": "ENG-42", "url": "https://linear/42"},
        title="Meeting task",
        mirror_wiki=False,
    )

    config = MagicMock()
    config.notion = _notion_config_with_db()
    agent = NotionTaskScannerAgent(config)

    row = {
        "id": "page-99",
        "url": "https://notion.so/page-99",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Existing task"}]},
            "Linear ID": {"type": "rich_text", "rich_text": [{"plain_text": "ENG-42"}]},
            "Status": {"type": "status", "status": {"name": "In progress"}},
        },
    }

    with patch.object(agent, "_client"), patch(
        "company_brain.agents.operations.notion.notion_task_scanner.notion_db.notion_is_available",
        return_value=True,
    ), patch(
        "company_brain.agents.operations.notion.notion_task_scanner.notion_db.query_database_updated_since",
        return_value=[row],
    ):
        result = agent.run_once()

    assert result["linked"] == 1
    updated = store.get(binding.task_id)
    assert updated.platforms["notion"]["page_id"] == "page-99"
    assert store.find_by_notion_page("page-99") is not None


def test_scanner_does_not_duplicate_link(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_granola_binding(
        note_id="n2:action",
        meeting_date="2026-06-01",
        linear_issue={"id": "l2", "identifier": "ENG-43", "url": ""},
        title="Already linked",
        mirror_wiki=False,
    )
    binding.platforms["notion"] = {
        "database_key": "engineering",
        "page_id": "page-43",
        "url": "https://notion.so/page-43",
    }
    store.upsert(binding, mirror_wiki=False)

    config = MagicMock()
    config.notion = _notion_config_with_db()
    agent = NotionTaskScannerAgent(config)
    row = {
        "id": "page-43",
        "properties": {
            "Linear ID": {"type": "rich_text", "rich_text": [{"plain_text": "ENG-43"}]},
        },
    }

    with patch(
        "company_brain.agents.operations.notion.notion_task_scanner.notion_db.notion_is_available",
        return_value=True,
    ), patch(
        "company_brain.agents.operations.notion.notion_task_scanner.notion_db.query_database_updated_since",
        return_value=[row],
    ):
        result = agent.run_once()

    assert result["linked"] == 0


def test_notion_sync_updates_status(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_granola_binding(
        note_id="n3:action",
        meeting_date="2026-06-01",
        linear_issue={"id": "l3", "identifier": "ENG-44", "url": ""},
        title="Sync me",
        mirror_wiki=False,
    )
    binding.platforms["notion"] = {
        "database_key": "engineering",
        "page_id": "page-44",
        "url": "https://notion.so/page-44",
    }
    store.upsert(binding, mirror_wiki=False)

    config = MagicMock()
    config.notion = _notion_config_with_db()
    agent = NotionTaskSyncAgent(config)

    with patch(
        "company_brain.agents.operations.notion.notion_task_sync.notion_db.notion_is_available",
        return_value=True,
    ), patch(
        "company_brain.agents.operations.notion.notion_task_sync.task_class_fan_out",
        return_value=["linear", "notion"],
    ), patch(
        "company_brain.agents.operations.notion.notion_task_sync.notion_db.update_database_row",
        return_value={"id": "page-44"},
    ) as update_mock:
        result = agent.run(binding=binding, linear_status="Done")

    assert result["status"] == "updated"
    update_mock.assert_called_once()
    assert update_mock.call_args.kwargs["status"] == "Done"


def test_notion_sync_creates_row_when_missing(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_granola_binding(
        note_id="n4:action",
        meeting_date="2026-06-01",
        linear_issue={"id": "l4", "identifier": "ENG-45", "url": ""},
        title="Create row",
        mirror_wiki=False,
    )

    config = MagicMock()
    config.notion = _notion_config_with_db()
    agent = NotionTaskSyncAgent(config)

    with patch(
        "company_brain.agents.operations.notion.notion_task_sync.notion_db.notion_is_available",
        return_value=True,
    ), patch(
        "company_brain.agents.operations.notion.notion_task_sync.task_class_fan_out",
        return_value=["linear", "notion"],
    ), patch(
        "company_brain.agents.operations.notion.notion_task_sync.notion_db.create_database_row",
        return_value={"id": "page-new", "url": "https://notion.so/page-new"},
    ):
        result = agent.run(binding=binding, title="Create row", create_if_missing=True)

    assert result["status"] == "created"
    updated = store.get(binding.task_id)
    assert updated.platforms["notion"]["page_id"] == "page-new"


def test_linear_completed_dispatches_notion(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "company_brain.agents.engineering.linear.task_bindings.CONFIG_DIR",
        config_dir,
    )
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_granola_binding(
        note_id="n5:action",
        meeting_date="2026-06-01",
        linear_issue={"id": "l5", "identifier": "ENG-46", "url": ""},
        title="Complete me",
        mirror_wiki=False,
    )
    binding.platforms["notion"] = {"page_id": "page-46", "database_key": "engineering"}
    store.upsert(binding, mirror_wiki=False)

    config = MagicMock()
    config.notion = _notion_config_with_db()
    agent = LinearCompletedAgent(config)

    with patch(
        "company_brain.agents.engineering.linear.linear_completed.dispatcher.task_class_fan_out",
        return_value=["linear", "notion"],
    ), patch(
        "company_brain.agents.operations.notion.notion_task_sync.NotionTaskSyncAgent.run",
        return_value={"status": "updated"},
    ) as sync_run:
        result = agent.run(
            task_id=binding.task_id,
            linear_issue={"id": "l5", "state": {"name": "Done"}},
        )

    assert result["platforms"]["notion"]["status"] == "updated"
    sync_run.assert_called_once()


def test_build_property_patch_status():
    schema = {"Status": "status", "Name": "title"}
    prop = notion_db.build_property_patch("Status", "Done", schema=schema)
    assert prop["Status"]["status"]["name"] == "Done"
