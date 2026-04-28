from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOL_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\Rool\30-cloudflare")
AUDIT_ROOT = ROOL_ROOT / "10-live-health-audit"
RECOVERY_ROOT = ROOL_ROOT / "13-codex-imagegen-recovery"
BACKUP_LOG_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\backup\작업log")
TASK_LABEL = "클라우드 이미지 정리"
EXCLUDED_CATEGORY = "미스테리아-스토리"

CATEGORY_LEAF_MAP = {
    "개발과-프로그래밍": "gaebalgwa-peurogeuraeming",
    "나스닥의-흐름": "naseudagyi-heureum",
    "동그리의-생각": "donggeuriyi-saenggag",
    "문화와-공간": "munhwawa-gonggan",
    "미스테리아-스토리": "miseuteria-seutori",
    "삶을-유용하게": "salmeul-yuyonghage",
    "삶의-기름칠": "salmyi-gireumcil",
    "여행과-기록": "yeohaenggwa-girog",
    "일상과-메모": "ilsanggwa-memo",
    "주식의-흐름": "jusigyi-heureum",
    "축제와-현장": "cugjewa-hyeonjang",
    "크립토의-흐름": "keuribtoyi-heureum",
}

CATEGORY_IMAGE_BRIEFS = {
    "개발과-프로그래밍": (
        "AI 개발 도구, IDE/CLI 워크플로, 운영 대시보드, 아키텍처 보드가 보이는 "
        "현대적인 3x3 기술 문서형 hero collage"
    ),
    "나스닥의-흐름": "미국 기술주, 반도체, 실적, 리스크 지표가 보이는 금융 리포트형 3x3 hero collage",
    "동그리의-생각": "다크 라이브러리, 생각 노트, 사회 장면, 창가 책상이 어우러진 사색형 3x3 hero collage",
    "문화와-공간": (
        "전시/문화 공간의 장소성, 운영 기간 또는 상설 맥락, 입구와 관람 동선, 작품 배치, "
        "관람자 흐름, 공간 조명이 보이는 문화 공간 가이드형 3x3 hero collage"
    ),
    "삶을-유용하게": "생활 개선, 도구, 체크리스트, 실용 루틴이 보이는 명확한 생활 정보형 3x3 hero collage",
    "삶의-기름칠": "정책 서류, 신청 화면, 상담 장면, 자격 조건 카드가 보이는 공공지원 안내형 3x3 hero collage",
    "여행과-기록": "국내 장소, 동선, 현장 기록, 계절감이 보이는 실제 여행 기록형 3x3 hero collage",
    "일상과-메모": "노트, 책상, 창가 빛, 루틴 체크리스트가 보이는 조용한 일상 기록형 3x3 hero collage",
    "주식의-흐름": "시장 차트, 기업 이벤트, 리스크 타이밍, 투자 메모가 보이는 금융 분석형 3x3 hero collage",
    "축제와-현장": (
        "축제/행사의 개최 장소, 기간과 시간대 분위기, 방문 동선, 대기줄, 부스/무대, "
        "교통/입구 정보가 보이는 현장 가이드형 3x3 hero collage"
    ),
    "크립토의-흐름": "블록체인 네트워크, 온체인 지표, 거래 심리, 규제 이슈가 보이는 사이버 분석형 3x3 hero collage",
}

RECOVERY_SUBDIRS = [
    "01-input-audit",
    "02-generation-queue",
    "03-generated-png",
    "04-webp",
    "05-r2-upload",
    "06-live-apply",
    "07-verify",
    "08-completed",
    "09-skipped",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def today_dir() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def ensure_dirs() -> None:
    for subdir in RECOVERY_SUBDIRS:
        (RECOVERY_ROOT / subdir).mkdir(parents=True, exist_ok=True)
    (BACKUP_LOG_ROOT / today_dir() / TASK_LABEL).mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def reason_set(row: dict[str, str]) -> set[str]:
    return {item.strip() for item in str(row.get("reasons") or "").split(";") if item.strip()}


def category_policy_path(category_slug: str) -> Path:
    leaf = CATEGORY_LEAF_MAP.get(category_slug, category_slug)
    return ROOL_ROOT / "categories" / leaf / "image-prompt-policy.md"


def r2_key_for(row: dict[str, str]) -> str:
    category = row.get("category_slug") or ""
    leaf = CATEGORY_LEAF_MAP.get(category, category)
    slug = row.get("slug") or ""
    published_hint = "2026/04"
    thumbnail = row.get("thumbnail_url") or ""
    marker = "/dongri-archive/"
    if marker in thumbnail:
        tail = thumbnail.split(marker, 1)[1].split("/")
        if len(tail) >= 4 and tail[1].isdigit() and tail[2].isdigit():
            published_hint = f"{tail[1]}/{tail[2]}"
    return f"assets/media/cloudflare/dongri-archive/{leaf}/{published_hint}/{slug}/{slug}.webp"


def public_url_for(row: dict[str, str]) -> str:
    return f"https://api.dongriarchive.com/{r2_key_for(row)}"


def local_png_for(row: dict[str, str]) -> str:
    return str(RECOVERY_ROOT / "03-generated-png" / (row.get("category_slug") or "unknown") / f"{row.get('slug')}.png")


def local_webp_for(row: dict[str, str]) -> str:
    return str(RECOVERY_ROOT / "04-webp" / (row.get("category_slug") or "unknown") / f"{row.get('slug')}.webp")


def build_image_prompt(row: dict[str, str]) -> str:
    category = row.get("category_slug") or ""
    title = row.get("title") or row.get("slug") or ""
    style_brief = CATEGORY_IMAGE_BRIEFS.get(category, "글의 핵심 주제가 한눈에 읽히는 3x3 hero collage")
    return "\n".join(
        [
            "Use case: editorial blog hero image",
            "Asset type: Cloudflare blog canonical hero image",
            f"Post title: {title}",
            f"Category: {category}",
            f"Visual policy: {style_brief}",
            "Composition: one single Web hero image, 16:9, polished editorial style, 3x3 collage feeling in one image.",
            "Requirements: no text overlays, no logos, no watermarks, no UI brand marks, no unrelated category imagery.",
            "Mood: premium Korean editorial archive, clear subject hierarchy, high readability at thumbnail size.",
            "Output intent: PNG backup first, then WebP conversion and R2 upload by BloggerGent.",
        ]
    )


def build_outputs(*, stamp: str, execute: bool) -> dict[str, Any]:
    ensure_dirs()
    audit_path = AUDIT_ROOT / "cloudflare-live-integrity-audit-latest.csv"
    audit_rows = read_csv(audit_path)
    active_rows = [row for row in audit_rows if row.get("category_slug") != EXCLUDED_CATEGORY]

    image_targets: list[dict[str, Any]] = []
    content_review: list[dict[str, Any]] = []
    legacy_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in active_rows:
        reasons = reason_set(row)
        if not reasons:
            continue
        base = {
            "remote_post_id": row.get("remote_post_id", ""),
            "category_slug": row.get("category_slug", ""),
            "slug": row.get("slug", ""),
            "title": row.get("title", ""),
            "post_url": row.get("target_public_url") or row.get("public_url", ""),
            "thumbnail_url": row.get("thumbnail_url", ""),
            "reasons": ";".join(sorted(reasons)),
        }
        if {"fallback_placeholder", "actual_broken_image"} & reasons:
            image_targets.append(
                {
                    **base,
                    "imagegen_prompt": build_image_prompt(row),
                    "policy_path": str(category_policy_path(row.get("category_slug", ""))),
                    "png_path": local_png_for(row),
                    "webp_path": local_webp_for(row),
                    "r2_key": r2_key_for(row),
                    "public_url": public_url_for(row),
                    "generation_status": "queued",
                }
            )
        if "title_identity_mismatch" in reasons:
            content_review.append({**base, "review_type": "title_identity_mismatch", "review_status": "queued"})
        if "legacy_media_posts_url" in reasons:
            legacy_candidates.append({**base, "migration_type": "canonical_image_migration_candidate", "migration_status": "queued"})
        if reasons and not ({"fallback_placeholder", "actual_broken_image", "title_identity_mismatch", "legacy_media_posts_url"} & reasons):
            skipped.append({**base, "skip_reason": "no_supported_action_for_reason"})

    backup_dir = BACKUP_LOG_ROOT / today_dir() / TASK_LABEL
    input_dir = RECOVERY_ROOT / "01-input-audit"
    queue_dir = RECOVERY_ROOT / "02-generation-queue"
    skipped_dir = RECOVERY_ROOT / "09-skipped"

    copied_files: list[dict[str, str]] = []
    for src in [
        audit_path,
        AUDIT_ROOT / "fallback_placeholder_latest.csv",
        AUDIT_ROOT / "actual_broken_image_latest.csv",
        AUDIT_ROOT / "title_mismatch_latest.csv",
        AUDIT_ROOT / "legacy_image_url_latest.csv",
    ]:
        dst = input_dir / src.name
        if copy_if_exists(src, dst):
            copied_files.append({"source": str(src), "copied_to": str(dst)})
            copy_if_exists(src, backup_dir / "input-audit" / src.name)

    old_register = ROOL_ROOT / "09-refactoring" / "fallback-placeholder-register" / "fallback-placeholder-115-register.csv"
    old_rows = read_csv(old_register)
    active_ids = {row["remote_post_id"] for row in image_targets if row.get("remote_post_id")}
    stale_old_rows = [{**row, "active_status": "stale_not_in_latest_non_mysteria_image_queue"} for row in old_rows if row.get("remote_post_id") not in active_ids]
    still_active_old_rows = [{**row, "active_status": "active_in_latest_non_mysteria_image_queue"} for row in old_rows if row.get("remote_post_id") in active_ids]

    image_fields = [
        "remote_post_id",
        "category_slug",
        "slug",
        "title",
        "post_url",
        "thumbnail_url",
        "reasons",
        "imagegen_prompt",
        "policy_path",
        "png_path",
        "webp_path",
        "r2_key",
        "public_url",
        "generation_status",
    ]
    review_fields = ["remote_post_id", "category_slug", "slug", "title", "post_url", "thumbnail_url", "reasons", "review_type", "review_status"]
    legacy_fields = ["remote_post_id", "category_slug", "slug", "title", "post_url", "thumbnail_url", "reasons", "migration_type", "migration_status"]

    write_csv(queue_dir / "codex-imagegen-queue.csv", image_targets, image_fields)
    write_csv(queue_dir / f"codex-imagegen-queue-{stamp}.csv", image_targets, image_fields)
    write_csv(queue_dir / "content-review-queue.csv", content_review, review_fields)
    write_csv(queue_dir / "legacy-image-migration-candidates.csv", legacy_candidates, legacy_fields)
    write_csv(skipped_dir / "unsupported-reason-skipped.csv", skipped, ["remote_post_id", "category_slug", "slug", "title", "post_url", "thumbnail_url", "reasons", "skip_reason"])

    if old_rows:
        fieldnames = list(old_rows[0].keys()) + ["active_status"]
        write_csv(input_dir / "fallback-placeholder-115-stale-vs-active.csv", stale_old_rows + still_active_old_rows, fieldnames)
        copy_if_exists(old_register, backup_dir / "stale-registers" / old_register.name)
        write_csv(backup_dir / "stale-registers" / "fallback-placeholder-115-stale-vs-active.csv", stale_old_rows + still_active_old_rows, fieldnames)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "mode": "execute" if execute else "dry_run",
        "source_audit": str(audit_path),
        "excluded_category": EXCLUDED_CATEGORY,
        "published_rows_in_audit": len(audit_rows),
        "non_mysteria_rows": len(active_rows),
        "image_generation_targets": len(image_targets),
        "content_review_targets": len(content_review),
        "legacy_image_migration_candidates": len(legacy_candidates),
        "unsupported_skipped": len(skipped),
        "old_fallback_register_rows": len(old_rows),
        "old_fallback_register_stale_rows": len(stale_old_rows),
        "old_fallback_register_still_active_rows": len(still_active_old_rows),
        "recovery_root": str(RECOVERY_ROOT),
        "backup_log_root": str(backup_dir),
        "copied_files": copied_files,
    }
    write_json(RECOVERY_ROOT / "01-input-audit" / "codex-imagegen-recovery-summary.json", summary)
    write_json(RECOVERY_ROOT / "01-input-audit" / f"codex-imagegen-recovery-summary-{stamp}.json", summary)
    write_json(backup_dir / "codex-imagegen-recovery-summary.json", summary)

    command_log = backup_dir / "commands.txt"
    command_log.write_text(
        "\n".join(
            [
                f"timestamp={datetime.now().isoformat()}",
                "task=Cloudflare Codex ImageGen recovery queue preparation",
                "command=python scripts\\cloudflare\\prepare_codex_imagegen_recovery.py --mode execute",
                f"source_audit={audit_path}",
                f"recovery_root={RECOVERY_ROOT}",
                f"backup_log_root={backup_dir}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def write_rule_docs() -> None:
    root_readme = RECOVERY_ROOT / "README.md"
    root_readme.write_text(
        """# Cloudflare Codex ImageGen Recovery

이 작업공간은 Cloudflare 실게시글 이미지 복구를 Codex `image_gen` 기준으로 관리한다.

## 고정 규칙
- Antigravity는 사용하지 않는다.
- `미스테리아-스토리`는 이번 복구 범위에서 제외한다.
- 한 게시글당 대표 이미지 1장만 생성한다.
- PNG 원본은 `03-generated-png/<category>/<slug>.png`에 둔다.
- WebP 변환본은 `04-webp/<category>/<slug>.webp`에 둔다.
- R2 key는 `assets/media/cloudflare/dongri-archive/<category-leaf>/YYYY/MM/<slug>/<slug>.webp`만 허용한다.
- 공개 URL은 `https://api.dongriarchive.com/assets/media/cloudflare/dongri-archive/...`만 허용한다.
- live 반영은 `HEAD/GET 200`과 `Content-Type image/*` 확인 후에만 한다.

## 실행 순서
1. `02-generation-queue/codex-imagegen-queue.csv`를 확인한다.
2. 각 row의 `imagegen_prompt`를 Codex 내장 `image_gen`에 전달한다.
3. 생성 PNG를 지정된 `png_path`에 저장한다.
4. PNG를 WebP로 변환한다.
5. R2 업로드 후 공개 URL 검증을 수행한다.
6. 검증 성공 건만 `coverImage`와 DB `thumbnail_url`을 교체한다.
7. 해결 완료 시 관련 queue/report를 `D:\\Donggri_Runtime\\BloggerGent\\backup\\작업log\\YYYY-MM-DD\\클라우드 이미지 정리`에 보존한다.
""",
        encoding="utf-8",
    )

    workflow = RECOVERY_ROOT / "02-generation-queue" / "codex-imagegen-operator-rule.md"
    workflow.write_text(
        """# Codex ImageGen Operator Rule

## 입력
- `codex-imagegen-queue.csv`
- 필수 컬럼: `remote_post_id`, `category_slug`, `slug`, `title`, `imagegen_prompt`, `png_path`, `webp_path`, `r2_key`, `public_url`

## 생성
- 내장 `image_gen` 스킬을 사용한다.
- 별도 CLI fallback은 쓰지 않는다.
- 이미지에는 텍스트, 로고, 워터마크를 넣지 않는다.
- 카테고리 정책은 `policy_path`를 기준으로 한다.

## 저장
- 생성 결과는 반드시 `png_path`에 복사한다.
- 프로젝트/게시글에 참조되는 이미지를 Codex 기본 생성 폴더에만 남기지 않는다.

## 반영
- WebP 변환과 R2 업로드 후 `public_url`이 이미지로 열릴 때만 live 반영한다.
- 실패하면 기존 게시글 URL을 유지하고 `09-skipped`에 사유를 남긴다.
""",
        encoding="utf-8",
    )

    backup_rule = BACKUP_LOG_ROOT / "README.md"
    if not backup_rule.exists():
        backup_rule.parent.mkdir(parents=True, exist_ok=True)
        backup_rule.write_text(
            """# BloggerGent 작업log

작업 완료 또는 정리된 실행 산출물은 날짜와 업무명 기준으로 보존한다.

폴더 규칙:

```text
D:\\Donggri_Runtime\\BloggerGent\\backup\\작업log\\YYYY-MM-DD\\한글 3단어 업무명
```

Cloudflare 이미지 정리 업무명은 `클라우드 이미지 정리`로 고정한다.
""",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Cloudflare Codex image_gen recovery queues.")
    parser.add_argument("--mode", choices=["dry_run", "execute"], default="dry_run")
    args = parser.parse_args()
    stamp = now_stamp()
    ensure_dirs()
    if args.mode == "execute":
        write_rule_docs()
    summary = build_outputs(stamp=stamp, execute=args.mode == "execute")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
