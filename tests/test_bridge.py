"""Tests for member bridge MCP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from company_brain.bridge.events import BridgeEvent, BridgeEventStore
from company_brain.bridge.index import rebuild_index
from company_brain.bridge.mcp_http import handle_jsonrpc
from company_brain.bridge.read_gate import ReadGate
from company_brain.bridge.tokens import BridgeTokenStore
from company_brain.bridge.tools import ToolContext, dispatch_tool
from company_brain.wiki.store import LocalWikiStore, MarkdownDoc


@pytest.fixture
def bridge_env(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    employee = tmp_path / "employee_wiki"
    config_dir = tmp_path / "config"
    wiki.mkdir()
    employee.mkdir()
    config_dir.mkdir()

    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    monkeypatch.setenv("COMPANY_BRAIN_EMPLOYEE_WIKI_DIR", str(employee))

    (config_dir / "bridge.yaml").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "bridge.yaml").read_text()
    )
    (config_dir / "members.yaml").write_text(
        "members:\n  alice:\n    email: alice@co.com\n"
        "    bridge:\n      departments: [engineering]\n"
    )

    # Company pages
    store = LocalWikiStore(root=wiki)
    store.write(
        "engineering/practices/prompts.md",
        MarkdownDoc(
            frontmatter={"title": "Prompts", "sync": "location:engineering"},
            body="Use structured prompts.",
        ),
    )
    store.write(
        "engineering/priorities/lead-focus.md",
        MarkdownDoc(
            frontmatter={"title": "Lead Focus", "sync": "company"},
            body="Eng lead: ship bridge. Product lead: priorities UI.",
        ),
    )
    store.write(
        "engineering/practices/skills/_index.yaml",
        MarkdownDoc(
            frontmatter={"title": "Skills Index", "sync": "location:engineering"},
            body=yaml.safe_dump(
                {
                    "skills": [
                        {
                            "id": "test-skill",
                            "title": "Test Skill",
                            "path": "engineering/practices/skills/test-skill.md",
                        }
                    ]
                }
            ),
        ),
    )
    store.write(
        "engineering/practices/skills/test-skill.md",
        MarkdownDoc(
            frontmatter={"title": "Test Skill", "sync": "location:engineering"},
            body="Skill body content.",
        ),
    )

    import company_brain.bridge.config as bridge_cfg_mod
    import company_brain.config as cfg_mod
    import company_brain.members_config as members_mod

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(bridge_cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(members_mod, "CONFIG_DIR", config_dir)
    bridge_cfg_mod.load_bridge_config.cache_clear()

    return {"wiki": wiki, "employee": employee, "config_dir": config_dir}


def test_read_gate_department_scoped(bridge_env):
    gate = ReadGate("alice")
    assert gate.can_read(
        "engineering/practices/prompts.md",
        "location:engineering",
        volume="company",
    )
    assert not gate.can_read(
        "finance/vendor/acme.md",
        "location:finance",
        volume="company",
    )
    assert gate.can_read(
        "engineering/priorities/lead-focus.md",
        "company",
        volume="company",
    )


def test_token_issue_and_verify(bridge_env):
    store = BridgeTokenStore()
    plain = store.issue("alice")
    assert store.verify(plain) == "alice"
    assert store.verify("wrong") is None
    store.revoke("alice")
    assert store.verify(plain) is None


def test_report_blocker_and_idempotency(bridge_env):
    ctx = ToolContext.for_member("alice", bridge_env["config_dir"])
    out = dispatch_tool(
        ctx,
        "report_blocker",
        {
            "title": "API down",
            "area": "payments",
            "severity": "high",
            "idempotency_key": "abc123",
        },
    )
    assert out["status"] == "accepted"
    dup = dispatch_tool(
        ctx,
        "report_blocker",
        {
            "title": "API down",
            "area": "payments",
            "severity": "high",
            "idempotency_key": "abc123",
        },
    )
    assert dup["status"] == "duplicate"


def test_materializer_and_rollup(bridge_env, monkeypatch):
    from company_brain.agents.bridge.blocker_rollup import BlockerRollupAgent
    from company_brain.agents.bridge.bridge_event_materializer import (
        BridgeEventMaterializerAgent,
    )
    from company_brain.config import load_config

    event = BridgeEvent.create_blocker(
        member="alice",
        title="DB migration blocked",
        area="platform",
        severity="medium",
    )
    BridgeEventStore().append(event)

    config = load_config()
    BridgeEventMaterializerAgent(config).execute(event=event)
    result = BlockerRollupAgent(config).execute()
    assert result["blockers"] >= 1

    rollup = LocalWikiStore(root=bridge_env["wiki"]).read("engineering/priorities/blockers.md")
    assert "DB migration blocked" in rollup.body
    assert rollup.frontmatter.get("sync") == "location:engineering"


def test_mcp_tools_call(bridge_env):
    BridgeTokenStore().issue("alice")
    resp = handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_skills",
                "arguments": {},
            },
        },
        member="alice",
    )
    assert "error" not in resp
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert "engineering" in data["departments"]


def test_rebuild_index(bridge_env):
    index = rebuild_index(config_dir=bridge_env["config_dir"])
    assert any("practices" in e.rel_path for e in index.entries)
    assert "engineering" in index.skills
