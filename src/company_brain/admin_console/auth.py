"""Admin console session auth (separate from member bridge tokens)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any

COOKIE_NAME = "cb_admin_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours


class AuthError(RuntimeError):
    pass


def password_configured() -> bool:
    return bool(os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip())


def session_secret() -> str:
    secret = os.getenv("ADMIN_CONSOLE_SESSION_SECRET", "").strip()
    if secret:
        return secret
    # Dev fallback derived from password so local runs work without two secrets.
    pw = os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip()
    if not pw:
        raise AuthError(
            "ADMIN_CONSOLE_SESSION_SECRET or ADMIN_CONSOLE_PASSWORD required "
            "(see project_install.md)"
        )
    return hashlib.sha256(f"admin-console:{pw}".encode()).hexdigest()


def verify_password(candidate: str) -> bool:
    expected = os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip()
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def mint_session(*, now: float | None = None) -> str:
    """Return a signed session token ``nonce.exp.sig``."""
    now = time.time() if now is None else now
    exp = int(now + SESSION_TTL_SECONDS)
    nonce = secrets.token_urlsafe(16)
    payload = f"{nonce}.{exp}"
    sig = hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session(token: str | None, *, now: float | None = None) -> bool:
    if not token or token.count(".") != 2:
        return False
    nonce, exp_s, sig = token.split(".", 2)
    payload = f"{nonce}.{exp_s}"
    expected = hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    now = time.time() if now is None else now
    return now <= exp


def session_cookie_kwargs() -> dict[str, Any]:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "max_age": SESSION_TTL_SECONDS,
        "path": "/",
    }
