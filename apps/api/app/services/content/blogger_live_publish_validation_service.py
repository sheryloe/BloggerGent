from __future__ import annotations

import html
import re
import time
from typing import Any

import httpx

from app.services.blogger.blogger_live_audit_service import extract_best_article_fragment


_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_MULTISPACE_RE = re.compile(r"\s+")
_H1_RE = re.compile(r"(?is)<h1\b")
_H2_RE = re.compile(r"(?is)<h2\b")
_IMG_RE = re.compile(r"(?is)<img\b")
_ARTICLE_BODY_ROLE_RE = re.compile(
    r"<section\b[^>]*data-bloggent-role=['\"]article-body['\"][^>]*>(?P<body>.*?)</section>",
    re.IGNORECASE | re.DOTALL,
)
_RELATED_POSTS_BLOCK_RE = re.compile(
    r"<section\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</section>",
    re.IGNORECASE | re.DOTALL,
)
_RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}


def _normalize_text(value: str | None) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    return _MULTISPACE_RE.sub(" ", text).strip()


def _non_space_length(value: str | None) -> int:
    return len(_MULTISPACE_RE.sub("", _normalize_text(value)))


def _excerpt_snippet(value: str | None, *, max_length: int = 160) -> str:
    raw = str(value or "")
    role_match = _ARTICLE_BODY_ROLE_RE.search(raw)
    if role_match is not None:
        raw = str(role_match.group("body") or "")
    paragraph_matches = _PARAGRAPH_RE.findall(raw)
    normalized = _normalize_text(" ".join(paragraph_matches) if paragraph_matches else raw)
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].strip()


def _extract_title(html_text: str | None) -> str:
    raw = str(html_text or "")
    match = _TITLE_RE.search(raw)
    if match is None:
        return ""
    return _normalize_text(match.group(1))


def _normalize_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].strip()


def _count(pattern: re.Pattern[str], value: str | None) -> int:
    return len(pattern.findall(str(value or "")))


def _fetch_live_html(url: str, *, timeout_seconds: float) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    for attempt in range(1, 4):
        try:
            response = httpx.get(
                url,
                timeout=timeout_seconds,
                follow_redirects=True,
                headers=_DEFAULT_HEADERS,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in _RETRYABLE_HTTP_STATUS_CODES or attempt >= 3:
                raise
            time.sleep(0.4 * attempt)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= 3:
                raise
            time.sleep(0.4 * attempt)
    assert last_error is not None
    raise last_error


def validate_blogger_live_publish(
    *,
    published_url: str | None,
    expected_title: str | None,
    expected_hero_url: str | None,
    assembled_html: str | None,
    timeout_seconds: float = 30.0,
    required_article_h1_count: int | None = 1,
) -> dict[str, Any]:
    normalized_url = str(published_url or "").strip()
    normalized_title = _normalize_text(expected_title)
    normalized_hero_url = _normalize_url(expected_hero_url).lower()
    expected_body_snippet = _excerpt_snippet(assembled_html)
    expected_visible_non_space_chars = _non_space_length(assembled_html)
    minimum_live_non_space_chars = max(500, min(1500, max(expected_visible_non_space_chars // 4, 500)))

    payload: dict[str, Any] = {
        "status": "failed",
        "published_url": normalized_url,
        "final_url": normalized_url or None,
        "http_status": None,
        "title_present": False,
        "hero_present": False,
        "body_snippet_present": False,
        "live_content_present": False,
        "expected_visible_non_space_chars": expected_visible_non_space_chars,
        "minimum_live_non_space_chars": minimum_live_non_space_chars,
        "document_visible_non_space_chars": 0,
        "article_visible_non_space_chars": 0,
        "document_h1_count": 0,
        "document_h2_count": 0,
        "document_img_count": 0,
        "document_hero_occurrence_count": 0,
        "article_h1_count": 0,
        "article_h2_count": 0,
        "article_img_count": 0,
        "article_hero_occurrence_count": 0,
        "document_title_present": False,
        "article_title_present": False,
        "article_hero_present": False,
        "article_body_present": False,
        "failure_reasons": [],
        "diagnostic_warnings": [],
    }
    if not normalized_url:
        payload["failure_reasons"] = ["missing_published_url"]
        return payload

    try:
        response = _fetch_live_html(normalized_url, timeout_seconds=timeout_seconds)
    except httpx.HTTPError as exc:
        payload["failure_reasons"] = [f"http_error:{exc}"]
        return payload

    live_html = response.text
    live_html_lower = live_html.lower()
    live_text = _normalize_text(live_html)
    live_title = _extract_title(live_html)
    article_fragment = extract_best_article_fragment(
        live_html,
        expected_title=normalized_title,
        expected_hero_url=normalized_hero_url,
    )
    article_validation_fragment = _RELATED_POSTS_BLOCK_RE.sub("", article_fragment or "")
    article_text = _normalize_text(article_validation_fragment)
    article_html_lower = str(article_validation_fragment or "").lower()

    document_visible_non_space_chars = _non_space_length(live_html)
    article_visible_non_space_chars = _non_space_length(article_validation_fragment)
    document_h1_count = _count(_H1_RE, live_html)
    document_h2_count = _count(_H2_RE, live_html)
    document_img_count = _count(_IMG_RE, live_html)
    article_h1_count = _count(_H1_RE, article_validation_fragment)
    article_h2_count = _count(_H2_RE, article_validation_fragment)
    article_img_count = _count(_IMG_RE, article_validation_fragment)
    document_hero_occurrence_count = live_html_lower.count(normalized_hero_url) if normalized_hero_url else 0
    article_hero_occurrence_count = article_html_lower.count(normalized_hero_url) if normalized_hero_url else 0

    document_title_present = bool(normalized_title) and (
        normalized_title.casefold() in live_text.casefold()
        or normalized_title.casefold() in live_title.casefold()
    )
    article_title_present = bool(normalized_title) and normalized_title.casefold() in article_text.casefold()
    article_hero_present = article_hero_occurrence_count >= 1
    body_snippet_present = bool(expected_body_snippet) and expected_body_snippet.casefold() in article_text.casefold()
    article_body_present = article_visible_non_space_chars >= 200
    live_content_present = (
        article_title_present
        and article_hero_present
        and article_body_present
        and article_visible_non_space_chars >= minimum_live_non_space_chars
    )

    payload.update(
        {
            "http_status": response.status_code,
            "final_url": str(response.url),
            "title_present": article_title_present,
            "hero_present": article_hero_present,
            "body_snippet_present": body_snippet_present,
            "live_content_present": live_content_present,
            "document_visible_non_space_chars": document_visible_non_space_chars,
            "article_visible_non_space_chars": article_visible_non_space_chars,
            "document_h1_count": document_h1_count,
            "document_h2_count": document_h2_count,
            "document_img_count": document_img_count,
            "document_hero_occurrence_count": document_hero_occurrence_count,
            "article_h1_count": article_h1_count,
            "article_h2_count": article_h2_count,
            "article_img_count": article_img_count,
            "article_hero_occurrence_count": article_hero_occurrence_count,
            "document_title_present": document_title_present,
            "article_title_present": article_title_present,
            "article_hero_present": article_hero_present,
            "article_body_present": article_body_present,
            "live_title": live_title or None,
            "expected_body_snippet": expected_body_snippet or None,
            "article_fragment_html": article_fragment or None,
            "article_validation_fragment_html": article_validation_fragment or None,
        }
    )

    failure_reasons: list[str] = []
    diagnostic_warnings: list[str] = []
    if not article_title_present:
        failure_reasons.append("missing_live_title")
    if article_hero_occurrence_count < 1:
        failure_reasons.append("missing_live_hero")
        failure_reasons.append("article_hero_missing")
    elif article_hero_occurrence_count > 1:
        failure_reasons.append("article_hero_multiple")
    if not article_body_present:
        failure_reasons.append("missing_live_body")
    if not body_snippet_present:
        diagnostic_warnings.append("article_body_snippet_mismatch")
    if article_visible_non_space_chars < minimum_live_non_space_chars:
        failure_reasons.append("live_body_too_short")

    if required_article_h1_count is not None:
        if article_h1_count < required_article_h1_count:
            failure_reasons.append("article_h1_missing")
        elif article_h1_count > required_article_h1_count:
            failure_reasons.append("article_h1_multiple")

    payload["failure_reasons"] = failure_reasons
    payload["diagnostic_warnings"] = diagnostic_warnings
    payload["status"] = "ok" if not failure_reasons else "failed"
    return payload
