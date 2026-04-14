from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"


def _bootstrap_local_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        existing = os.environ.get(key)
        if not key or (existing is not None and existing.strip()):
            continue
        os.environ[key] = value.strip()


_bootstrap_local_runtime_env()
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models.entities import Blog, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _category_hard_gate,
    _cloudflare_public_body_quality_reasons,
    _default_prompt_for_stage,
    _extract_cloudflare_content_html,
)
from app.services.integrations.settings_service import get_settings_map  # noqa: E402


DEFAULT_DATABASE_URL = "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent"
TRACE_TOKENS = (
    "quick brief",
    "core focus",
    "key entities",
    "기준 시각",
    "internal archive",
    "같은 주제로 다시 정리했다",
    "summary section",
)
HANGUL_RE = re.compile(r"[가-힣]")
PROMPT_REVIEW_RULES: dict[str, dict[str, Any]] = {
    "여행과-기록": {
        "dir_name": "yeohaenggwa-girog",
        "prompt_required": (
            "This category is only for actual places, route flow, and lived travel movement.",
            "Never write a blog introduction, archive introduction, category introduction, or a generic essay about travel itself.",
            "The final body section title must be exactly <h2>마무리 기록</h2>.",
        ),
        "gate_required": (
            "Travel category must stay with real places, route flow, and first-hand travel movement.",
            "Reject blog introductions, archive introductions, category introductions, and generic travel essays.",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
    "축제와-현장": {
        "dir_name": "cugjewa-hyeonjang",
        "prompt_required": (
            "This category is for real festivals, fairs, local events, seasonal markets, and on-site field coverage.",
            "Include on-site mood, best visit window, route logic, crowd caution, nearby food, lodging idea, and one practical warning.",
            "The final body section title must be exactly <h2>마무리 기록</h2>.",
        ),
        "gate_required": (
            "Festival category must cover real events, field atmosphere, route, food, lodging, and caution points.",
            "Do not turn it into a generic event essay with no on-site specifics.",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
    "문화와-공간": {
        "dir_name": "munhwawa-gonggan",
        "prompt_required": (
            "This category must stay with real exhibitions, artists, representative works, and viewing points.",
            "Never write a blog introduction, archive introduction, or a vague article about how to enjoy culture.",
            "The final body section title must be exactly <h2>마무리 기록</h2>.",
        ),
        "gate_required": (
            "Culture category must anchor on a real exhibition, artist, representative works, and viewing points.",
            "Reject blog introductions, archive introductions, and generic culture-appreciation essays.",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
    "미스테리아-스토리": {
        "dir_name": "miseuteria-seutori",
        "prompt_required": (
            "This category must be built from 사건, 기록, 단서, 해석, 현재 추적 상태.",
            "Do not create a visible source or verification block.",
            "The final body section title must be exactly <h2>마무리 기록</h2>.",
        ),
        "gate_required": (
            "Mystery category must use 사건, 기록, 단서, 해석, 현재 추적 상태.",
            "Do not generate a visible source or verification block.",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
    "동그리의-생각": {
        "dir_name": "donggeuriyi-saenggag",
        "prompt_required": (
            "This category is for a personal voice, not a report, memo, or productivity checklist.",
            "Create a Korean reflective post that starts from one concrete scene or question and unfolds as a personal monologue.",
            "The final body section title must be exactly <h2>마무리 기록</h2>.",
        ),
        "gate_required": (
            "Thought category must sound like a personal monologue, not a lecture, memo, or report.",
            "Use a distinct reflective tone and finish with a short personal closing note.",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
    "나스닥의-흐름": {
        "dir_name": "naseudagyi-heureum",
        "prompt_required": (
            "Use exactly two speakers: 동그리 and 햄니.",
            "동그리 is aggressive. 햄니 is conservative.",
            "Place the TradingView chart as the last visual block after the written analysis.",
        ),
        "gate_required": (
            "Use exactly two speakers: 동그리 (aggressive) and 햄니 (conservative).",
            "Anchor the piece on one real Nasdaq-listed company",
            "The final body section title must be exactly '마무리 기록'.",
        ),
    },
}

def _database_url() -> str:
    return str(os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL).strip()


def _has_trace_tokens(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    return [token for token in TRACE_TOKENS if token in lowered]


def _prompt_review_payload() -> dict[str, Any]:
    prompt_root = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive"
    items: list[dict[str, Any]] = []
    for slug, rule in PROMPT_REVIEW_RULES.items():
        path = prompt_root / str(rule["dir_name"]) / "article_generation.md"
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        category = {"slug": slug, "name": slug, "id": slug}
        default_prompt = _default_prompt_for_stage(category, "article_generation")
        hard_gate = _category_hard_gate(slug, slug)
        items.append(
            {
                "category_slug": slug,
                "prompt_path": str(path),
                "prompt_exists": path.exists(),
                "prompt_required_hits": {
                    fragment: (fragment in content)
                    for fragment in tuple(rule["prompt_required"])
                },
                "default_prompt_hits": {
                    fragment: (fragment in default_prompt)
                    for fragment in tuple(rule["prompt_required"])
                },
                "hard_gate_hits": {
                    fragment: (fragment in hard_gate)
                    for fragment in tuple(rule["gate_required"])
                },
            }
        )
    return {"items": items}


def _scan_blogger_public_content(db: Session) -> dict[str, Any]:
    blogs = {row.id: row for row in db.execute(select(Blog)).scalars().all()}
    rows = db.execute(select(SyncedBloggerPost)).scalars().all()
    summary: Counter[str] = Counter()
    examples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        html = str(row.content_html or "")
        trace_hits = _has_trace_tokens(html)
        if trace_hits:
            summary["trace_posts"] += 1
            if len(examples["trace_posts"]) < 15:
                examples["trace_posts"].append(
                    {
                        "blog_id": row.blog_id,
                        "title": row.title,
                        "url": row.url,
                        "hits": trace_hits,
                    }
                )
        blog = blogs.get(row.blog_id)
        locale = str(getattr(blog, "primary_language", "") or "").strip().lower()
        lowered = html.casefold()
        if locale == "es" and "frequently asked questions" in lowered:
            summary["es_english_faq_heading"] += 1
            if len(examples["es_english_faq_heading"]) < 15:
                examples["es_english_faq_heading"].append({"title": row.title, "url": row.url})
        if locale == "ja" and "frequently asked questions" in lowered:
            summary["ja_english_faq_heading"] += 1
            if len(examples["ja_english_faq_heading"]) < 15:
                examples["ja_english_faq_heading"].append({"title": row.title, "url": row.url})
        if locale == "es" and "related korea travel reads" in lowered:
            summary["es_english_related_heading"] += 1
        if locale == "ja" and "related korea travel reads" in lowered:
            summary["ja_english_related_heading"] += 1
        if blog and str(blog.slug or "") == "midnight-archives" and HANGUL_RE.search(html):
            summary["mystery_hangul"] += 1
            if len(examples["mystery_hangul"]) < 15:
                examples["mystery_hangul"].append({"title": row.title, "url": row.url})
    return {
        "total_posts": len(rows),
        "summary": dict(summary),
        "examples": dict(examples),
    }


def _scan_cloudflare_public_content(db: Session, *, max_workers: int) -> dict[str, Any]:
    values = get_settings_map(db)
    base_url = str(values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
    token = str(values.get("cloudflare_blog_m2m_token") or "").strip()
    rows = [
        {
            "remote_id": str(row.remote_post_id or "").strip(),
            "title": row.title,
            "url": row.url,
            "category": str(row.canonical_category_slug or row.category_slug or "").strip(),
        }
        for row in db.execute(select(SyncedCloudflarePost)).scalars().all()
        if str(row.status or "").strip().lower() in {"published", "live"}
        and str(row.remote_post_id or "").strip()
    ]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    summary: Counter[str] = Counter()
    examples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    def _scan_one(item: dict[str, Any]) -> dict[str, Any]:
        response = httpx.get(
            f"{base_url}/api/integrations/posts/{item['remote_id']}",
            headers=headers,
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else payload
        detail = data if isinstance(data, dict) else {}
        body = _extract_cloudflare_content_html({"content": detail.get("content")}, detail)
        reasons = _cloudflare_public_body_quality_reasons(body, category_slug=item["category"])
        return {"item": item, "reasons": reasons}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_scan_one, item) for item in rows]
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                summary["detail_fetch_failed"] += 1
                if len(examples["detail_fetch_failed"]) < 15:
                    examples["detail_fetch_failed"].append({"error": str(exc)})
                continue
            summary["scanned"] += 1
            reasons = list(result["reasons"])
            if not reasons:
                continue
            summary["issue_posts"] += 1
            for reason in reasons:
                summary[reason] += 1
            if len(examples["issue_posts"]) < 20:
                examples["issue_posts"].append(
                    {
                        "title": result["item"]["title"],
                        "url": result["item"]["url"],
                        "category": result["item"]["category"],
                        "reasons": reasons,
                    }
                )
    return {
        "total_posts": len(rows),
        "summary": dict(summary),
        "examples": dict(examples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Cloudflare prompt alignment and current public content hygiene.")
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy database URL override.")
    parser.add_argument("--cloudflare-workers", type=int, default=16, help="Parallel workers for Cloudflare detail scan.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()

    database_url = str(args.database_url or _database_url()).strip()
    engine = create_engine(database_url, future=True)

    with Session(engine) as db:
        payload = {
            "prompt_alignment": _prompt_review_payload(),
            "blogger_public_content": _scan_blogger_public_content(db),
            "cloudflare_public_content": _scan_cloudflare_public_content(
                db,
                max_workers=max(int(args.cloudflare_workers), 1),
            ),
        }

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if str(args.output or "").strip():
        output_path = Path(str(args.output)).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
