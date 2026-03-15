from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.blog_service import disable_legacy_demo_blogs_for_live, ensure_all_blog_workflows, ensure_default_blogs
from app.services.settings_service import ensure_default_settings, get_settings_map
from app.services.storage_service import ensure_storage_dirs

app = FastAPI(title=settings.project_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
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
    finally:
        db.close()


@app.get("/healthz")
def healthcheck() -> dict:
    return {"status": "ok"}
