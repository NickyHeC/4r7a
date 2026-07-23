"""Run the admin console HTTP server (uvicorn)."""

from __future__ import annotations

import logging

from company_brain.admin_console.auth import auth_ready, password_configured, sso_enabled
from company_brain.admin_console.config import bind_host, bind_port

logger = logging.getLogger(__name__)


def serve(*, host: str | None = None, port: int | None = None) -> None:
    if not auth_ready():
        raise SystemExit(
            "Admin console needs a login method: set ADMIN_CONSOLE_PASSWORD "
            "(password_login) and/or enable Google SSO "
            "(ADMIN_CONSOLE_GOOGLE_CLIENT_ID/SECRET + admin_console.yaml sso.enabled). "
            "See project_install.md"
        )
    if sso_enabled() and not password_configured():
        logger.info("Admin console auth: Google SSO only")
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
