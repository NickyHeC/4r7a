"""Regression coverage for the public company-brain Click command tree."""

from __future__ import annotations

from click import Group
from click.testing import CliRunner

from company_brain.cli import main

EXPECTED_COMMAND_PATHS = {
    line
    for line in """
absorb
admin
admin console
admin doc-hygiene
admin expense-report
admin fleet
admin fleet clear-redeploy
admin fleet pause
admin fleet request-redeploy
admin fleet resume
admin fleet status
admin investor-newsletter
admin knowledge
admin knowledge approve
admin knowledge paste
admin maintain
admin manager
admin process-scout
admin self-heal
admin upstream-sync
admin wiki-commit
admin wiki-ops-audit
bridge
bridge issue-token
bridge manager
bridge rebuild-index
bridge revoke-token
bridge rollup
bridge serve
catalog
cleanup
crm
crm rebuild-registry
crm seed
crm sync-notion
discord
discord channel
discord channel list
discord gateway
discord manager
discord onboarding
discord onboarding estimate
discord onboarding run
discord sync-channels
doctor
doctor agents
doctor all
doctor bridge
doctor code
doctor connect
doctor llm
doctor naming
doctor ops
doctor wiki
finance
finance onboarding
finance onboarding run
github
github onboarding
github onboarding run
gmail
gmail onboarding
gmail onboarding run
google-ads
google-ads manager
google-ads onboarding
google-ads onboarding run
granola
granola onboarding
granola onboarding run
growth
growth activity-manager
growth competitor-manager
growth content-manager
growth draft
growth event
growth event partner
growth event plan
growth event register
growth event wrap
growth lead-manager
growth leads
growth leads enqueue
growth onboarding
growth published-pull
hr
hr confirm-offboard
hr manager
hr offboard
hr onboard
hr promote
hr status-watch
ingest
init
install
install cleanup
install credentials
install foundation
install onboard
install profile
install status
install verify
linear
linear onboarding
linear onboarding run
migrate-names
models
models budget
models configure
models spot-check
notion
notion manager
notion onboarding
notion onboarding run
notion sync-pull
posthog
posthog manager
posthog onboarding
posthog onboarding run
product
product attribution-manager
product docs-audit
product docs-manager
product newsletter
product onboarding
product progress
product progress-manager
product signup-match
product update-manager
product use-case-manager
product use-cases
query
slack
slack channel
slack channel enable-connect
slack channel list
slack channel tag
slack events
slack onboarding
slack onboarding estimate
slack onboarding run
slack sync-channels
slack thread-absorb
status
sync
weave
weave events
weave poll-approvals
""".splitlines()
    if line
}


def _command_paths(group: Group, prefix: tuple[str, ...] = ()) -> set[str]:
    paths: set[str] = set()
    for name, command in group.commands.items():
        parts = (*prefix, name)
        paths.add(" ".join(parts))
        if isinstance(command, Group):
            paths.update(_command_paths(command, parts))
    return paths


def test_complete_command_tree_is_preserved() -> None:
    assert _command_paths(main) == EXPECTED_COMMAND_PATHS


def test_important_groups_and_onboarding_paths_render_help() -> None:
    runner = CliRunner()
    paths = [
        "doctor",
        "admin",
        "slack",
        "weave",
        "product",
        "growth",
        "hr",
        "notion",
        "install",
        "github onboarding",
        "linear onboarding",
        "gmail onboarding",
        "granola onboarding",
        "finance onboarding",
        "discord onboarding",
        "posthog onboarding",
        "google-ads onboarding",
    ]

    for path in paths:
        result = runner.invoke(main, [*path.split(), "--help"])
        assert result.exit_code == 0, (path, result.output, result.exception)
