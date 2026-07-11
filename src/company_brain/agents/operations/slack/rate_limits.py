"""Per-user rate limits for @wiki interactive commands."""

from __future__ import annotations

from datetime import datetime, timezone

from company_brain.agents.gates import StateStore
from company_brain.agents.operations.slack import slack_config as cfg
from company_brain.members_config import load_members_config


class RateLimitExceeded(RuntimeError):
    def __init__(self, *, limit: int, window: str):
        super().__init__(f"rate limit exceeded ({limit}/{window})")
        self.limit = limit
        self.window = window


def _is_admin(slack_user_id: str) -> bool:
    members = load_members_config()
    key = members.find_by_slack_user_id(slack_user_id)
    if not key:
        return False
    spec = members.get(key)
    return bool(spec and spec.is_admin)


def check_wiki_query_limit(slack_user_id: str) -> None:
    if _is_admin(slack_user_id):
        return
    limit = cfg.wiki_queries_per_user_hour()
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    key = f"slack:wiki:queries:{slack_user_id}:{bucket}"
    store = StateStore()
    count = int(store.get(key) or 0)
    if count >= limit:
        raise RateLimitExceeded(limit=limit, window="hour")
    store.set(key, count + 1)


def check_weave_submission_limit(slack_user_id: str) -> None:
    if _is_admin(slack_user_id):
        return
    limit = cfg.weave_submissions_per_user_day()
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"slack:weave:submissions:{slack_user_id}:{bucket}"
    store = StateStore()
    count = int(store.get(key) or 0)
    if count >= limit:
        raise RateLimitExceeded(limit=limit, window="day")
    store.set(key, count + 1)
