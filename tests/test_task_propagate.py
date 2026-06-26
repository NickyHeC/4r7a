"""Unit tests for task propagation ledger."""

from pathlib import Path

from company_brain.agents.engineering.linear.task_bindings import TaskBinding, TaskBindingStore
from company_brain.agents.engineering.linear.task_propagate import (
    is_terminal_linear_status,
    pending_propagations,
    record_status_change,
    should_propagate_field,
)


def test_terminal_status_detection():
    assert is_terminal_linear_status("Done") is True
    assert is_terminal_linear_status("canceled") is True
    assert is_terminal_linear_status("In Progress") is False


def test_done_propagates_once(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    store = TaskBindingStore(config_dir=config_dir)
    binding = TaskBinding(
        task_id="t1",
        origin={"platform": "gmail", "artifact_id": "m1", "department": "operations"},
        linear={"issue_id": "l1", "identifier": "ENG-9", "url": ""},
        platforms={"gmail": {"message_id": "m1", "archived": False}},
        task_class="inbox_action",
        title="Test",
    )
    store.upsert(binding, mirror_wiki=False)

    record_status_change(
        binding,
        platform="linear",
        field="status",
        value="Done",
        source="system:linear_completed",
        store=store,
        mirror_wiki=False,
    )
    assert should_propagate_field(binding, "linear", "status", "Done") is False
    assert pending_propagations(binding) == []


def test_echo_ignored_after_system_archive(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    store = TaskBindingStore(config_dir=config_dir)
    binding = store.create_gmail_binding(
        message_id="m3",
        thread_id="t3",
        mailbox="me",
        linear_issue={"id": "l3", "identifier": "ENG-3", "url": ""},
        title="Echo test",
        mirror_wiki=False,
    )

    record_status_change(
        binding,
        platform="gmail",
        field="archived",
        value=True,
        source="system:linear_completed",
        store=store,
        mirror_wiki=False,
    )
    before = len(binding.status_track)
    record_status_change(
        binding,
        platform="gmail",
        field="archived",
        value=True,
        source="gmail",
        store=store,
        mirror_wiki=False,
    )
    assert len(binding.status_track) == before
