"""Run the admin console HTTP server (uvicorn)."""

from __future__ import annotations

import logging

from company_brain.admin_console.auth import password_configured
from company_brain.admin_console.config import bind_host, bind_port

logger = logging.getLogger(__name__)


def serve(*, host: str | None = None, port: int | None = None) -> None:
    if not password_configured():
        raise SystemExit("ADMIN_CONSOLE_PASSWORD not set — see project_install.md (Admin console)")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn/fastapi required: pip install 'company-brain[admin-console]'"
        ) from exc

    from company_brain.admin_console.app import create_app

    host = host or bind_host()
    port = port if port is not None else bind_port()
    logger.info("Admin console listening on http://%s:%s", host, port)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
