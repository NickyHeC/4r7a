"""Result + verification types for the agent eval loop.

Every agent run produces output that can be *verified* against the agent's own
standard. ``verify()`` returns an ``AgentResult`` whose ``status`` triages the
output:

- ``ok``     — output meets the standard; stop iterating, deliver normally.
- ``rework`` — output is real but below standard; iterate (up to max_iterations).
- ``noise``  — nothing actionable happened; suppress notification (still logged).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUS_OK = "ok"
STATUS_REWORK = "rework"
STATUS_NOISE = "noise"


@dataclass
class AgentResult:
    """Outcome of an agent run plus its verification verdict."""

    output: Any = None
    status: str = STATUS_OK
    score: float | None = None
    gaps: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == STATUS_OK

    @property
    def is_noise(self) -> bool:
        return self.status == STATUS_NOISE
