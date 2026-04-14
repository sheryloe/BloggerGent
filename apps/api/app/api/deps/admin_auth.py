from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.integrations.settings_service import get_settings_map


_basic_auth = HTTPBasic(auto_error=False)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _unauthorized(detail: str = "admin_auth_required") -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def require_admin_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic_auth),
    x_admin_user: str | None = Header(default=None, alias="x-admin-user"),
    x_admin_password: str | None = Header(default=None, alias="x-admin-password"),
    db: Session = Depends(get_db),
) -> None:
    values = get_settings_map(db)
    if not _is_truthy(values.get("admin_auth_enabled")):
        return

    expected_username = str(values.get("admin_auth_username") or "").strip()
    expected_password = str(values.get("admin_auth_password") or "").strip()
    if not expected_username or not expected_password:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin_auth_not_configured")

    supplied_username = ""
    supplied_password = ""
    if credentials is not None:
        supplied_username = credentials.username or ""
        supplied_password = credentials.password or ""
    elif x_admin_user or x_admin_password:
        supplied_username = x_admin_user or ""
        supplied_password = x_admin_password or ""
    else:
        _unauthorized()

    if not secrets.compare_digest(supplied_username, expected_username):
        _unauthorized("admin_auth_invalid_username")
    if not secrets.compare_digest(supplied_password, expected_password):
        _unauthorized("admin_auth_invalid_password")
