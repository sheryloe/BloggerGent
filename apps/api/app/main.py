from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.blog_service import (
    disable_legacy_demo_blogs_for_live,
    enforce_free_tier_model_policy,
    ensure_all_blog_workflows,
    ensure_default_blogs,
)
from app.services.settings_service import ensure_default_settings, get_settings_map
from app.services.storage_service import ensure_storage_dirs
from app.services.topic_guard_service import backfill_missing_topic_memories


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
        settings_map = get_settings_map(db)
        enable_demo = settings_map.get("provider_mode", settings.provider_mode).lower() != "live"
        ensure_default_blogs(db, enable_demo=enable_demo)
        if not enable_demo:
            disable_legacy_demo_blogs_for_live(db)
        ensure_all_blog_workflows(db)
        enforce_free_tier_model_policy(db)
        backfill_missing_topic_memories(db)
    finally:
        db.close()


@app.get("/healthz")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/health")
def healthcheck_compat() -> dict:
    return {"status": "ok"}
