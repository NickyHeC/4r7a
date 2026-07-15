"""Ambient LLM run context — inherited by nested ``record_usage`` calls.

Managers wrap specialist dispatch in ``ambient_scope`` so cost and duration
rollups can attribute spend to the dispatcher without threading kwargs.
"""

from __future__ import annotations

import contextlib
import contextvars
import uuid
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class RunContext:
    """Tags inherited by nested LLM usage / specialist work."""

    run_id: str
    manager: str | None = None
    reason: str | None = None
    session_id: str | None = None


_current: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "llm_run_context",
    default=None,
)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def get_run_context() -> RunContext | None:
    return _current.get()


@contextlib.contextmanager
def ambient_scope(
    *,
    manager: str | None = None,
    run_id: str | None = None,
    reason: str | None = None,
    session_id: str | None = None,
) -> Iterator[RunContext]:
    """Install ambient tags for the duration of a manager dispatch / poll."""
    parent = _current.get()
    ctx = RunContext(
        run_id=run_id or (parent.run_id if parent else None) or new_run_id(),
        manager=manager if manager is not None else (parent.manager if parent else None),
        reason=reason if reason is not None else (parent.reason if parent else None),
        session_id=(
            session_id if session_id is not None else (parent.session_id if parent else None)
        ),
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
