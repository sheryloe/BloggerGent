# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPT_DIR.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"

from sqlalchemy import text as sql_text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from package_common import CloudflareIntegrationClient, normalize_space, resolve_cloudflare_category_id  # noqa: E402
from repair_mystery_garbage_data import (  # noqa: E402
    MYSTERIA_CATEGORY_NAME,
    MYSTERIA_CATEGORY_SLUG,
    PATTERN_ID,
    PATTERN_VERSION,
    audit_cloudflare_url,
    build_publish_description,
)


TITLE_MAP = {
    "miseuteria-seutori-sodder-children-christmas-fire-record": "소더 아이들 실종 사건: 크리스마스 화재 뒤 남은 다섯 개의 빈자리",
    "miseuteria-seutori-dyatlov-pass-tent-and-footprints-record": "디아틀로프 패스 사건: 눈 위의 발자국과 찢어진 텐트의 기록",
    "miseuteria-seutori-roanoke-colony-croatoan-record": "로어노크 식민지 실종: CROATOAN 한 단어가 남긴 식민지의 공백",
    "miseuteria-seutori-oak-island-money-pit-record": "오크 아일랜드 머니 핏: 보물보다 오래 살아남은 발굴 기록의 함정",
    "miseuteria-seutori-flor-de-la-mar-treasure-ship-record": "플로르 드 라 마르 보물선: 말라카 해협에 잠긴 제국의 화물 기록",
    "miseuteria-seutori-mary-celeste-ghost-ship-record": "메리 셀레스트 기록 재검토: 빈 배가 남긴 단서와 과장된 전설",
    "miseuteria-seutori-uss-cyclops-bermuda-route-record": "USS 사이클롭스 실종: 거대한 석탄 운반선이 남긴 마지막 항로",
    "miseuteria-seutori-wow-signal-72-second-radio-record": "와우! 시그널: 72초 전파 기록이 외계 신호가 되기까지",
    "miseuteria-seutori-zodiac-killer-cipher-letter-record": "조디악 킬러 기록 재검토: 암호와 편지가 수사를 흔든 방식",
}


def post_url(slug: str) -> str:
    return f"https://dongriarchive.com/ko/post/{slug}"


def main() -> int:
    rows = []
    with SessionLocal() as db:
        values = get_settings_map(db)
        cf = CloudflareIntegrationClient(
            base_url=str(values.get("cloudflare_blog_api_base_url") or ""),
            token=str(values.get("cloudflare_blog_m2m_token") or ""),
        )
        category_id = resolve_cloudflare_category_id(MYSTERIA_CATEGORY_SLUG, cf.list_categories()) or resolve_cloudflare_category_id(
            MYSTERIA_CATEGORY_NAME,
            cf.list_categories(),
        )
        if not category_id:
            raise RuntimeError("mysteria_category_id_not_found")
        posts = {normalize_space(str(post.get("slug") or "")): post for post in cf.list_posts()}
        for slug, title in TITLE_MAP.items():
            post = posts.get(slug)
            if not post:
                rows.append({"slug": slug, "result": "missing"})
                continue
            post_id = normalize_space(str(post.get("id") or post.get("remote_id") or ""))
            detail = cf.get_post(post_id)
            content = str(detail.get("content") or "")
            description = build_publish_description(title, content)
            cover = normalize_space(str(detail.get("coverImage") or post.get("coverImage") or ""))
            payload = {
                "title": title,
                "slug": slug,
                "content": content,
                "description": description,
                "excerpt": description,
                "seoTitle": title,
                "seoDescription": description,
                "metaDescription": description,
                "tagNames": [MYSTERIA_CATEGORY_NAME, "미스터리", "사건기록"],
                "categoryId": str(category_id),
                "status": "published",
                "coverImage": cover,
                "coverAlt": title,
                "article_pattern_id": normalize_space(str(detail.get("article_pattern_id") or PATTERN_ID)),
                "article_pattern_version": int(detail.get("article_pattern_version") or PATTERN_VERSION),
                "articlePatternId": normalize_space(str(detail.get("articlePatternId") or detail.get("article_pattern_id") or PATTERN_ID)),
                "articlePatternVersion": int(detail.get("articlePatternVersion") or detail.get("article_pattern_version") or PATTERN_VERSION),
            }
            cf.update_post(post_id, payload)
            db.execute(
                sql_text(
                    """
                    UPDATE synced_cloudflare_posts
                    SET
                        title = :title,
                        category_name = :category_name,
                        category_slug = :category_slug,
                        canonical_category_name = :category_name,
                        canonical_category_slug = :category_slug,
                        synced_at = now(),
                        updated_at = now()
                    WHERE slug = :slug
                    """
                ),
                {
                    "slug": slug,
                    "title": title,
                    "category_name": MYSTERIA_CATEGORY_NAME,
                    "category_slug": MYSTERIA_CATEGORY_SLUG,
                },
            )
            db.commit()
            audit = audit_cloudflare_url(post_url(slug))
            rows.append(
                {
                    "slug": slug,
                    "title": title,
                    "result": "updated",
                    "status": audit.status,
                    "plain_text_length": audit.plain_text_length,
                    "image_count": audit.image_count,
                    "markdown_exposed": audit.markdown_exposed,
                    "raw_html_exposed": audit.raw_html_exposed,
                }
            )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all(row.get("result") == "updated" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
