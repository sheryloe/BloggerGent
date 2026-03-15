from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, Blog, BloggerPost
from app.schemas.api import SeoMetaStatusRead
from app.services.blog_service import clear_blog_seo_meta_verified, mark_blog_seo_meta_verified

PATCH_SNIPPET = """<!-- Bloggent SEO meta patch -->
<b:if cond='data:view.isSingleItem'>
  <meta expr:content='data:view.description.escaped' name='description'/>
  <meta expr:content='data:view.description.escaped' property='og:description'/>
  <meta expr:content='data:view.description.escaped' name='twitter:description'/>
<b:else/>
  <meta expr:content='data:blog.metaDescription' name='description'/>
  <meta expr:content='data:blog.metaDescription' property='og:description'/>
  <meta expr:content='data:blog.metaDescription' name='twitter:description'/>
</b:if>"""

PATCH_STEPS = [
    "Blogger API로는 테마 HTML을 직접 수정할 수 없으므로, 아래 스니펫은 Blogger 관리자 화면에서 수동으로 붙여넣어야 합니다.",
    "Blogger 관리 화면에서 테마 > HTML 편집으로 들어갑니다.",
    "<head> 영역의 기존 description / og:description / twitter:description 메타 태그 근처를 찾습니다.",
    "Bloggent SEO meta patch 스니펫을 <head> 안에 추가하고 저장합니다.",
    "이미 공개된 글 하나의 URL을 넣어 메타 검증을 실행합니다.",
    "head meta description, og:description, twitter:description이 글별 설명으로 일치하면 적용 완료입니다.",
]


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def _extract_head(html: str) -> str:
    match = re.search(r"<head\b[^>]*>(.*?)</head>", html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


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


def _build_status(*, key: str, label: str, actual: str | None, expected: str | None) -> SeoMetaStatusRead:
    normalized_actual = _normalize(actual)
    normalized_expected = _normalize(expected)

    if not normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="warning",
            actual=actual,
            expected=expected,
            message="앱에 저장된 검색 설명이 없어 비교할 수 없습니다.",
        )
    if not normalized_actual:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="warning",
            actual=actual,
            expected=expected,
            message="공개 페이지 head에서 값을 찾지 못했습니다.",
        )
    if normalized_actual == normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="ok",
            actual=actual,
            expected=expected,
            message="글별 검색 설명이 정상 반영되었습니다.",
        )
    return SeoMetaStatusRead(
        key=key,
        label=label,
        status="warning",
        actual=actual,
        expected=expected,
        message="공개 페이지 값이 앱에 저장된 검색 설명과 다릅니다.",
    )


def _latest_published_pair(db: Session, blog_id: int) -> tuple[Article | None, BloggerPost | None]:
    row = db.execute(
        select(Article, BloggerPost)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id == blog_id)
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
    warning = []
    if not blog.seo_theme_patch_installed:
        warning.append("Blogger API는 테마 HTML 수정 엔드포인트를 제공하지 않아, SEO 메타 패치는 Blogger 관리자 화면에서 수동으로 적용해야 합니다.")
    if not verification_target_url:
        warning.append("아직 공개되었거나 초안으로 저장된 Blogger 글이 없어 실제 head 메타를 검증할 수 없습니다.")

    empty_status = SeoMetaStatusRead(
        key="unverified",
        label="검증 전",
        status="idle",
        actual=None,
        expected=expected_meta_description,
        message="아직 공개 페이지 메타 검증을 실행하지 않았습니다.",
    )
    return {
        "blog_id": blog.id,
        "seo_theme_patch_installed": blog.seo_theme_patch_installed,
        "seo_theme_patch_verified": bool(blog.seo_theme_patch_verified_at),
        "seo_theme_patch_verified_at": blog.seo_theme_patch_verified_at,
        "verification_target_url": verification_target_url,
        "expected_meta_description": expected_meta_description,
        "patch_snippet": PATCH_SNIPPET,
        "patch_steps": PATCH_STEPS,
        "warnings": warning,
        "head_meta_description_status": empty_status,
        "og_description_status": empty_status,
        "twitter_description_status": empty_status,
    }


def verify_blog_seo_meta(db: Session, blog: Blog) -> dict:
    payload = get_blog_seo_meta_overview(db, blog)
    target_url = payload["verification_target_url"]
    expected = payload["expected_meta_description"]

    if not target_url:
        return payload

    warnings = list(payload["warnings"])
    try:
        response = httpx.get(target_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        warnings.append(f"공개 페이지를 불러오지 못했습니다. {exc}")
        payload["warnings"] = warnings
        return payload

    head_html = _extract_head(response.text)
    head_meta = _extract_meta(head_html, name="description")
    og_meta = _extract_meta(head_html, prop="og:description")
    twitter_meta = _extract_meta(head_html, name="twitter:description")

    head_status = _build_status(
        key="head_meta_description",
        label="head meta description",
        actual=head_meta,
        expected=expected,
    )
    og_status = _build_status(
        key="og_description",
        label="og:description",
        actual=og_meta,
        expected=expected,
    )
    twitter_status = _build_status(
        key="twitter_description",
        label="twitter:description",
        actual=twitter_meta,
        expected=expected,
    )

    if all(status.status == "ok" for status in (head_status, og_status, twitter_status)):
        verified_at = datetime.now(timezone.utc)
        mark_blog_seo_meta_verified(db, blog, verified_at=verified_at)
        payload["seo_theme_patch_verified"] = True
        payload["seo_theme_patch_verified_at"] = verified_at
    else:
        clear_blog_seo_meta_verified(db, blog)
        payload["seo_theme_patch_verified"] = False
        payload["seo_theme_patch_verified_at"] = None
        if not blog.seo_theme_patch_installed:
            warnings.append("앱 설정에서 Blogger SEO 테마 패치 적용 여부를 아직 체크하지 않았습니다.")

    payload["warnings"] = warnings
    payload["head_meta_description_status"] = head_status
    payload["og_description_status"] = og_status
    payload["twitter_description_status"] = twitter_status
    return payload
