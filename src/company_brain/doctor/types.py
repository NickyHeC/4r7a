"""Doctor check result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: Status
    message: str
    hint: str = ""


@dataclass
class DoctorReport:
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def fail_rules(self) -> set[str]:
        return {c.check for c in self.checks if c.status == "fail"}

    @property
    def warn_rules(self) -> set[str]:
        return {c.check for c in self.checks if c.status == "warn"}

    @property
    def score(self) -> int:
        from company_brain.doctor.scoring import compute_score

        return compute_score(self.fail_rules, self.warn_rules)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "fail_count": len(self.fail_rules),
            "warn_count": len(self.warn_rules),
            "checks": [
                {
                    "check": c.check,
                    "status": c.status,
                    "message": c.message,
                    "hint": c.hint,
                }
                for c in self.checks
            ],
        }
