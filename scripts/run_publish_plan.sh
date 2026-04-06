#!/usr/bin/env bash
set -euo pipefail

cd /mnt/d/Donggri_Platform/BloggerGent

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bloggent-test}"
export WEB_PORT="${WEB_PORT:-7004}"
export API_PORT="${API_PORT:-8004}"
export POSTGRES_PORT="${POSTGRES_PORT:-5434}"

: "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
: "${BLOGGER_ES_ID:?set BLOGGER_ES_ID}"
: "${BLOGGER_JA_ID:?set BLOGGER_JA_ID}"
: "${CLOUDFLARE_BLOG_API_BASE_URL:?set CLOUDFLARE_BLOG_API_BASE_URL}"
: "${CLOUDFLARE_BLOG_M2M_TOKEN:?set CLOUDFLARE_BLOG_M2M_TOKEN}"

TS="$(date +%Y%m%d-%H%M%S)"
LOG="TEST/logs/ia-publish-$TS.log"
mkdir -p TEST/logs
exec > >(tee -a "$LOG") 2>&1

docker compose up -d --build

API="http://localhost:${API_PORT}"

python3 - <<'PY'
import os, json, urllib.request

API=os.environ["API"]
openai_key=os.environ["OPENAI_API_KEY"]


def req(method, path, payload=None):
    data=None
    headers={}
    if payload is not None:
        data=json.dumps(payload).encode()
        headers={"Content-Type":"application/json"}
    r=urllib.request.Request(API+path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        body=resp.read().decode() or "{}"
        return json.loads(body)

settings=req("GET","/api/v1/settings")
settings_map={item["key"]:item["value"] for item in settings}

values={
    "provider_mode":"live",
    "openai_api_key":openai_key,
    "openai_text_model":"gpt-4.1-mini-2025-04-14",
    "topic_discovery_model":"gpt-4.1-2025-04-14",
    "article_generation_model":"gpt-4.1-2025-04-14",
    "topic_discovery_provider":"openai",
    "cloudflare_channel_enabled":"true",
    "cloudflare_blog_api_base_url": os.environ["CLOUDFLARE_BLOG_API_BASE_URL"],
    "cloudflare_blog_m2m_token": os.environ["CLOUDFLARE_BLOG_M2M_TOKEN"],
}

req("PUT","/api/v1/settings", {"values":values})
print("settings_updated")
PY

AUTH_URL=$(python3 - <<'PY'
import os, json, urllib.request

API=os.environ["API"]
with urllib.request.urlopen(API+"/api/v1/blogger/config") as resp:
    cfg=json.load(resp)
url=cfg.get("authorization_url") or ""
if not url:
    raise SystemExit("authorization_url is empty; configure blogger_client_id/secret/redirect_uri")
print(url)
PY
)

echo "AUTH_URL=$AUTH_URL"
if command -v wslview >/dev/null 2>&1; then
  wslview "$AUTH_URL"
else
  echo "Open the URL above in your browser to finish OAuth."
fi
read -p "OAuth ¿Ï·á ÈÄ Enter: "

python3 - <<'PY'
import os, json, urllib.request

API=os.environ["API"]

with urllib.request.urlopen(API+"/api/v1/blogger/config?include_remote=true") as resp:
    cfg=json.load(resp)
ids={b.get("id") for b in cfg.get("available_blogs",[]) if b.get("id")}
missing=[env for env in ("BLOGGER_ES_ID","BLOGGER_JA_ID") if os.environ[env] not in ids]
if missing:
    raise SystemExit("remote blogs missing: "+", ".join(missing))
print("remote_ok")
PY

python3 - <<'PY'
import os, json, urllib.request, urllib.error

API=os.environ["API"]


def post(path, payload):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(API+path, data=data, headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail=e.read().decode()
        print("import_error", payload.get("blogger_blog_id"), detail)
        return None

for blog_id in (os.environ["BLOGGER_ES_ID"], os.environ["BLOGGER_JA_ID"]):
    res=post("/api/v1/blogs/import", {"blogger_blog_id": blog_id, "profile_key":"korea_travel"})
    if res:
        print("imported", res["id"], blog_id)
PY

python3 - <<'PY'
import os, json, urllib.request

API=os.environ["API"]


def get(path):
    with urllib.request.urlopen(API+path) as resp:
        return json.load(resp)


def put(path, payload):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(API+path, data=data, headers={"Content-Type":"application/json"}, method="PUT")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)

blogs=get("/api/v1/blogs")
lang_map={os.environ["BLOGGER_ES_ID"]:"es", os.environ["BLOGGER_JA_ID"]:"ja"}

for blog in blogs:
    remote=blog.get("blogger_blog_id") or ""
    if remote in lang_map and blog.get("primary_language") != lang_map[remote]:
        payload={
            "name": blog["name"],
            "description": blog.get("description"),
            "content_category": blog["content_category"],
            "primary_language": lang_map[remote],
            "target_audience": blog.get("target_audience"),
            "content_brief": blog.get("content_brief"),
            "target_reading_time_min_minutes": blog.get("target_reading_time_min_minutes", 6),
            "target_reading_time_max_minutes": blog.get("target_reading_time_max_minutes", 8),
            "publish_mode": blog["publish_mode"],
            "is_active": blog.get("is_active", True),
        }
        put(f"/api/v1/blogs/{blog['id']}", payload)
        print("lang_updated", blog["id"], lang_map[remote])
PY

docker compose exec -T api python - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import Blog
from app.tasks.pipeline import discover_topics_and_enqueue

db = SessionLocal()
try:
    blogs = db.execute(select(Blog)).scalars().all()

    def pick(profile_key, lang=None):
        for b in blogs:
            if (b.profile_key or "") == profile_key and (lang is None or (b.primary_language or "") == lang):
                return b
        return None

    travel_en = pick("korea_travel","en")
    travel_es = pick("korea_travel","es")
    travel_ja = pick("korea_travel","ja")
    mystery = pick("world_mystery", None)

    missing = [name for name, b in [("travel_en", travel_en), ("travel_es", travel_es), ("travel_ja", travel_ja), ("mystery", mystery)] if not b]
    if missing:
        raise SystemExit("missing blogs: " + ",".join(missing))

    start = datetime.now(ZoneInfo("Asia/Seoul"))
    for blog in [travel_en, travel_es, travel_ja, mystery]:
        result = discover_topics_and_enqueue(
            db,
            blog_id=blog.id,
            publish_mode="publish",
            topic_count=3,
            scheduled_start=start,
            publish_interval_minutes=10,
        )
        print("queued", blog.id, result.get("status"))
finally:
    db.close()
PY

docker compose exec -T api python - <<'PY'
import time
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models.entities import SyncedCloudflarePost
from app.services.cloudflare_channel_service import list_cloudflare_categories, generate_cloudflare_posts

db=SessionLocal()
try:
    categories=[c for c in list_cloudflare_categories(db) if c.get("isLeaf")]
    by_slug={c.get("slug"):c for c in categories if c.get("slug")}

    rows = db.execute(
        select(SyncedCloudflarePost.category_slug, func.avg(SyncedCloudflarePost.ctr))
        .where(SyncedCloudflarePost.ctr.is_not(None))
        .group_by(SyncedCloudflarePost.category_slug)
        .order_by(func.avg(SyncedCloudflarePost.ctr).desc())
    ).all()

    ordered=[slug for slug, _ in rows if slug in by_slug]
    if not ordered:
        ordered=[c["slug"] for c in categories[:3] if c.get("slug")]

    selected=ordered[:3]
    if len(selected) < 3:
        raise SystemExit("not enough cloudflare categories")

    for idx, slug in enumerate(selected, 1):
        result = generate_cloudflare_posts(db, per_category=1, category_slugs=[slug], status="published")
        print("cloudflare_generated", slug, result.get("created_count"))
        if idx < 3:
            time.sleep(600)
finally:
    db.close()
PY

python3 - <<'PY'
import os, json, urllib.request

API=os.environ["API"]


def post(path, payload=None):
    data=None
    headers={}
    if payload is not None:
        data=json.dumps(payload).encode()
        headers={"Content-Type":"application/json"}
    req=urllib.request.Request(API+path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)

post("/api/v1/analytics/backfill")
for profile in ("korea_travel","world_mystery"):
    post("/api/v1/content-ops/overview/recalculate", {"profile": profile, "published_only": False, "sync_sheet": False})
print("sync_done")
PY

BASE_WEB="http://localhost:${WEB_PORT}"
BASE_API="http://localhost:${API_PORT}"

curl -sSf "$BASE_WEB/" -I | head -n 1
curl -sSf "$BASE_API/api/v1/channels?include_disconnected=false" > /tmp/channels.json
curl -sSf "$BASE_API/api/v1/seo/targets" > /tmp/seo_targets.json
curl -sSf "$BASE_API/api/v1/workspace/runtime/usage?days=7" > /tmp/runtime_usage.json

python3 - <<'PY'
import json
for path in ("/tmp/channels.json","/tmp/seo_targets.json","/tmp/runtime_usage.json"):
    with open(path,"r",encoding="utf-8") as f:
        json.load(f)
print("json_ok")
PY

echo "done: $LOG"
