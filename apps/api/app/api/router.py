from fastapi import APIRouter

from app.api.routes import articles, blogs, dashboard, google, jobs, prompts, settings, topics

api_router = APIRouter()
api_router.include_router(blogs.router, prefix="/blogs", tags=["blogs"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(articles.router, prefix="/articles", tags=["articles"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(google.router, prefix="/google", tags=["google"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(settings.blogger_router, prefix="/blogger", tags=["blogger"])
