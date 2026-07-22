"""HR Onboarding — seed current employees / past hires, or onboard one joiner.

First run (``seed=True``): reads ``config/hr_seed.yaml``, upserts members/roster,
bootstraps employee wikis, optional LinkedIn pull, backfills hiring log, starts
``hr_manager``.

Per-joiner: admin runs with ``member_key`` after adding them to members/roster.

SDK: Neither (orchestration). Follows platform-onboarding shape: backfill then
``start`` managers.
"""

from __future__ import annotations

from typing import Any

from company_brain.agents.base import BaseAgent
from company_brain.agents.hr.hiring_log import backfill_hire_entry, join_hire_entry
from company_brain.agents.hr.hr_config import HrSeedPerson, load_hr_seed
from company_brain.members_config import (
    MemberBindings,
    MemberBridgeConfig,
    MemberSpec,
    load_members_config,
    save_members_config,
)
from company_brain.roster_config import RosterPerson, load_roster_config, save_roster_config


class HrOnboardingAgent(BaseAgent):
    """One-time seed onboarding or per-member join onboarding."""

    name = "hr_onboarding"

    def run(
        self,
        *,
        seed: bool = False,
        member_key: str = "",
        start_manager: bool = True,
        pull_linkedin: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if seed:
            return self._run_seed(start_manager=start_manager, pull_linkedin=pull_linkedin)
        key = (member_key or "").strip()
        if not key:
            return {"status": "error", "reason": "member_key_or_seed_required"}
        return self._run_member(key, pull_linkedin=pull_linkedin, start_manager=False)

    def _run_seed(self, *, start_manager: bool, pull_linkedin: bool) -> dict[str, Any]:
        seed_cfg = load_hr_seed()
        onboarded: list[str] = []
        skipped: list[dict[str, str]] = []
        for person in seed_cfg.current_employees:
            result = self._upsert_and_onboard(person, pull_linkedin=pull_linkedin)
            if result.get("status") == "ok":
                onboarded.append(person.key)
            else:
                skipped.append({"key": person.key, "reason": str(result.get("reason"))})

        past: list[str] = []
        for person in seed_cfg.past_hires:
            backfill_hire_entry(
                key=person.key,
                employment_type=person.employment_type,
                department=person.department,
                email=person.email,
                start_date=person.start_date,
                end_date=person.end_date,
                notes=person.notes,
            )
            past.append(person.key)

        started: list[str] = []
        if start_manager:
            started = self._start_manager()

        return {
            "status": "ok",
            "onboarded": onboarded,
            "skipped": skipped,
            "past_hires_logged": past,
            "managers_started": started,
        }

    def _run_member(
        self,
        member_key: str,
        *,
        pull_linkedin: bool,
        start_manager: bool,
    ) -> dict[str, Any]:
        members = load_members_config()
        roster = load_roster_config()
        if member_key in members.members:
            spec = members.members[member_key]
            person = HrSeedPerson(
                key=member_key,
                email=spec.email,
                employment_type="w2",
                department=spec.department,
                linkedin_url=spec.bindings.linkedin_url,
                role=spec.role,
                slack_user_id=spec.bindings.slack_user_id,
            )
        elif member_key in roster.people:
            rp = roster.people[member_key]
            person = HrSeedPerson(
                key=member_key,
                email=rp.email,
                employment_type=rp.employment_type,
                department=rp.department,
                linkedin_url=rp.linkedin_url,
                slack_user_id=rp.slack_user_id,
            )
        else:
            return {"status": "error", "reason": "unknown_member_or_roster"}

        result = self._upsert_and_onboard(person, pull_linkedin=pull_linkedin, log_join=True)
        if start_manager:
            result["managers_started"] = self._start_manager()
        return result

    def _upsert_and_onboard(
        self,
        person: HrSeedPerson,
        *,
        pull_linkedin: bool,
        log_join: bool = True,
    ) -> dict[str, Any]:
        key = person.key.strip()
        if not key:
            return {"status": "error", "reason": "empty_key"}

        employment = (person.employment_type or "w2").strip().lower()
        if employment == "w2":
            self._ensure_member(person)
        else:
            self._ensure_roster(person)

        from company_brain.agents.employee_wiki.employee_wiki_onboarding import (
            EmployeeWikiOnboardingAgent,
        )
        from company_brain.runtime import get_runtime

        wiki = get_runtime().run(
            EmployeeWikiOnboardingAgent,
            self.config,
            member_key=key,
            email=person.email,
        )

        if log_join:
            join_hire_entry(
                key=key,
                employment_type=employment,
                department=person.department,
                email=person.email,
                start_date=person.start_date,
                linkedin_url=person.linkedin_url,
            )

        linkedin_result: dict[str, Any] | None = None
        if pull_linkedin and person.linkedin_url:
            from company_brain.agents.hr.linkedin.pull import PullAgent

            linkedin_result = get_runtime().run(
                PullAgent,
                self.config,
                member_key=key,
                force=True,
            )

        return {
            "status": "ok",
            "member": key,
            "employment_type": employment,
            "employee_wiki": wiki,
            "linkedin": linkedin_result,
        }

    def _ensure_member(self, person: HrSeedPerson) -> None:
        members = load_members_config()
        existing = members.members.get(person.key)
        depts = list(existing.bridge.departments) if existing else []
        if person.department and person.department not in depts:
            depts.insert(0, person.department)

        bindings = MemberBindings(
            granola_label=(existing.bindings.granola_label if existing else "") or person.key,
            gmail_mailbox=(existing.bindings.gmail_mailbox if existing else "") or person.email,
            slack_user_id=person.slack_user_id
            or (existing.bindings.slack_user_id if existing else ""),
            linkedin_url=person.linkedin_url
            or (existing.bindings.linkedin_url if existing else ""),
            discord_id=existing.bindings.discord_id if existing else "",
            discord_handle=existing.bindings.discord_handle if existing else "",
            linear_user_id=existing.bindings.linear_user_id if existing else "",
        )
        members.members[person.key] = MemberSpec(
            email=person.email or (existing.email if existing else ""),
            role=person.role or (existing.role if existing else "member"),
            status="active",
            department=person.department or (existing.department if existing else ""),
            notion_teamspace=existing.notion_teamspace if existing else "",
            bridge=MemberBridgeConfig(departments=depts),
            bindings=bindings,
            ingest=existing.ingest if existing else MemberSpec().ingest,
            query_grants=existing.query_grants if existing else {},
            departed_at="",
            wiki_archived=False,
        )
        save_members_config(members)

    def _ensure_roster(self, person: HrSeedPerson) -> None:
        roster = load_roster_config()
        existing = roster.people.get(person.key)
        bridge = dict(existing.bridge) if existing else {}
        depts = list(bridge.get("departments") or [])
        if person.department and person.department not in depts:
            depts.insert(0, person.department)
        bridge["departments"] = depts
        roster.people[person.key] = RosterPerson(
            email=person.email or (existing.email if existing else ""),
            employment_type=person.employment_type or "contractor",
            department=person.department or (existing.department if existing else ""),
            status="active",
            slack_user_id=person.slack_user_id or (existing.slack_user_id if existing else ""),
            linkedin_url=person.linkedin_url or (existing.linkedin_url if existing else ""),
            bindings=dict(existing.bindings) if existing else {},
            ingest=dict(existing.ingest) if existing else {},
            bridge=bridge,
        )
        save_roster_config(roster)

    def _start_manager(self) -> list[str]:
        from company_brain.agents.hr.hr_manager import HrManager
        from company_brain.runtime import get_runtime

        get_runtime().start(HrManager, self.config)
        return [HrManager.name]
