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
<b:if cond='data:blog.pageType == "item"'>
  <meta expr:content='data:post.snippet' name='description'/>
  <meta expr:content='data:post.snippet' property='og:description'/>
  <meta expr:content='data:post.snippet' name='twitter:description'/>
<b:else/>
  <meta expr:content='data:blog.metaDescription' name='description'/>
  <meta expr:content='data:blog.metaDescription' property='og:description'/>
  <meta expr:content='data:blog.metaDescription' name='twitter:description'/>
</b:if>"""

PATCH_STEPS = [
    "Blogger 관리자에서 설정 > 메타 태그 > 검색 설명 사용을 먼저 켭니다.",
    "Blogger 관리자에서 테마 > HTML 편집으로 이동합니다.",
    "<head> 안에 기존 description / og:description / twitter:description 메타 태그가 있다면 중복되지 않게 정리합니다.",
    "아래 Bloggent SEO meta patch 스니펫을 <head> 안에 붙여넣고 저장합니다.",
    "이 스니펫은 글 페이지에서는 data:post.snippet, 홈과 목록 페이지에서는 data:blog.metaDescription을 사용합니다.",
    "저장 후 공개 글 URL로 SEO 메타 검증을 실행해 head meta description, og:description, twitter:description이 정상인지 확인합니다.",
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
            message="앱에 저장된 비교용 검색 설명이 없어 검증 기준을 만들 수 없습니다.",
        )
    if not normalized_actual:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="warning",
            actual=actual,
            expected=expected,
            message="공개 페이지 head에서 이 메타 태그를 찾지 못했습니다.",
        )
    if normalized_actual == normalized_expected:
        return SeoMetaStatusRead(
            key=key,
            label=label,
            status="ok",
            actual=actual,
            expected=expected,
            message="기대값과 실제 공개 페이지 메타가 일치합니다.",
        )
    return SeoMetaStatusRead(
        key=key,
        label=label,
        status="warning",
        actual=actual,
        expected=expected,
        message="공개 페이지 메타 값이 앱에 저장된 검색 설명과 다릅니다.",
    )


def _empty_status(expected: str | None) -> SeoMetaStatusRead:
    return SeoMetaStatusRead(
        key="unverified",
        label="검증 전",
        status="idle",
        actual=None,
        expected=expected,
        message="아직 공개 페이지 메타 검증을 실행하지 않았습니다.",
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
        payload["warnings"] = [*warnings, f"공개 페이지를 불러오지 못했습니다. {exc}"]
        return payload

    head_html = _extract_head(response.text)
    payload["head_meta_description_status"] = _build_status(
        key="head_meta_description",
        label="head meta description",
        actual=_extract_meta(head_html, name="description"),
        expected=expected,
    )
    payload["og_description_status"] = _build_status(
        key="og_description",
        label="og:description",
        actual=_extract_meta(head_html, prop="og:description"),
        expected=expected,
    )
    payload["twitter_description_status"] = _build_status(
        key="twitter_description",
        label="twitter:description",
        actual=_extract_meta(head_html, name="twitter:description"),
        expected=expected,
    )
    return payload


def _latest_published_pair(db: Session, blog_id: int) -> tuple[Article | None, BloggerPost | None]:
    row = db.execute(
        select(Article, BloggerPost)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id == blog_id, BloggerPost.is_draft.is_(False))
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
            "Blogger API만으로는 글별 검색 설명 메타를 안정적으로 head에 넣기 어렵습니다. "
            "설정 화면의 Bloggent SEO meta patch 스니펫을 테마에 수동 적용해야 합니다."
        )
    if not verification_target_url:
        warnings.append("아직 공개된 Blogger 글이 없어 실제 공개 페이지 메타를 검증할 수 없습니다.")

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
        if not blog.seo_theme_patch_installed:
            verification["warnings"].append("설정 화면에서 Blogger SEO 메타 패치 적용 여부를 아직 체크하지 않았습니다.")

    payload.update(verification)
    return payload


def get_article_seo_meta_overview(article: Article) -> dict:
    post = article.blogger_post
    warnings: list[str] = []
    target_url = None
    if not post or post.is_draft:
        warnings.append("이 글은 아직 공개 게시되지 않아 실제 공개 페이지 메타를 검증할 수 없습니다.")
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
