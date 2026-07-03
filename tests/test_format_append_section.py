"""Tests for append-mode run context formatting."""

from company_brain.wiki.publish import format_append_section


def test_format_append_section_includes_context():
    section = format_append_section(
        "Week of 2026-07-02",
        "- commit one\n",
        trigger="github_manager",
        why="7 commits scanned",
    )
    assert "## Week of 2026-07-02" in section
    assert "**Trigger:** github_manager" in section
    assert "**Why:** 7 commits scanned" in section
    assert "- commit one" in section
