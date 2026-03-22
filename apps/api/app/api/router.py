from fastapi import APIRouter

from app.api.routes import admin, archive, articles, blogs, cloudflare, dashboard, google, jobs, prompts, settings, telegram, topics, training

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(archive.router, prefix="/archive", tags=["archive"])
api_router.include_router(blogs.router, prefix="/blogs", tags=["blogs"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(articles.router, prefix="/articles", tags=["articles"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(cloudflare.router, prefix="/cloudflare", tags=["cloudflare"])
api_router.include_router(google.router, prefix="/google", tags=["google"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(settings.blogger_router, prefix="/blogger", tags=["blogger"])
api_router.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
api_router.include_router(training.router, prefix="/training", tags=["training"])
