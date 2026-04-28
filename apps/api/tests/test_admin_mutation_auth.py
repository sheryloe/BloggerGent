from __future__ import annotations

from fastapi.routing import APIRoute

from app.api.router import api_router
from app.schemas.api import GeneratedDataResetRequest


def test_all_mutation_routes_require_admin_auth() -> None:
    mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
    missing: list[str] = []

    for route in api_router.routes:
        if not isinstance(route, APIRoute):
            continue
        if not (set(route.methods or []) & mutation_methods):
            continue
        dependency_names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        if "require_admin_auth" not in dependency_names:
            missing.append(f"{sorted(route.methods)} {route.path}")

    assert missing == []


def test_generated_data_reset_request_defaults_to_dry_run() -> None:
    payload = GeneratedDataResetRequest()

    assert payload.dry_run is True
    assert payload.confirm_text is None
