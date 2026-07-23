"""Heuristic security-mail detection (deterministic, $0)."""

from __future__ import annotations

SECURITY_SUBJECT_HINTS = (
    "security alert",
    "unusual sign-in",
    "new sign-in",
    "suspicious activity",
    "password reset",
    "reset your password",
    "verification code",
    "mfa",
    "2fa",
    "two-factor",
    "multi-factor",
    "wire transfer",
    "wire request",
    "ach transfer",
    "gift card",
    "bank account change",
    "change of bank",
    "payment details updated",
    "vendor bank",
    "account takeover",
    "login attempt",
)

SECURITY_BODY_HINTS = (
    "if you did not",
    "did not recently",
    "unauthorized",
    "wire instructions",
    "send gift cards",
    "urgent wire",
    "new banking details",
)

# Borderline: needs human/LLM confirm — still never auto-archive
BORDERLINE_HINTS = (
    "verify your account",
    "confirm your identity",
    "action required: security",
)


def security_match(subject: str, from_hdr: str, snippet: str) -> dict[str, object]:
    """Return match info: ``{matched, confidence, reasons}``.

    ``confidence`` is ``high`` | ``borderline`` | ``none``.
    """
    subj = (subject or "").lower()
    frm = (from_hdr or "").lower()
    body = (snippet or "").lower()
    blob = f"{subj} {frm} {body}"
    reasons: list[str] = []

    for h in SECURITY_SUBJECT_HINTS:
        if h in subj or h in blob:
            reasons.append(h)
    for h in SECURITY_BODY_HINTS:
        if h in body:
            reasons.append(h)

    if reasons:
        return {"matched": True, "confidence": "high", "reasons": reasons[:6]}

    borderline = [h for h in BORDERLINE_HINTS if h in blob]
    if borderline:
        return {"matched": True, "confidence": "borderline", "reasons": borderline[:4]}

    return {"matched": False, "confidence": "none", "reasons": []}
