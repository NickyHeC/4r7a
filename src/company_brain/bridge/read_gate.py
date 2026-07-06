"""Department-scoped read gate for bridge MCP."""

from __future__ import annotations

from pathlib import PurePosixPath

from company_brain.bridge.config import BridgeConfig, load_bridge_config
from company_brain.members_config import MembersConfig, load_members_config


def _normalize_rel(rel_path: str) -> str:
    return str(PurePosixPath(rel_path.strip().lstrip("/")))


def _path_under_prefix(rel_path: str, prefix: str) -> bool:
    p = _normalize_rel(rel_path)
    pref = prefix.strip("/")
    return p == pref or p.startswith(pref + "/")


def member_departments(member_key: str, members: MembersConfig | None = None) -> list[str]:
    cfg = members or load_members_config()
    spec = cfg.get(member_key)
    if not spec:
        return []
    bridge = getattr(spec, "bridge", None)
    if bridge is None:
        return []
    return [str(d).strip() for d in (bridge.departments or []) if str(d).strip()]


def parse_location_sync(sync: str) -> str | None:
    s = (sync or "").strip()
    if s.startswith("location:"):
        return s.split(":", 1)[1].strip()
    return None


class ReadGate:
    """Decide whether a member token may read a wiki page."""

    def __init__(
        self,
        member_key: str,
        *,
        bridge_cfg: BridgeConfig | None = None,
        members_cfg: MembersConfig | None = None,
    ):
        self.member_key = member_key
        self.bridge_cfg = bridge_cfg or load_bridge_config()
        self.members_cfg = members_cfg or load_members_config()
        self.departments = member_departments(member_key, self.members_cfg)

    def can_read(self, rel_path: str, sync: str, *, volume: str = "company") -> bool:
        sync = (sync or "").strip()
        rel = _normalize_rel(rel_path)

        if sync in ("admin_only", "not_synced"):
            return False

        if volume == "employee":
            return self._can_read_employee(rel, sync)

        if sync == "company":
            return any(_path_under_prefix(rel, p) for p in self.bridge_cfg.company_prefixes())

        loc = parse_location_sync(sync)
        if loc and loc in self.departments:
            return any(_path_under_prefix(rel, p) for p in self.bridge_cfg.department_prefixes(loc))

        return False

    def _can_read_employee(self, rel: str, sync: str) -> bool:
        prefix = f"{self.member_key}/"
        if not rel.startswith(prefix):
            spec = self.members_cfg.get(self.member_key)
            grants = (spec.query_grants if spec else {}) or {}
            for grantee, paths in grants.items():
                if grantee != self.member_key:
                    continue
                for p in paths:
                    if _path_under_prefix(rel, p):
                        return sync in ("private", "company")
            return False
        if sync not in ("private", "company"):
            return False
        return True

    def department_allowed(self, department: str) -> bool:
        return department in self.departments
