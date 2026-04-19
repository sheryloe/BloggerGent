from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.platform.blog_service import (
    enforce_text_runtime_policy,
    ensure_all_blog_workflows,
    purge_legacy_demo_blogs,
)
from app.services.cloudflare.cloudflare_performance_service import get_cloudflare_performance_summary
from app.services.integrations.settings_service import ensure_default_settings, get_settings_map
from app.services.integrations.mystery_asset_public_service import (
    guess_asset_content_type,
    mystery_asset_path_to_object_key,
)
from app.services.integrations.storage_service import cloudflare_r2_download_binary, ensure_storage_dirs
from app.services.content.topic_guard_service import backfill_missing_topic_memories
from app.services.providers.base import ProviderRuntimeError

logger = logging.getLogger(__name__)


def _normalized_origin(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_allowed_origins() -> list[str]:
    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:7000",
        "http://127.0.0.1:7000",
        "http://localhost:7001",
        "http://127.0.0.1:7001",
    }
    for candidate in (settings.public_web_base_url, settings.public_api_base_url):
        normalized = _normalized_origin(candidate)
        if normalized:
            origins.add(normalized)
    return sorted(origins)


app = FastAPI(title=settings.project_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_allowed_origins(),
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_storage_dirs()
app.mount("/storage", StaticFiles(directory=settings.storage_root), name="storage")
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
def on_startup() -> None:
    db = SessionLocal()
    try:
        ensure_default_settings(db)
        get_settings_map(db)
        purge_legacy_demo_blogs(db)
        ensure_all_blog_workflows(db)
        enforce_text_runtime_policy(db)
        backfill_missing_topic_memories(db)
        try:
            get_cloudflare_performance_summary(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cloudflare performance smoke check failed at startup: %s", exc)
    finally:
        db.close()


@app.get("/healthz")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/health")
def healthcheck_compat() -> dict:
    return {"status": "ok"}


def _asset_not_found_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "error": {
                "code": "ASSET_NOT_FOUND",
                "message": "The requested asset does not exist.",
            },
        },
    )


def _asset_fetch_failed_response() -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "success": False,
            "error": {
                "code": "ASSET_FETCH_FAILED",
                "message": "Failed to load the requested asset.",
            },
        },
    )


@app.api_route("/assets/{asset_path:path}", methods=["GET", "HEAD"])
def serve_mystery_asset(asset_path: str, request: Request) -> Response:
    object_key = mystery_asset_path_to_object_key(asset_path)
    if not object_key:
        return _asset_not_found_response()

    db = SessionLocal()
    try:
        payload = cloudflare_r2_download_binary(db, public_key="", key=object_key)
    except ProviderRuntimeError as exc:
        if int(getattr(exc, "status_code", 502)) == 404:
            return _asset_not_found_response()
        logger.warning("Mystery asset fetch failed for key=%s: %s", object_key, exc)
        return _asset_fetch_failed_response()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected mystery asset fetch error for key=%s: %s", object_key, exc)
        return _asset_fetch_failed_response()
    finally:
        db.close()

    media_type = guess_asset_content_type(object_key)
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if request.method.upper() == "HEAD":
        return Response(status_code=200, media_type=media_type, headers=headers)
    return Response(content=payload, status_code=200, media_type=media_type, headers=headers)
