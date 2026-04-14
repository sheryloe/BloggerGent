from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import Article, BloggerPost, Image, Job, JobStatus, SyncedBloggerPost
from app.utils.embeddings import cosine_similarity, text_to_embedding


def _label_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = {item.lower() for item in left}
    right_set = {item.lower() for item in right}
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _urls_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_link_key(left)
    normalized_right = _normalize_link_key(right)
    if not normalized_left or not normalized_right:
        return False
    return normalized_left == normalized_right


def _titles_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    return SequenceMatcher(a=normalized_left, b=normalized_right).ratio() >= 0.94


def _is_public_related_link(link: str | None) -> bool:
    normalized = (link or "").strip()
    if not normalized or normalized == "#":
        return False

    lowered = normalized.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    if "localhost" in lowered or "127.0.0.1" in lowered or "mock-blogger.local" in lowered:
        return False

    parsed = urlsplit(normalized)
    if not parsed.netloc:
        return False
    if parsed.path.strip() in {"", "/"} and not parsed.query and not parsed.fragment:
        return False
    return True


def _normalize_link_key(link: str | None) -> str:
    if not _is_public_related_link(link):
        return ""
    parsed = urlsplit((link or "").strip())
    hostname = (parsed.netloc or "").strip().lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = unquote(parsed.path or "/").strip() or "/"
    path = re.sub(r"/+", "/", path)
    if path != "/":
        path = path.rstrip("/")
    return f"{hostname}{path}"


def _normalize_related_thumbnail_url(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    normalized_path = quote(unquote(parsed.path or ""), safe="/-_.~")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))


def _replace_path_token(url: str, source: str, target: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path or "")
    if source not in path:
        return ""
    replaced = path.replace(source, target, 1)
    if replaced == path:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, quote(replaced, safe="/-_.~"), parsed.query, parsed.fragment))


def _replace_path_extension(url: str, extension: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path or "")
    dot_index = path.rfind(".")
    slash_index = path.rfind("/")
    if dot_index <= slash_index:
        return ""
    replaced = f"{path[:dot_index]}{extension}"
    return urlunsplit((parsed.scheme, parsed.netloc, quote(replaced, safe="/-_.~"), parsed.query, parsed.fragment))


def _related_thumbnail_fallback_candidates(url: str | None) -> list[str]:
    normalized = _normalize_related_thumbnail_url(url)
    if not normalized:
        return []

    candidates: list[str] = []
    for source, target in (
        ("/assets/media/", "/assets/assets/media/"),
        ("/assets/assets/media/", "/assets/media/"),
    ):
        swapped = _replace_path_token(normalized, source, target)
        if swapped:
            candidates.append(swapped)

    lowered_path = urlsplit(normalized).path.lower()
    if lowered_path.endswith(".webp"):
        for ext in (".jpg", ".jpeg"):
            switched = _replace_path_extension(normalized, ext)
            if switched:
                candidates.append(switched)
        for base in list(candidates):
            if urlsplit(base).path.lower().endswith(".webp"):
                for ext in (".jpg", ".jpeg"):
                    switched = _replace_path_extension(base, ext)
                    if switched:
                        candidates.append(switched)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = _normalize_related_thumbnail_url(candidate)
        if not normalized_candidate or normalized_candidate == normalized:
            continue
        if normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        out.append(normalized_candidate)
    return out


def _escape_js_single_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _related_thumbnail_onerror(url: str | None) -> str:
    fallbacks = _related_thumbnail_fallback_candidates(url)
    if not fallbacks:
        return "this.onerror=null;this.style.display='none';"

    parts = []
    for index, candidate in enumerate(fallbacks):
        escaped = _escape_js_single_quote(candidate)
        token = f"fb{index}"
        parts.append(
            f"if(this.dataset.{token}!=='1'){{this.dataset.{token}='1';this.src='{escaped}';return;}}"
        )
    parts.append("this.onerror=null;this.style.display='none';")
    return "".join(parts)


def _normalize_topic_value(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _same_cluster_and_angle(left: Article, right: Article) -> bool:
    left_topic = getattr(left, "topic", None)
    right_topic = getattr(right, "topic", None)
    if not left_topic or not right_topic:
        return False

    left_cluster = _normalize_topic_value(left_topic.topic_cluster_label)
    right_cluster = _normalize_topic_value(right_topic.topic_cluster_label)
    left_angle = _normalize_topic_value(left_topic.topic_angle_label)
    right_angle = _normalize_topic_value(right_topic.topic_angle_label)
    if not left_cluster or not right_cluster or not left_angle or not right_angle:
        return False
    return left_cluster == right_cluster and left_angle == right_angle


def _related_source_rank(payload: dict[str, Any]) -> int:
    return 1 if str(payload.get("source") or "").strip().lower() == "generated" else 0


def _should_replace_related_payload(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_rank = (
        _related_source_rank(candidate),
        float(candidate.get("score") or 0.0),
        str(candidate.get("published_at") or ""),
    )
    current_rank = (
        _related_source_rank(current),
        float(current.get("score") or 0.0),
        str(current.get("published_at") or ""),
    )
    return candidate_rank > current_rank


def _related_payload(
    *,
    score: float,
    title: str,
    excerpt: str,
    thumbnail: str,
    link: str,
    source: str,
    published_at,
    slug: str | None = None,
) -> dict[str, Any]:
    return {
        "score": round(score, 4),
        "title": title,
        "slug": slug or "",
        "excerpt": excerpt,
        "thumbnail": thumbnail,
        "link": link,
        "source": source,
        "published_at": published_at.isoformat() if published_at else None,
    }


def _resolve_related_thumbnail(image: Image | None) -> str:
    if not image:
        return ""

    metadata = image.image_metadata if isinstance(image.image_metadata, dict) else {}
    delivery = metadata.get("delivery") if isinstance(metadata, dict) else None
    if isinstance(delivery, dict):
        cloudflare_meta = delivery.get("cloudflare")
        if isinstance(cloudflare_meta, dict):
            original_url = str(cloudflare_meta.get("original_url") or "").strip()
            if original_url:
                return _normalize_related_thumbnail_url(original_url)

        cloudinary_meta = delivery.get("cloudinary")
        if isinstance(cloudinary_meta, dict):
            original_url = str(cloudinary_meta.get("secure_url_original") or "").strip()
            if original_url:
                return _normalize_related_thumbnail_url(original_url)

        local_public_url = str(delivery.get("local_public_url") or "").strip()
        if local_public_url:
            return _normalize_related_thumbnail_url(local_public_url)

        public_url = str(delivery.get("public_url") or "").strip()
        if public_url:
            return _normalize_related_thumbnail_url(public_url)

    return _normalize_related_thumbnail_url(str(image.public_url or "").strip())


def _build_synced_related_candidate_maps(
    synced_candidates: list[SyncedBloggerPost],
) -> tuple[dict[str, SyncedBloggerPost], dict[str, SyncedBloggerPost]]:
    by_link_key: dict[str, SyncedBloggerPost] = {}
    by_title_key: dict[str, SyncedBloggerPost] = {}
    for candidate in synced_candidates:
        link_key = _normalize_link_key(candidate.url)
        if link_key and link_key not in by_link_key:
            by_link_key[link_key] = candidate
        title_key = _normalize_text(candidate.title)
        if title_key and title_key not in by_title_key:
            by_title_key[title_key] = candidate
    return by_link_key, by_title_key


def _payload_for_synced_candidate(*, candidate: SyncedBloggerPost, score: float) -> dict[str, Any]:
    return _related_payload(
        score=score,
        title=candidate.title,
        excerpt=candidate.excerpt_text,
        thumbnail=_normalize_related_thumbnail_url(candidate.thumbnail_url or ""),
        link=candidate.url or "#",
        source="synced",
        published_at=candidate.published_at,
    )


def _resolve_generated_candidate_payload(
    *,
    article: Article,
    candidate: Article,
    score: float,
    current_url: str | None,
    synced_by_link_key: dict[str, SyncedBloggerPost],
    synced_by_title_key: dict[str, SyncedBloggerPost],
) -> dict[str, Any] | None:
    candidate_link = candidate.blogger_post.published_url if candidate.blogger_post else "#"
    if _urls_match(candidate_link, current_url) or _titles_match(candidate.title, article.title):
        return None

    candidate_link_key = _normalize_link_key(candidate_link)
    candidate_title_key = _normalize_text(candidate.title)
    live_candidate = synced_by_link_key.get(candidate_link_key) if candidate_link_key else None
    if live_candidate is None and candidate_title_key:
        live_candidate = synced_by_title_key.get(candidate_title_key)
    if live_candidate is None:
        return None
    if _urls_match(live_candidate.url, current_url) or _titles_match(live_candidate.title, article.title):
        return None
    return _payload_for_synced_candidate(candidate=live_candidate, score=score)


def find_related_articles(db: Session, article: Article, limit: int | None = None) -> list[dict]:
    limit = limit or settings.related_post_count
    generated_query = (
        select(Article)
        .join(Job, Job.id == Article.job_id)
        .outerjoin(Image, Image.article_id == Article.id)
        .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Job.status == JobStatus.COMPLETED, Article.blog_id == article.blog_id, Article.id != article.id)
        .options(selectinload(Article.image), selectinload(Article.blogger_post), selectinload(Article.topic))
        .order_by(Article.created_at.desc())
    )
    synced_query = (
        select(SyncedBloggerPost)
        .where(SyncedBloggerPost.blog_id == article.blog_id)
        .order_by(
            SyncedBloggerPost.published_at.desc().nullslast(),
            SyncedBloggerPost.updated_at_remote.desc().nullslast(),
            SyncedBloggerPost.id.desc(),
        )
    )

    generated_candidates = db.execute(generated_query).scalars().unique().all()
    synced_candidates = db.execute(synced_query).scalars().all()
    synced_by_link_key, synced_by_title_key = _build_synced_related_candidate_maps(synced_candidates)
    base_embedding = text_to_embedding(f"{article.title} {article.excerpt}")
    current_url = article.blogger_post.published_url if article.blogger_post else None

    ranked: list[tuple[float, dict[str, Any]]] = []

    for candidate in generated_candidates:
        if _same_cluster_and_angle(article, candidate):
            continue
        candidate_embedding = text_to_embedding(f"{candidate.title} {candidate.excerpt}")
        embedding_score = cosine_similarity(base_embedding, candidate_embedding)
        label_score = _label_similarity(article.labels or [], candidate.labels or [])
        score = (label_score * 0.6) + (embedding_score * 0.4)
        payload = _resolve_generated_candidate_payload(
            article=article,
            candidate=candidate,
            score=score,
            current_url=current_url,
            synced_by_link_key=synced_by_link_key,
            synced_by_title_key=synced_by_title_key,
        )
        if payload is None:
            continue
        ranked.append((score, payload))

    for candidate in synced_candidates:
        if _urls_match(candidate.url, current_url) or _titles_match(candidate.title, article.title):
            continue
        candidate_text = " ".join(
            [
                candidate.title,
                candidate.excerpt_text or "",
                " ".join(candidate.labels or []),
            ]
        ).strip()
        candidate_embedding = text_to_embedding(candidate_text)
        embedding_score = cosine_similarity(base_embedding, candidate_embedding)
        label_score = _label_similarity(article.labels or [], candidate.labels or [])
        score = (label_score * 0.6) + (embedding_score * 0.4)
        ranked.append((score, _payload_for_synced_candidate(candidate=candidate, score=score)))

    ranked.sort(
        key=lambda item: (
            item[0],
            _related_source_rank(item[1]),
            str(item[1].get("published_at") or ""),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    seen_links: dict[str, int] = {}
    seen_titles: dict[str, int] = {}

    for _, payload in ranked:
        link_key = _normalize_link_key(payload.get("link"))
        if not link_key:
            continue

        normalized_title = _normalize_text(payload.get("title"))
        existing_index = seen_links.get(link_key)
        if existing_index is None and normalized_title:
            existing_index = seen_titles.get(normalized_title)

        if existing_index is not None:
            if _should_replace_related_payload(payload, selected[existing_index]):
                selected[existing_index] = payload
                seen_links[link_key] = existing_index
                if normalized_title:
                    seen_titles[normalized_title] = existing_index
            continue

        seen_links[link_key] = len(selected)
        if normalized_title:
            seen_titles[normalized_title] = len(selected)
        selected.append(payload)

    if len(selected) < limit:
        fallback_payloads: list[dict[str, Any]] = []

        for candidate in generated_candidates:
            payload = _resolve_generated_candidate_payload(
                article=article,
                candidate=candidate,
                score=0.0,
                current_url=current_url,
                synced_by_link_key=synced_by_link_key,
                synced_by_title_key=synced_by_title_key,
            )
            if payload is not None:
                fallback_payloads.append(payload)

        for candidate in synced_candidates:
            if _urls_match(candidate.url, current_url) or _titles_match(candidate.title, article.title):
                continue
            fallback_payloads.append(_payload_for_synced_candidate(candidate=candidate, score=0.0))

        fallback_payloads.sort(
            key=lambda payload: (
                _related_source_rank(payload),
                str(payload.get("published_at") or ""),
            ),
            reverse=True,
        )

        for payload in fallback_payloads:
            if len(selected) >= limit:
                break
            link_key = _normalize_link_key(payload.get("link"))
            if not link_key:
                continue
            normalized_title = _normalize_text(payload.get("title"))
            if link_key in seen_links:
                continue
            if normalized_title and normalized_title in seen_titles:
                continue
            seen_links[link_key] = len(selected)
            if normalized_title:
                seen_titles[normalized_title] = len(selected)
            selected.append(payload)

    return selected[:limit]


def render_related_cards_html(
    related_posts: list[dict],
    section_title: str = "Related Posts",
    *,
    category: str = "",
    empty_message: str = "Relevant posts will appear here once this blog has more published content.",
) -> str:
    category = (category or "").lower()
    card_background = "#f8fafc"
    card_border = "#e2e8f0"
    heading_color = "#0f172a"
    body_color = "#475569"

    filtered_posts: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for post in related_posts:
        link_key = _normalize_link_key(str(post.get("link") or ""))
        if not link_key or link_key in seen_links:
            continue
        seen_links.add(link_key)
        filtered_posts.append(post)

    if not filtered_posts:
        return (
            f"<section class='related-posts'><h2>{section_title}</h2>"
            f"<p>{html.escape(empty_message)}</p></section>"
        )

    cards = []
    for post in filtered_posts:
        title = html.escape(str(post.get("title") or ""), quote=True)
        excerpt = html.escape(str(post.get("excerpt") or ""), quote=True)
        link = html.escape(str(post.get("link") or ""), quote=True)
        raw_thumbnail_url = _normalize_related_thumbnail_url(str(post.get("thumbnail") or ""))
        thumbnail_url = html.escape(raw_thumbnail_url, quote=True)
        onerror_attr = html.escape(_related_thumbnail_onerror(raw_thumbnail_url), quote=True)
        thumbnail = (
            f"<img src='{thumbnail_url}' alt='{title}' "
            f"loading='lazy' decoding='async' onerror=\"{onerror_attr}\" "
            "style='width:100%;height:120px;object-fit:cover;border-radius:14px;' />"
            if post.get("thumbnail")
            else ""
        )
        cards.append(
            f"<a href='{link}' style='display:block;text-decoration:none;color:#1f2937;'>"
            f"<div style='border:1px solid {card_border};border-radius:18px;padding:14px;background:{card_background};backdrop-filter:blur(8px);'>"
            f"{thumbnail}"
            f"<h3 style='font-size:18px;margin:12px 0 8px;color:{heading_color};'>{title}</h3>"
            f"<p style='font-size:14px;line-height:1.7;color:{body_color};'>{excerpt}</p>"
            "</div></a>"
        )

    return (
        "<section class='related-posts' style='margin-top:36px;'>"
        f"<h2 style='font-size:28px;margin-bottom:16px;color:{heading_color};'>{section_title}</h2>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;'>"
        + "".join(cards)
        + "</div></section>"
    )
