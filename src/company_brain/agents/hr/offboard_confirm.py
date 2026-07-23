"""Offboard Confirm — admin-confirmed departure actuation.

Sets ``status: departed``, revokes bridge token, stops ingest, records
``departed_at`` for the T+30 wiki archive timer. Does not remove Workspace /
Notion accounts (stubs only).

SDK: Neither (config + bridge + wiki).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.hr.hiring_log import append_hiring_log
from company_brain.bridge.tokens import BridgeTokenStore
from company_brain.members_config import MemberIngestConfig, load_members_config, update_member
from company_brain.roster_config import load_roster_config, save_roster_config
from company_brain.wiki.publish import UPDATE, write_wiki_page

PROPOSAL_DIR = "hr/offboard-proposal"


class OffboardConfirmAgent(BaseAgent):
    """Actuate offboarding after admin confirmation."""

    name = "offboard_confirm"
    WRITE_MODE = UPDATE

    def run(
        self,
        *,
        member_key: str,
        reason: str = "admin_confirm",
        **kwargs: Any,
    ) -> dict[str, Any]:
        key = (member_key or "").strip()
        if not key:
            return {"status": "error", "reason": "member_key_required"}

        now = datetime.now(timezone.utc).isoformat()
        members = load_members_config()
        roster = load_roster_config()

        if key in members.members:
            return self._confirm_member(key, reason=reason, now=now)
        if key in roster.people:
            return self._confirm_roster(key, reason=reason, now=now)
        return {"status": "skipped", "reason": "unknown_person"}

    def _confirm_member(self, key: str, *, reason: str, now: str) -> dict[str, Any]:
        spec = load_members_config().get(key)
        if spec is None:
            return {"status": "skipped", "reason": "unknown_member"}
        if not spec.is_active and spec.departed_at:
            return {
                "status": "skipped",
                "reason": "already_departed",
                "departed_at": spec.departed_at,
            }

        update_member(
            key,
            status="departed",
            departed_at=now,
            wiki_archived=False,
            ingest=MemberIngestConfig(granola="off", gmail="off", slack="off").model_dump(),
        )

        revoked = BridgeTokenStore().revoke(key)
        self._mark_proposal_confirmed(key, reason=reason, now=now)
        append_hiring_log(
            f"Departed — {key}",
            f"- **Confirmed at:** {now}\n- **Reason:** {reason}\n"
            f"- **Bridge token revoked:** {revoked}\n"
            "- **Wiki archive:** scheduled (see `departed_at` + archive_delay_days)",
            trigger="offboard_confirm",
            why=key,
        )
        return {
            "status": "ok",
            "member": key,
            "departed_at": now,
            "bridge_revoked": revoked,
            "kind": "member",
        }

    def _confirm_roster(self, key: str, *, reason: str, now: str) -> dict[str, Any]:
        roster = load_roster_config()
        person = roster.people.get(key)
        if person is None:
            return {"status": "skipped", "reason": "unknown_roster"}
        if (person.status or "").lower() == "departed" and person.departed_at:
            return {
                "status": "skipped",
                "reason": "already_departed",
                "departed_at": person.departed_at,
            }

        person.status = "departed"
        person.departed_at = now
        roster.people[key] = person
        save_roster_config(roster)

        # Roster has no bridge token; revoke no-ops if somehow issued.
        revoked = BridgeTokenStore().revoke(key)
        self._mark_proposal_confirmed(key, reason=reason, now=now)
        append_hiring_log(
            f"Departed — {key}",
            f"- **Confirmed at:** {now}\n- **Reason:** {reason}\n"
            f"- **Employment type:** {person.employment_type}\n"
            f"- **Bridge token revoked:** {revoked}",
            trigger="offboard_confirm",
            why=key,
        )
        return {
            "status": "ok",
            "member": key,
            "departed_at": now,
            "bridge_revoked": revoked,
            "kind": "roster",
        }

    def _mark_proposal_confirmed(self, key: str, *, reason: str, now: str) -> None:
        rel_path = f"{PROPOSAL_DIR}/{key}.md"
        body = (
            f"# Offboard Proposal — {key}\n\n"
            f"**Status:** confirmed\n"
            f"**Confirmed at:** {now}\n"
            f"**Reason:** {reason}\n\n"
            "Actuation complete: `status: departed`, ingest stopped, bridge token "
            "revoked when present. Wiki archive runs after the configured delay.\n"
        )
        write_wiki_page(
            rel_path,
            f"Offboard Proposal — {key}",
            body,
            mode=self.WRITE_MODE,
            section="hr",
            type_="proposal",
            extra_frontmatter={
                "member": key,
                "status": "confirmed",
                "reason": reason,
                "confirmed_at": now,
            },
        )
