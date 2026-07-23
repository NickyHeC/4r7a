"""Admin console session auth (password local-dev + Google Workspace OIDC)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from company_brain.admin_console.config import load_admin_console_config

COOKIE_NAME = "cb_admin_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours
PASSWORD_LOCAL_EMAIL = "local@password"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class AuthError(RuntimeError):
    pass


def password_configured() -> bool:
    return bool(os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip())


def password_login_enabled() -> bool:
    raw = load_admin_console_config().get("password_login")
    if raw is None:
        return True
    return bool(raw)


def sso_config() -> dict[str, Any]:
    raw = load_admin_console_config().get("sso") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "provider": str(raw.get("provider") or "google").strip().lower(),
        "hosted_domain": str(raw.get("hosted_domain") or "").strip().lower(),
    }


def sso_enabled() -> bool:
    cfg = sso_config()
    if not cfg["enabled"] or cfg["provider"] != "google":
        return False
    return bool(google_client_id() and google_client_secret())


def google_client_id() -> str:
    return os.getenv("ADMIN_CONSOLE_GOOGLE_CLIENT_ID", "").strip()


def google_client_secret() -> str:
    return os.getenv("ADMIN_CONSOLE_GOOGLE_CLIENT_SECRET", "").strip()


def public_base_url() -> str:
    return (
        os.getenv("ADMIN_CONSOLE_PUBLIC_BASE_URL", "").strip().rstrip("/")
        or "http://127.0.0.1:8780"
    )


def admin_allowlist() -> list[str]:
    raw = load_admin_console_config().get("admins") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip().lower() for x in raw if str(x).strip()]


def email_allowed(email: str) -> bool:
    """Allow-list gate. Empty ``admins`` → any authenticated identity."""
    email = (email or "").strip().lower()
    if not email:
        return False
    allow = admin_allowlist()
    if not allow:
        return True
    return email in allow


def auth_ready() -> bool:
    """True if at least one login method is configured."""
    if sso_enabled():
        return True
    return password_login_enabled() and password_configured()


def session_secret() -> str:
    secret = os.getenv("ADMIN_CONSOLE_SESSION_SECRET", "").strip()
    if secret:
        return secret
    # Dev fallback derived from password or Google client secret.
    pw = os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip()
    if pw:
        return hashlib.sha256(f"admin-console:{pw}".encode()).hexdigest()
    cid = google_client_secret()
    if cid:
        return hashlib.sha256(f"admin-console-sso:{cid}".encode()).hexdigest()
    raise AuthError(
        "ADMIN_CONSOLE_SESSION_SECRET required when neither password nor "
        "GOOGLE client secret is set (see project_install.md)"
    )


def verify_password(candidate: str) -> bool:
    expected = os.getenv("ADMIN_CONSOLE_PASSWORD", "").strip()
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def _encode_email(email: str) -> str:
    """Base64url without padding (no dots — safe inside ``.``-separated tokens)."""
    raw = (email or "").strip().lower().encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_email(enc: str) -> str:
    if not enc:
        return ""
    pad = "=" * (-len(enc) % 4)
    try:
        return base64.urlsafe_b64decode(enc + pad).decode()
    except (ValueError, UnicodeDecodeError):
        return ""


def mint_session(*, email: str = "", now: float | None = None) -> str:
    """Return a signed session token ``nonce.exp.email_b64.sig``."""
    now = time.time() if now is None else now
    exp = int(now + SESSION_TTL_SECONDS)
    nonce = secrets.token_urlsafe(16)
    email_enc = _encode_email(email)
    payload = f"{nonce}.{exp}.{email_enc}"
    sig = hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def parse_session(token: str | None, *, now: float | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) == 3:
        # Legacy password sessions (pre-SSO): nonce.exp.sig
        nonce, exp_s, sig = parts
        email = ""
        payload = f"{nonce}.{exp_s}"
    elif len(parts) == 4:
        nonce, exp_s, email_enc, sig = parts
        email = _decode_email(email_enc)
        payload = f"{nonce}.{exp_s}.{email_enc}"
    else:
        return None
    try:
        expected = hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    except AuthError:
        return None
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    now = time.time() if now is None else now
    if now > exp:
        return None
    return {"email": email, "exp": exp}


def verify_session(token: str | None, *, now: float | None = None) -> bool:
    parsed = parse_session(token, now=now)
    if not parsed:
        return False
    email = str(parsed.get("email") or "")
    if email == PASSWORD_LOCAL_EMAIL and not password_login_enabled():
        return False
    if email and email != PASSWORD_LOCAL_EMAIL and not email_allowed(email):
        return False
    return True


def session_email(token: str | None) -> str:
    parsed = parse_session(token)
    return str((parsed or {}).get("email") or "")


def session_cookie_kwargs() -> dict[str, Any]:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "max_age": SESSION_TTL_SECONDS,
        "path": "/",
    }


def google_authorize_url(*, state: str) -> str:
    cfg = sso_config()
    params: dict[str, str] = {
        "client_id": google_client_id(),
        "redirect_uri": f"{public_base_url()}/auth/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "state": state,
        "prompt": "select_account",
    }
    if cfg["hosted_domain"]:
        params["hd"] = cfg["hosted_domain"]
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _http_json(method: str, url: str, *, data: dict[str, str] | None = None) -> dict[str, Any]:
    body = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "User-Agent": "company-brain-admin-console"},
    )
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise AuthError(f"OIDC HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AuthError(f"OIDC network error: {exc}") from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise AuthError("OIDC response was not JSON") from exc
    if not isinstance(parsed, dict):
        raise AuthError("OIDC response was not an object")
    return parsed


def exchange_google_code(code: str) -> dict[str, Any]:
    """Exchange auth code → userinfo. Raises AuthError on failure / deny."""
    token = _http_json(
        "POST",
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": google_client_id(),
            "client_secret": google_client_secret(),
            "redirect_uri": f"{public_base_url()}/auth/callback",
            "grant_type": "authorization_code",
        },
    )
    access = str(token.get("access_token") or "")
    if not access:
        raise AuthError("Google token response missing access_token")
    req = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json",
            "User-Agent": "company-brain-admin-console",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise AuthError(f"Failed to fetch Google userinfo: {exc}") from exc
    email = str(info.get("email") or "").strip().lower()
    if not email:
        raise AuthError("Google account has no email")
    if not info.get("email_verified", True):
        raise AuthError("Google email not verified")
    hd = sso_config()["hosted_domain"]
    if hd:
        domain = email.split("@")[-1]
        claim_hd = str(info.get("hd") or "").lower()
        if domain != hd and claim_hd != hd:
            raise AuthError(f"email domain not in Workspace ({hd})")
    if not email_allowed(email):
        raise AuthError(f"email not in admin allow-list: {email}")
    return {"email": email, "name": str(info.get("name") or email)}
