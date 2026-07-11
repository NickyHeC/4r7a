"""Weave requester authorization — members vs roster."""

from __future__ import annotations

from dataclasses import dataclass

from company_brain.members_config import load_members_config
from company_brain.roster_config import load_roster_config


@dataclass
class WeaveRequester:
    slack_user_id: str
    member_key: str | None = None
    roster_key: str | None = None
    email: str = ""
    is_w2: bool = False


def resolve_weave_requester(slack_user_id: str) -> WeaveRequester | None:
    ref = (slack_user_id or "").strip()
    if not ref:
        return None

    roster = load_roster_config()
    roster_key = roster.find_by_slack_user_id(ref)
    if roster_key:
        person = roster.get(roster_key)
        return WeaveRequester(
            slack_user_id=ref,
            roster_key=roster_key,
            email=person.email if person else "",
            is_w2=False,
        )

    members = load_members_config()
    member_key = members.find_by_slack_user_id(ref)
    if member_key:
        spec = members.get(member_key)
        return WeaveRequester(
            slack_user_id=ref,
            member_key=member_key,
            email=spec.email if spec else "",
            is_w2=True,
        )

    return WeaveRequester(slack_user_id=ref, is_w2=False)


def can_invoke_weave(requester: WeaveRequester | None) -> tuple[bool, str]:
    if requester is None:
        return False, "unknown_user"
    if requester.roster_key:
        return False, "roster_not_allowed"
    if not requester.member_key:
        return False, "not_a_member"
    members = load_members_config()
    spec = members.get(requester.member_key)
    if spec is None or not spec.is_active:
        return False, "inactive_member"
    return True, "ok"
