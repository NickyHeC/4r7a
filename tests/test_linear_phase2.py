"""Unit tests for Linear structure organization proposal."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from company_brain.agents.engineering.linear.structure_organization import (
    StructureOrganizationAgent,
)
from company_brain.wiki.store import LocalWikiStore


def test_structure_proposal_writes_wiki(tmp_path: Path):
    wiki = LocalWikiStore(root=tmp_path / "wiki")
    (tmp_path / "wiki" / "operations").mkdir(parents=True)
    config = MagicMock()

    with patch(
        "company_brain.agents.engineering.linear.structure_organization.linear_client.list_teams",
        return_value=[{"key": "ENG", "name": "Engineering"}],
    ), patch(
        "company_brain.agents.engineering.linear.structure_organization.linear_client.linear_is_configured",
        return_value=True,
    ), patch.object(StructureOrganizationAgent, "_notify_slack"), patch(
        "company_brain.wiki.publish.LocalWikiStore",
        return_value=wiki,
    ):
        agent = StructureOrganizationAgent(config)
        with patch(
            "company_brain.agents.engineering.linear.structure_organization.resolve_wiki_dir",
            return_value=tmp_path / "wiki",
        ):
            result = agent.run(notify=False, sync=False)

    assert result["linear_teams"] == 1
    assert wiki.exists("engineering/linear/structure-proposal.md")
    body = wiki.read("engineering/linear/structure-proposal.md").body
    assert "Structure Proposal Proposal" in body
