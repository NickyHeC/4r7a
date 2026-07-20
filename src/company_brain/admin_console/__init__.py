"""Admin console — logged-in ops cockpit on the wiki host (not member bridge)."""

from __future__ import annotations

__all__ = ["serve"]


def serve(**kwargs):  # pragma: no cover - thin re-export
    from company_brain.admin_console.server import serve as _serve

    return _serve(**kwargs)
