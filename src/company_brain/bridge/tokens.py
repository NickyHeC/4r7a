"""Per-member bridge bearer tokens (hashes only on disk)."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_brain.bridge.config import BridgeConfig, load_bridge_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


@dataclass
class TokenRecord:
    member: str
    token_hash: str
    issued_at: str
    revoked_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenRecord:
        return cls(
            member=str(data.get("member") or ""),
            token_hash=str(data.get("token_hash") or ""),
            issued_at=str(data.get("issued_at") or ""),
            revoked_at=str(data.get("revoked_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "token_hash": self.token_hash,
            "issued_at": self.issued_at,
            "revoked_at": self.revoked_at,
        }

    @property
    def is_active(self) -> bool:
        return not self.revoked_at


class BridgeTokenStore:
    def __init__(self, cfg: BridgeConfig | None = None, config_dir: Path | None = None):
        self._cfg = cfg or load_bridge_config(config_dir)
        from company_brain.config import CONFIG_DIR

        self._dir = config_dir or CONFIG_DIR
        self._path = self._cfg.config_path(self._cfg.tokens_path, self._dir)

    def _load(self) -> list[TokenRecord]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
        except json.JSONDecodeError:
            return []
        records = data.get("tokens") or []
        return [TokenRecord.from_dict(r) for r in records]

    def _save(self, records: list[TokenRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tokens": [r.to_dict() for r in records]}
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        tmp.replace(self._path)

    def issue(self, member: str) -> str:
        """Return plaintext token (show once). Revokes prior active token for member."""
        member = member.strip()
        if not member:
            raise ValueError("member key required")
        plaintext = secrets.token_urlsafe(32)
        record = TokenRecord(
            member=member,
            token_hash=hash_token(plaintext),
            issued_at=_utc_now(),
        )
        records = [r for r in self._load() if r.member != member]
        # Mark old tokens revoked (shouldn't exist after filter, but keep audit trail)
        for old in self._load():
            if old.member == member and old.is_active:
                old.revoked_at = _utc_now()
                records.append(old)
        records.append(record)
        self._save(records)
        return plaintext

    def revoke(self, member: str) -> bool:
        member = member.strip()
        changed = False
        records = self._load()
        for rec in records:
            if rec.member == member and rec.is_active:
                rec.revoked_at = _utc_now()
                changed = True
        if changed:
            self._save(records)
        return changed

    def verify(self, plaintext: str) -> str | None:
        if not plaintext or not plaintext.strip():
            return None
        digest = hash_token(plaintext.strip())
        for rec in self._load():
            if rec.token_hash == digest and rec.is_active:
                return rec.member
        return None
