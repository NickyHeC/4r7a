"""Unit tests for task binding registry."""

from pathlib import Path

from company_brain.agents.engineering.linear.task_bindings import TaskBindingStore
from company_brain.wiki.store import LocalWikiStore


def test_task_binding_create_and_lookup(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    wiki_dir = tmp_path / "wiki"
    wiki = LocalWikiStore(root=wiki_dir)
    store = TaskBindingStore(config_dir=config_dir)

    binding = store.create_gmail_binding(
        message_id="msg1",
        thread_id="t1",
        mailbox="me",
        linear_issue={"id": "lin-uuid", "identifier": "ENG-1", "url": "https://linear.app/x/ENG-1"},
        title="Fix the bug",
        task_class="inbox_action",
        wiki_store=wiki,
        sync_notion=False,
    )

    assert binding.task_id
    assert store.get(binding.task_id) is not None
    assert store.find_by_gmail_message("msg1") is not None
    assert store.find_by_linear("ENG-1") is not None
    assert store.find_by_linear("lin-uuid") is not None
    assert wiki.exists(f"engineering/tasks/operations/general/{binding.task_id}.md")
    assert wiki.exists("engineering/tasks/_index.md")


def test_task_binding_idempotent_gmail(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    store = TaskBindingStore(config_dir=config_dir)
    issue = {"id": "a", "identifier": "ENG-2", "url": ""}
    first = store.create_gmail_binding(
        message_id="m2",
        thread_id="t2",
        mailbox="me",
        linear_issue=issue,
        title="One",
        mirror_wiki=False,
    )
    second = store.create_gmail_binding(
        message_id="m2",
        thread_id="t2",
        mailbox="me",
        linear_issue={**issue, "identifier": "ENG-2"},
        title="One updated",
        mirror_wiki=False,
    )
    assert first.task_id == second.task_id
    assert len(store.list_all()) == 1
