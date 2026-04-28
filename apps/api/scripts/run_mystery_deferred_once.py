from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@localhost:15432/bloggent"
DEFAULT_TOPIC_MODEL = "gpt-4.1-2025-04-14"
DEFAULT_ARTICLE_MODEL = "gpt-4.1-mini-2025-04-14"
DEFAULT_PROMPT_MODEL = "gpt-4.1-mini-2025-04-14"
MYSTERY_BLOG_ID = 35
MYSTERY_CATEGORY_KEY = "case-files"
MYSTERY_CATEGORY_LABEL = "Case Files"
MYSTERY_CATEGORY_GUIDANCE = "Focus on documented cases, investigations, timelines, evidence, and unresolved factual questions."

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, SyncedBloggerPost  # noqa: E402
from app.schemas.ai import ArticleGenerationOutput, TopicDiscoveryPayload  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.content.faq_hygiene import filter_generic_faq_items  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.providers.factory import get_runtime_config  # noqa: E402
from publish_mystery_generated_draft import run as publish_draft_run  # noqa: E402


TAG_RE = re.compile(r"<[^>]+>")
NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
DETAILS_RE = re.compile(r"<details\b", re.IGNORECASE)
COMMON_TERMS = {
    "case",
    "file",
    "files",
    "mystery",
    "incident",
    "archive",
    "archives",
    "disappearance",
    "vanishing",
    "unsolved",
    "unknown",
    "documented",
    "evidence",
    "investigation",
    "historical",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and publish one Mystery Blogger post with manual image defer.")
    parser.add_argument("--blog-id", type=int, default=MYSTERY_BLOG_ID)
    parser.add_argument("--topic", default="")
    parser.add_argument("--topic-candidates", type=int, default=6)
    parser.add_argument("--topic-model", default=DEFAULT_TOPIC_MODEL)
    parser.add_argument("--article-model", default=DEFAULT_ARTICLE_MODEL)
    parser.add_argument("--prompt-model", default=DEFAULT_PROMPT_MODEL)
    parser.add_argument("--publish-live", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _plain_text(html_value: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", html_value))).strip()


def _slugify(value: str) -> str:
    slug = NON_SLUG_RE.sub("-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)[:90].strip("-")


def _significant_terms(value: str) -> list[str]:
    terms = []
    for term in re.split(r"[^a-z0-9]+", value.lower()):
        if len(term) < 4 or term in COMMON_TERMS:
            continue
        terms.append(term)
    return list(dict.fromkeys(terms))[:8]


def _render_template(path: Path, values: dict[str, Any]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _openai_chat(
    *,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    json_object: bool,
    timeout: float = 240.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text
        try:
            detail = response.json().get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise RuntimeError(f"openai_call_failed:{response.status_code}:{detail}") from exc
    return response.json()


def _content_from_response(response: dict[str, Any]) -> str:
    return str(response["choices"][0]["message"]["content"] or "").strip()


def _usage_event(stage: str, model: str, response: dict[str, Any]) -> dict[str, Any]:
    usage = dict(response.get("usage") or {})
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return {
        "stage": stage,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
    }


def _summarize_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for event in events:
        model_bucket = by_model[str(event["model"])]
        model_bucket["calls"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            model_bucket[key] += int(event.get(key) or 0)
            total[key] += int(event.get(key) or 0)
    return {"events": events, "by_model": dict(by_model), "total": total}


def _load_existing_records(db, blog_id: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    articles = db.execute(
        select(Article.title, Article.slug)
        .where(Article.blog_id == blog_id)
        .order_by(Article.id.desc())
        .limit(240)
    ).all()
    records.extend({"title": _safe_str(title), "slug": _safe_str(slug), "url": ""} for title, slug in articles)
    synced = db.execute(
        select(SyncedBloggerPost.title, SyncedBloggerPost.url)
        .where(SyncedBloggerPost.blog_id == blog_id)
        .order_by(SyncedBloggerPost.id.desc())
        .limit(240)
    ).all()
    records.extend({"title": _safe_str(title), "slug": "", "url": _safe_str(url)} for title, url in synced)
    return records


def _is_duplicate_candidate(candidate: str, records: list[dict[str, str]]) -> bool:
    slug = _slugify(candidate)
    terms = _significant_terms(candidate + " " + slug)
    if not terms:
        return False
    required_hits = 2 if len(terms) >= 2 else 1
    for record in records:
        haystack = f"{record.get('title', '')} {record.get('slug', '')} {record.get('url', '')}".lower()
        if slug and slug in haystack:
            return True
        if sum(1 for term in terms if term in haystack) >= required_hits:
            return True
    return False


def _exclusion_prompt(records: list[dict[str, str]], limit: int = 80) -> str:
    lines = []
    for record in records[:limit]:
        label = record.get("title") or record.get("slug") or record.get("url")
        if label:
            lines.append(f"- {label}")
    if not lines:
        return ""
    return "\n\n[Existing published/DB coverage to avoid]\n" + "\n".join(lines) + "\n"


def _pick_topic(
    *,
    api_key: str,
    blog: Blog,
    records: list[dict[str, str]],
    topic_model: str,
    topic_override: str,
    topic_candidates: int,
    usage_events: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if topic_override:
        if _is_duplicate_candidate(topic_override, records):
            raise RuntimeError(f"topic_duplicate_blocked:{topic_override}")
        return topic_override, {"keyword": topic_override, "reason": "User supplied topic.", "trend_score": 0.0}, {}

    template = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "mystery_topic_discovery.md"
    prompt = _render_template(
        template,
        {
            "blog_name": blog.name,
            "current_date": datetime.now(timezone.utc).date().isoformat(),
            "target_audience": blog.target_audience or "English readers who like documentary mystery cases.",
            "content_brief": blog.content_brief or "Documented mysteries, strange records, and unresolved cases.",
            "editorial_category_key": MYSTERY_CATEGORY_KEY,
            "editorial_category_label": MYSTERY_CATEGORY_LABEL,
            "editorial_category_guidance": MYSTERY_CATEGORY_GUIDANCE,
            "topic_count": max(3, int(topic_candidates)),
        },
    )
    prompt += _exclusion_prompt(records)
    response = _openai_chat(
        api_key=api_key,
        model=topic_model,
        system="Return precise JSON only for a mystery topic discovery pipeline.",
        prompt=prompt,
        temperature=0.4,
        json_object=True,
        timeout=180.0,
    )
    usage_events.append(_usage_event("topic_discovery", topic_model, response))
    payload = TopicDiscoveryPayload.model_validate_json(_content_from_response(response))
    for item in payload.topics:
        if not _is_duplicate_candidate(item.keyword, records):
            return item.keyword, item.model_dump(), response
    raise RuntimeError("topic_selection_failed_all_candidates_duplicate")


def _normalize_article_output(keyword: str, response: dict[str, Any]) -> ArticleGenerationOutput:
    content = _content_from_response(response)
    data = json.loads(content)
    faq_section = data.get("faq_section")
    if isinstance(faq_section, dict):
        faq_section = faq_section.get("questions") or faq_section.get("items") or faq_section.get("faqs") or []
    if isinstance(faq_section, list):
        normalized_faq = []
        for item in faq_section:
            if isinstance(item, dict):
                question = _safe_str(item.get("question") or item.get("q") or item.get("title"))
                answer = _safe_str(item.get("answer") or item.get("a") or item.get("text"))
                if question and answer:
                    normalized_faq.append({"question": question, "answer": answer})
            elif isinstance(item, str) and item.strip():
                normalized_faq.append({"question": item.strip().rstrip("?") + "?", "answer": "The article above separates the documented record from later interpretation."})
        data["faq_section"] = normalized_faq
    else:
        data["faq_section"] = []
    payload = ArticleGenerationOutput.model_validate(data)
    normalized = payload.model_dump()
    normalized["slug"] = _slugify(normalized.get("slug") or normalized.get("title") or keyword)
    if MYSTERY_CATEGORY_LABEL not in normalized["labels"]:
        normalized["labels"] = [MYSTERY_CATEGORY_LABEL, *normalized["labels"]]
    normalized["labels"] = list(dict.fromkeys([_safe_str(item) for item in normalized["labels"] if _safe_str(item)]))[:8]
    normalized["faq_section"] = filter_generic_faq_items(
        [
            item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for item in (payload.faq_section or [])
        ]
    )
    return ArticleGenerationOutput.model_validate(normalized)


def _generate_article(
    *,
    api_key: str,
    blog: Blog,
    keyword: str,
    topic_payload: dict[str, Any],
    article_model: str,
    prompt_model: str,
    usage_events: list[dict[str, Any]],
) -> tuple[ArticleGenerationOutput, dict[str, Any], dict[str, Any]]:
    planner_brief = (
        f"- Selected keyword: {keyword}\n"
        f"- Selection reason: {topic_payload.get('reason', '')}\n"
        f"- Required approach: build a documentary case file with a timeline, records, competing explanations, "
        f"and a clear boundary between confirmed details and speculation."
    )
    article_template = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "mystery_article_generation.md"
    article_prompt = _render_template(
        article_template,
        {
            "blog_name": blog.name,
            "keyword": keyword,
            "current_date": datetime.now(timezone.utc).date().isoformat(),
            "target_audience": blog.target_audience or "English readers who like documentary mystery cases.",
            "content_brief": blog.content_brief or "Documented mysteries, strange records, and unresolved cases.",
            "planner_brief": planner_brief,
            "editorial_category_label": MYSTERY_CATEGORY_LABEL,
            "editorial_category_guidance": MYSTERY_CATEGORY_GUIDANCE,
        },
    )
    article_prompt += (
        "\n\n[Extra publish rules]\n"
        "- Include one section that states what is confirmed, what is reported, and what remains disputed.\n"
        "- Do not include any <img> tag or visible placeholder image.\n"
        "- Put FAQ content in faq_section JSON, not as visible <details> inside html_article.\n"
    )
    response = _openai_chat(
        api_key=api_key,
        model=article_model,
        system="Return one valid JSON object for the article package. No markdown fences.",
        prompt=article_prompt,
        temperature=0.65,
        json_object=True,
        timeout=240.0,
    )
    usage_events.append(_usage_event("article_generation", article_model, response))
    article = _normalize_article_output(keyword, response)

    prompt_template = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "mystery_collage_prompt.md"
    prompt_request = _render_template(
        prompt_template,
        {
            "original_prompt": article.image_collage_prompt,
            "blog_name": blog.name,
            "article_title": article.title,
            "article_excerpt": article.excerpt,
            "article_context": _plain_text(article.html_article)[:1400],
        },
    )
    prompt_response = _openai_chat(
        api_key=api_key,
        model=prompt_model,
        system="Rewrite image prompts as plain text only. Do not generate images.",
        prompt=prompt_request,
        temperature=0.45,
        json_object=False,
        timeout=120.0,
    )
    usage_events.append(_usage_event("image_prompt_refinement_text_only", prompt_model, prompt_response))
    refined_prompt = _content_from_response(prompt_response)
    if refined_prompt:
        article = ArticleGenerationOutput.model_validate({**article.model_dump(), "image_collage_prompt": refined_prompt})
    return article, response, prompt_response


def _write_draft(
    *,
    blog: Blog,
    keyword: str,
    topic_payload: dict[str, Any],
    article: ArticleGenerationOutput,
    topic_response: dict[str, Any],
    article_response: dict[str, Any],
    prompt_response: dict[str, Any],
    usage: dict[str, Any],
) -> Path:
    generated_at = datetime.now(timezone.utc)
    article_payload = article.model_dump()
    article_payload["keyword"] = keyword
    article_payload["plain_text_characters"] = len(_plain_text(article.html_article))
    article_payload["image_prompt_word_count"] = len(article.image_collage_prompt.split())
    draft = {
        "generated_at": generated_at.isoformat(),
        "scope": {
            "blog_id": blog.id,
            "profile_key": blog.profile_key,
            "published": False,
            "db_written": False,
            "image_generated": False,
            "image_deferred": True,
        },
        "models": {
            "topic_model": topic_response.get("model"),
            "article_model": article_response.get("model"),
            "prompt_model": prompt_response.get("model"),
        },
        "dedupe": {
            "method": "DB/live title, slug, URL, and significant-term screening before generation",
            "selected_topic": topic_payload,
        },
        "article": article_payload,
        "planner": {
            "keyword": keyword,
            "title": article.title,
            "slug": article.slug,
            "editorial_category_key": MYSTERY_CATEGORY_KEY,
            "editorial_category_label": MYSTERY_CATEGORY_LABEL,
            "reason": topic_payload.get("reason", ""),
            "trend_score": topic_payload.get("trend_score", 0.0),
        },
        "usage": usage,
    }
    out_dir = Path(os.environ.get("STORAGE_ROOT") or "/app/storage") / "the-midnight-archives" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mystery-draft-{article.slug}-defer-{generated_at.strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def run(args: argparse.Namespace) -> dict[str, Any]:
    usage_events: list[dict[str, Any]] = []
    with SessionLocal() as db:
        blog = db.get(Blog, int(args.blog_id))
        if blog is None:
            raise RuntimeError(f"blog_not_found:{args.blog_id}")
        if int(blog.id) != MYSTERY_BLOG_ID or _safe_str(blog.profile_key) != "world_mystery":
            raise RuntimeError(f"refusing_non_english_mystery_blog:{blog.id}:{blog.profile_key}")

        settings_map = get_settings_map(db)
        if _safe_str(settings_map.get("provider_mode")) != "live":
            raise RuntimeError(f"provider_mode_not_live:{settings_map.get('provider_mode')}")
        runtime = get_runtime_config(db)
        if not runtime.openai_api_key:
            raise RuntimeError("openai_api_key_missing")

        sync_blogger_posts_for_blog(db, blog)
        records = _load_existing_records(db, blog.id)
        keyword, topic_payload, topic_response = _pick_topic(
            api_key=runtime.openai_api_key,
            blog=blog,
            records=records,
            topic_model=args.topic_model,
            topic_override=_safe_str(args.topic),
            topic_candidates=args.topic_candidates,
            usage_events=usage_events,
        )
        article, article_response, prompt_response = _generate_article(
            api_key=runtime.openai_api_key,
            blog=blog,
            keyword=keyword,
            topic_payload=topic_payload,
            article_model=args.article_model,
            prompt_model=args.prompt_model,
            usage_events=usage_events,
        )
        if _is_duplicate_candidate(article.title + " " + article.slug, records):
            raise RuntimeError(f"article_duplicate_blocked:{article.title}")
        usage = _summarize_usage(usage_events)
        draft_path = _write_draft(
            blog=blog,
            keyword=keyword,
            topic_payload=topic_payload,
            article=article,
            topic_response=topic_response,
            article_response=article_response,
            prompt_response=prompt_response,
            usage=usage,
        )

    publish_args = argparse.Namespace(
        blog_id=int(args.blog_id),
        draft_path=str(draft_path),
        publish_live=bool(args.publish_live),
        defer_images=True,
        timeout=float(args.timeout),
    )
    publish_result = publish_draft_run(publish_args)
    return {
        "status": "ok",
        "draft_path": str(draft_path),
        "topic": keyword,
        "title": publish_result.get("title"),
        "published_url": publish_result.get("published_url"),
        "article_id": publish_result.get("article_id"),
        "job_id": publish_result.get("job_id"),
        "manual_image_deferred": publish_result.get("manual_image_deferred"),
        "manual_image_slots": publish_result.get("manual_image_slots") or [],
        "manual_image_prompt_chat": publish_result.get("manual_image_prompt_chat") or "",
        "usage": usage,
        "publish_result": publish_result,
    }


def main() -> None:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
