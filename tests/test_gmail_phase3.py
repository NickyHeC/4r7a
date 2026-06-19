"""Unit tests for Phase-3 contact list parsing."""

from company_brain.agents.operations.shared.contact_lists import load_contacts, matches_contact


def test_matches_email_and_domain(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "ops.md"
    path.write_text(
        "# CRM\n\n- partner@acme.com\n- acme.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COMPANY_BRAIN_WIKI_DIR", str(wiki))
    emails, domains = load_contacts("ops.md")
    assert "partner@acme.com" in emails
    assert "acme.com" in domains
    assert matches_contact("Jane <partner@acme.com>", emails, domains)
    assert matches_contact("billing@vendor.acme.com", emails, domains)
