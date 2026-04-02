from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from package_common import (
    PATCH_PACKAGE_ROOT,
    SessionLocal,
    extract_html_outline,
    extract_html_paragraphs,
    extract_prompt_sections,
    fetch_synced_blogger_posts,
    normalize_space,
    resolve_blog_by_profile_key,
    safe_filename,
    write_csv_utf8,
    write_json,
    write_text_utf8,
)


PROFILE_BY_MODE = {
    "travel": ("korea_travel", "travel", Path("prompts/travel_article_generation.md")),
    "midnight": ("world_mystery", "midnight-archives", Path("prompts/mystery_article_generation.md")),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Blogger patch-draft packages without any live deployment.")
    parser.add_argument("--mode", choices=("travel", "midnight", "all"), default="all")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--limit", type=int, default=0, help="Optional per-channel limit for preview runs")
    return parser.parse_args()


def select_modes(mode: str) -> list[str]:
    if mode == "all":
        return ["travel", "midnight"]
    return [mode]


def build_focus_areas(channel_key: str) -> list[str]:
    if channel_key == "travel":
        return [
            "일정 또는 시즌성 변동 가능 정보 확인",
            "운영시간, 예약, 입장 방식 관련 보강 포인트 점검",
            "교통, 동선, 장소 맥락 관련 최신 보강 문단 후보 추출",
            "FAQ에 재확인 포인트만 추가하고 기존 골격 유지",
        ]
    return [
        "확인된 사실과 해석/주장을 분리할 보강 포인트 점검",
        "타임라인, 기록, 출처 표현의 정확도 보강 후보 추출",
        "사건 이후 달라진 정보나 반박된 주장 여부 검토",
        "FAQ에 사실 기반 보충 문답만 추가하고 기존 골격 유지",
    ]


def build_patch_payload(
    *,
    channel_key: str,
    source_url: str,
    title: str,
    published_at: str,
    labels: list[str],
    content_html: str,
    prompt_reference: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "source_url": source_url,
        "title": title,
        "published_at": published_at,
        "labels": labels,
        "preservation_contract": {
            "preserve_title": True,
            "preserve_images": True,
            "preserve_structure": True,
            "preserve_related_links": True,
            "allow_full_rewrite": False,
        },
        "focus_areas": build_focus_areas(channel_key),
        "prompt_reference": prompt_reference,
        "section_outline": extract_html_outline(content_html),
        "candidate_paragraphs": extract_html_paragraphs(content_html, limit=10),
        "manual_instruction": (
            "기존 본문 전체를 갈아엎지 말고, 필요한 문단만 덧붙이거나 교체한다. "
            "제목, 이미지, 큰 섹션 구조는 유지한다."
        ),
    }


def run() -> int:
    args = parse_args()
    output_root = PATCH_PACKAGE_ROOT / f"{args.date}-blogger-patch"
    output_root.mkdir(parents=True, exist_ok=True)

    package_metadata = {
        "kind": "blogger-patch-draft",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": args.mode,
        "channels": [],
    }

    with SessionLocal() as db:
        for mode in select_modes(args.mode):
            profile_key, channel_name, prompt_path = PROFILE_BY_MODE[mode]
            prompt_reference = extract_prompt_sections(prompt_path, ["Fact Rules", "Category Strategy"])
            blog = resolve_blog_by_profile_key(db, profile_key)
            posts = fetch_synced_blogger_posts(db, blog.id)
            if args.limit > 0:
                posts = posts[: args.limit]

            channel_root = output_root / channel_name
            snapshots_root = channel_root / "snapshots"
            patches_root = channel_root / "patches"
            channel_root.mkdir(parents=True, exist_ok=True)
            snapshots_root.mkdir(parents=True, exist_ok=True)
            patches_root.mkdir(parents=True, exist_ok=True)

            manifest_rows: list[dict[str, Any]] = []
            manifest_json: list[dict[str, Any]] = []

            for post in posts:
                source_url = normalize_space(post.url)
                title = normalize_space(post.title)
                published_at = post.published_at.isoformat() if post.published_at else ""
                labels = [normalize_space(str(item)) for item in (post.labels or []) if normalize_space(str(item))]
                content_html = post.content_html or ""

                file_stem = safe_filename(post.remote_post_id or title, fallback=f"{mode}-{post.id}")
                snapshot_path = snapshots_root / f"{file_stem}.html"
                patch_path = patches_root / f"{file_stem}.json"
                write_text_utf8(snapshot_path, content_html)
                patch_payload = build_patch_payload(
                    channel_key=mode,
                    source_url=source_url,
                    title=title,
                    published_at=published_at,
                    labels=labels,
                    content_html=content_html,
                    prompt_reference=prompt_reference,
                )
                write_json(patch_path, patch_payload)

                row = {
                    "source_url": source_url,
                    "remote_post_id": post.remote_post_id,
                    "title": title,
                    "published_at": published_at,
                    "labels": "|".join(labels),
                    "action": "patch_draft",
                    "notes": "Live apply disabled. Review verified updates and edit only affected paragraphs.",
                    "snapshot_html_path": str(snapshot_path),
                    "patch_json_path": str(patch_path),
                }
                manifest_rows.append(row)
                manifest_json.append(row)

            write_json(channel_root / "manifest.json", manifest_json)
            write_csv_utf8(
                channel_root / "manifest.csv",
                manifest_rows,
                [
                    "source_url",
                    "remote_post_id",
                    "title",
                    "published_at",
                    "labels",
                    "action",
                    "notes",
                    "snapshot_html_path",
                    "patch_json_path",
                ],
            )
            package_metadata["channels"].append(
                {
                    "channel": channel_name,
                    "profile_key": profile_key,
                    "post_count": len(manifest_rows),
                    "prompt_reference_path": str(prompt_path),
                }
            )

    write_json(output_root / "package-metadata.json", package_metadata)
    print(json.dumps({"package_root": str(output_root), "channels": package_metadata["channels"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
