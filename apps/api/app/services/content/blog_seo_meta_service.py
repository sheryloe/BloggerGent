from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, Blog, BloggerPost, PostStatus
from app.schemas.api import SeoMetaStatusRead
from app.services.platform.blog_service import clear_blog_seo_meta_verified, mark_blog_seo_meta_verified

PATCH_SNIPPET = """<!-- Bloggent SEO meta patch -->
<meta expr:content='data:blog.metaDescription' name='description'/>
<meta expr:content='data:blog.metaDescription' property='og:description'/>
<meta expr:content='data:blog.metaDescription' name='twitter:description'/>
<script>
document.addEventListener('DOMContentLoaded', function () {
  var article = document.querySelector('article[data-bloggent-meta-description]');
  var embedded = document.getElementById('bloggent-seo-meta');
  var description = '';

  if (article) {
    description = article.getAttribute('data-bloggent-meta-description') || '';
  }
  if (!description && embedded) {
    description = (embedded.textContent || '').trim();
  }
  if (!description) return;

  function upsertMeta(selector, attrs) {
    var node = document.head.querySelector(selector);
    if (!node) {
      node = document.createElement('meta');
      document.head.appendChild(node);
    }
    Object.keys(attrs).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
  }

  upsertMeta('meta[name="description"]', { name: 'description', content: description });
  upsertMeta('meta[property="og:description"]', { property: 'og:description', content: description });
  upsertMeta('meta[name="twitter:description"]', { name: 'twitter:description', content: description });
});
</script>"""

PATCH_STEPS = [
    "In Blogger, go to Settings > Meta tags and turn on search description.",
    "In Blogger, open Theme > Edit HTML.",
    "Inside <head>, remove duplicate custom description blocks from older experiments.",
    "Paste the Bloggent SEO meta patch into <head> and save the theme.",
    "Bloggent embeds the article meta description into the post body with article[data-bloggent-meta-description] and #bloggent-seo-meta.",
    "The theme script reads that embedded description on article pages and overwrites description, og:description, and twitter:description in the live DOM.",
    "Bloggent intentionally avoids Blogger API customMetaData because it does not render real head tags and can wipe manually entered search descriptions on update.",
]


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def _extract_head(html: str) -> str:
    match = re.search(r"<head\b[^>]*>(.*?)</head>", html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _extract_embedded_description(document_html: str) -> str | None:
    attr_match = re.search(
        r'data-bloggent-meta-description=["\']([^"\']*)["\']',
        document_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if attr_match:
        value = html.unescape(attr_match.group(1)).strip()
        if value:
            return value

    hidden_match = re.search(
        r'<div\b[^>]*id=["\']bloggent-seo-meta["\'][^>]*>(.*?)</div>',
        document_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if hidden_match:
        value = re.sub(r"<[^>]+>", "", hidden_match.group(1))
        value = html.unescape(value).strip()
        if value:
            return value
    return None


def _has_theme_patch(document_html: str) -> bool:
    return "Bloggent SEO meta patch" in document_html or "bloggent-seo-meta" in document_html


def _extract_meta(head_html: str, *, name: str | None = None, prop: str | None = None) -> str | None:
    for match in re.finditer(r"<meta\b[^>]*>", head_html, flags=re.IGNORECASE):
        tag = match.group(0)
        content_match = re.search(r'content=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        if not content_match:
            continue
        if name and re.search(rf'name=["\']{re.escape(name)}["\']', tag, flags=re.IGNORECASE):
            return content_match.group(1).strip()
        if prop and re.search(rf'property=["\']{re.escape(prop)}["\']', tag, flags=re.IGNORECASE):
            return content_match.group(1).strip()
    return None


def _build_status(
    *,
    key: str,
    label: str,
    actual: str | None,
    expected: str | None,
    fallback_description: str | None = None,
    fallback_active: bool = False,
) -> SeoMetaStatusRead:
    normalized_actual = _normalize(actual)
    normalized_expected = _normalize(expected)
    normalized_fallback = _normalize(fallback_description)

    if not normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="warning",
            actual=actual,
            expected=expected,
            message="No expected meta description is stored for comparison.",
        )
    if not normalized_actual:
        if fallback_active and normalized_fallback == normalized_expected:
            return SeoMetaStatusRead(
                key=key,
                label=label,
                status="ok",
                actual=fallback_description,
                expected=expected,
                message="The Bloggent theme patch will inject this meta tag from the embedded article description at runtime.",
            )
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="warning",
            actual=actual,
            expected=expected,
            message="The raw public page source does not contain this meta tag.",
        )
    if normalized_actual == normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="ok",
            actual=actual,
            expected=expected,
            message="The raw public page source matches the expected description.",
        )
    if fallback_active and normalized_fallback == normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="ok",
            actual=fallback_description,
            expected=expected,
            message="The raw source differs, but the Bloggent theme patch is ready to overwrite this meta tag from the embedded article description.",
        )
    return SeoMetaStatusRead(
        key=key,
        label=label,
        status="warning",
        actual=actual,
        expected=expected,
        message="The raw public page source does not match the expected description.",
    )


def _empty_status(expected: str | None) -> SeoMetaStatusRead:
    return SeoMetaStatusRead(
        key="unverified",
        label="verification",
        status="idle",
        actual=None,
        expected=expected,
        message="Verification has not been run yet.",
    )


def _build_verification_payload(*, expected: str | None, target_url: str | None, warnings: list[str]) -> dict:
    empty_status = _empty_status(expected)
    return {
        "verification_target_url": target_url,
        "expected_meta_description": expected,
        "warnings": warnings,
        "head_meta_description_status": empty_status,
        "og_description_status": empty_status,
        "twitter_description_status": empty_status,
    }


def _verify_target_meta(*, target_url: str | None, expected: str | None, warnings: list[str]) -> dict:
    payload = _build_verification_payload(expected=expected, target_url=target_url, warnings=list(warnings))
    if not target_url:
        return payload

    try:
        response = httpx.get(target_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        payload["warnings"] = [*warnings, f"Could not load the public page source. {exc}"]
        return payload

    head_html = _extract_head(response.text)
    embedded_description = _extract_embedded_description(response.text)
    fallback_active = _has_theme_patch(response.text)
    payload["head_meta_description_status"] = _build_status(
        key="head_meta_description",
        label="head meta description",
        actual=_extract_meta(head_html, name="description"),
        expected=expected,
        fallback_description=embedded_description,
        fallback_active=fallback_active,
    )
    payload["og_description_status"] = _build_status(
        key="og_description",
        label="og:description",
        actual=_extract_meta(head_html, prop="og:description"),
        expected=expected,
        fallback_description=embedded_description,
        fallback_active=fallback_active,
    )
    payload["twitter_description_status"] = _build_status(
        key="twitter_description",
        label="twitter:description",
        actual=_extract_meta(head_html, name="twitter:description"),
        expected=expected,
        fallback_description=embedded_description,
        fallback_active=fallback_active,
    )

    if fallback_active and embedded_description:
        payload["warnings"] = [
            *payload["warnings"],
            "This blog uses the Bloggent theme fallback. Google can render the runtime meta update, but non-rendering crawlers may still read the raw source only.",
        ]

    return payload


def _latest_published_pair(db: Session, blog_id: int) -> tuple[Article | None, BloggerPost | None]:
    row = db.execute(
        select(Article, BloggerPost)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id == blog_id, BloggerPost.post_status == PostStatus.PUBLISHED)
        .order_by(BloggerPost.published_at.desc().nullslast(), BloggerPost.created_at.desc())
        .limit(1)
    ).first()
    if not row:
        return None, None
    return row[0], row[1]


def get_blog_seo_meta_overview(db: Session, blog: Blog) -> dict:
    article, post = _latest_published_pair(db, blog.id)
    expected_meta_description = article.meta_description if article else None
    verification_target_url = post.published_url if post else None
    warnings: list[str] = []

    if not blog.seo_theme_patch_installed:
        warnings.append(
            "Blogger API customMetaData does not reliably become real head meta tags. Add the Bloggent theme patch in Blogger Theme > Edit HTML."
        )
    if not verification_target_url:
        warnings.append("No public Blogger post is available yet, so there is nothing to verify.")

    return {
        "blog_id": blog.id,
        "seo_theme_patch_installed": blog.seo_theme_patch_installed,
        "seo_theme_patch_verified": bool(blog.seo_theme_patch_verified_at),
        "seo_theme_patch_verified_at": blog.seo_theme_patch_verified_at,
        "patch_snippet": PATCH_SNIPPET,
        "patch_steps": PATCH_STEPS,
        **_build_verification_payload(
            expected=expected_meta_description,
            target_url=verification_target_url,
            warnings=warnings,
        ),
    }


def verify_blog_seo_meta(db: Session, blog: Blog) -> dict:
    payload = get_blog_seo_meta_overview(db, blog)
    verification = _verify_target_meta(
        target_url=payload["verification_target_url"],
        expected=payload["expected_meta_description"],
        warnings=list(payload["warnings"]),
    )

    statuses = (
        verification["head_meta_description_status"],
        verification["og_description_status"],
        verification["twitter_description_status"],
    )
    if all(status.status == "ok" for status in statuses):
        verified_at = datetime.now(timezone.utc)
        mark_blog_seo_meta_verified(db, blog, verified_at=verified_at)
        payload["seo_theme_patch_verified"] = True
        payload["seo_theme_patch_verified_at"] = verified_at
    else:
        clear_blog_seo_meta_verified(db, blog)
        payload["seo_theme_patch_verified"] = False
        payload["seo_theme_patch_verified_at"] = None

    payload.update(verification)
    return payload


def get_article_seo_meta_overview(article: Article) -> dict:
    post = article.blogger_post
    warnings: list[str] = []
    target_url = None
    if not post or post.post_status != PostStatus.PUBLISHED:
        warnings.append("This article is not publicly published yet, so live meta verification is not available.")
    else:
        target_url = post.published_url

    return {
        "article_id": article.id,
        "blog_id": article.blog_id,
        "article_title": article.title,
        **_build_verification_payload(
            expected=article.meta_description,
            target_url=target_url,
            warnings=warnings,
        ),
    }


def verify_article_seo_meta(article: Article) -> dict:
    payload = get_article_seo_meta_overview(article)
    verification = _verify_target_meta(
        target_url=payload["verification_target_url"],
        expected=payload["expected_meta_description"],
        warnings=list(payload["warnings"]),
    )
    payload.update(verification)
    return payload
