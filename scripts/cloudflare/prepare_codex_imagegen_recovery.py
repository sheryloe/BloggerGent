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
    "개발과-프로그래밍": "Developer workflow hero with official docs, tool version, IDE/CLI, logs, and architecture board.",
    "나스닥의-흐름": "Nasdaq infographic board with AI, semiconductors, earnings, rates, and risk scenarios.",
    "동그리의-생각": "Reflective note hero with social scene, notebook, desk, window light, and closing question.",
    "문화와-공간": "Culture space image with venue, operating period, viewing route, artwork placement, and lighting.",
    "미스테리아-스토리": "Dark mystery archive hero with case file, clues, timeline, and old documents.",
    "삶을-유용하게": "Life utility hero with tool, app, routine, checklist, and preparation item.",
    "삶의-기름칠": "Public benefit guide hero with documents, consultation, application flow, and eligibility checklist.",
    "여행과-기록": "Travel record hero with place, route cue, visit time, season, and booking or cost cue.",
    "일상과-메모": "Quiet daily record hero with notebook, desk, window light, routine object, and emotion cue.",
    "주식의-흐름": "Stock market hero with reference date, sector, price zone, event schedule, and risk.",
    "축제와-현장": "Festival field guide image with venue, period, operating hours, queue, booth, and access route.",
    "크립토의-흐름": "Crypto analysis hero with protocol, price zone, on-chain signal, sentiment, and regulation risk.",
}

IMAGEGEN_POLICY_BY_LEAF = {
    "gaebalgwa-peurogeuraeming": {
        "layout_policy": "hero_only_developer_workflow",
        "roles": ("hero",),
        "style": "developer workflow board with official docs, version/runtime cues, IDE/CLI, logs, and architecture artifacts",
        "anchors": ("reference date", "tool/version", "language/runtime", "IDE/CLI", "official docs"),
    },
    "ilsanggwa-memo": {
        "layout_policy": "hero_only_daily_record",
        "roles": ("hero",),
        "style": "quiet daily record with notebook, desk, window light, routine object, and emotional cue",
        "anchors": ("scene", "time of day", "emotion", "routine", "small checklist"),
    },
    "yeohaenggwa-girog": {
        "layout_policy": "hero_only_place_route",
        "roles": ("hero",),
        "style": "place and route editorial image with real location mood, transit/walking cue, season/weather, and booking/cost hint",
        "anchors": ("place", "route cue", "visit time", "season/weather", "budget or booking"),
    },
    "salmeul-yuyonghage": {
        "layout_policy": "hero_only_life_utility",
        "roles": ("hero",),
        "style": "practical life utility scene with app/tool, daily routine, checklist, and preparation items",
        "anchors": ("target user", "tool/service", "cost/benefit", "preparation item", "caution point"),
    },
    "salmyi-gireumcil": {
        "layout_policy": "hero_only_public_benefit",
        "roles": ("hero",),
        "style": "public benefit guide scene with documents, consultation desk, eligibility checklist, and application flow; no government logos or readable fake text",
        "anchors": ("reference date", "agency", "application period", "eligibility", "benefit scope"),
    },
    "donggeuriyi-saenggag": {
        "layout_policy": "hero_only_reflective_context",
        "roles": ("hero",),
        "style": "reflective social note with dark library, observation scene, notebook, cultural context, and unresolved question",
        "anchors": ("social event", "personal question", "culture context", "observation scene", "closing question"),
    },
    "jusigyi-heureum": {
        "layout_policy": "hero_only_stock_market",
        "roles": ("hero",),
        "style": "stock market visual; 12-panel cartoon only for stock-cartoon-summary, otherwise financial report board",
        "anchors": ("reference date", "stock/sector", "price or index zone", "event schedule", "risk"),
    },
    "keuribtoyi-heureum": {
        "layout_policy": "hero_only_crypto_market",
        "roles": ("hero",),
        "style": "crypto visual; cyber 12-panel cartoon only for crypto-cartoon-summary, otherwise on-chain/protocol/regulatory analysis board",
        "anchors": ("reference date", "coin/protocol", "price zone", "on-chain signal", "regulatory risk"),
    },
    "naseudagyi-heureum": {
        "layout_policy": "hero_only_nasdaq_infographic",
        "roles": ("hero",),
        "style": "Nasdaq infographic or market analysis board with AI, semiconductors, earnings, macro rates, and risk scenarios; no cartoon style",
        "anchors": ("reference date", "company/sector", "earnings/guidance", "AI or semiconductor context", "risk scenario"),
    },
    "cugjewa-hyeonjang": {
        "layout_policy": "hero_plus_two_inline_event",
        "roles": ("hero", "inline_1", "inline_2"),
        "style": "festival/event field guide; hero for atmosphere, inline_1 for access/queue/route, inline_2 for time/risk/booth-stage context",
        "anchors": ("official site", "venue", "event period", "operating hours", "recommended visit time", "access route", "field risk"),
    },
    "munhwawa-gonggan": {
        "layout_policy": "hero_plus_two_inline_culture",
        "roles": ("hero", "inline_1", "inline_2"),
        "style": "culture/space guide; hero for venue atmosphere, inline_1 for viewing/access route, inline_2 for artwork or space highlight",
        "anchors": ("official site", "venue", "period/permanent status", "operating hours", "reservation/admission", "viewing route", "space risk"),
    },
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


def category_leaf_for(row_or_category: dict[str, str] | str) -> str:
    category = row_or_category if isinstance(row_or_category, str) else row_or_category.get("category_slug") or ""
    return CATEGORY_LEAF_MAP.get(str(category), str(category))


def policy_for(row_or_category: dict[str, str] | str) -> dict[str, Any]:
    leaf = category_leaf_for(row_or_category)
    fallback_category = str(row_or_category) if isinstance(row_or_category, str) else str(row_or_category.get("category_slug") or "")
    return dict(
        IMAGEGEN_POLICY_BY_LEAF.get(leaf)
        or {
            "layout_policy": "hero_only_generic",
            "roles": ("hero",),
            "style": CATEGORY_IMAGE_BRIEFS.get(fallback_category, "category-specific editorial hero image"),
            "anchors": ("topic", "category", "reader task"),
        }
    )


def roles_for(row_or_category: dict[str, str] | str) -> tuple[str, ...]:
    return tuple(str(role) for role in policy_for(row_or_category).get("roles", ("hero",)))


def slot_index_for(image_role: str) -> int:
    if image_role == "hero":
        return 0
    try:
        return int(image_role.rsplit("_", 1)[-1])
    except (IndexError, ValueError):
        return 0


def r2_key_for(row: dict[str, str], *, image_role: str = "hero") -> str:
    leaf = category_leaf_for(row)
    slug = row.get("slug") or ""
    published_hint = "2026/04"
    thumbnail = row.get("thumbnail_url") or ""
    marker = "/dongri-archive/"
    if marker in thumbnail:
        tail = thumbnail.split(marker, 1)[1].split("/")
        if len(tail) >= 4 and tail[1].isdigit() and tail[2].isdigit():
            published_hint = f"{tail[1]}/{tail[2]}"
    filename = f"{slug}.webp" if image_role == "hero" else f"{slug}-{image_role.replace('_', '-')}.webp"
    return f"assets/media/cloudflare/dongri-archive/{leaf}/{published_hint}/{slug}/{filename}"


def public_url_for(row: dict[str, str], *, image_role: str = "hero") -> str:
    return f"https://api.dongriarchive.com/{r2_key_for(row, image_role=image_role)}"


def local_png_for(row: dict[str, str], *, image_role: str = "hero") -> str:
    suffix = "" if image_role == "hero" else f"-{image_role.replace('_', '-')}"
    return str(RECOVERY_ROOT / "03-generated-png" / (row.get("category_slug") or "unknown") / image_role / f"{row.get('slug')}{suffix}.png")


def local_webp_for(row: dict[str, str], *, image_role: str = "hero") -> str:
    suffix = "" if image_role == "hero" else f"-{image_role.replace('_', '-')}"
    return str(RECOVERY_ROOT / "04-webp" / (row.get("category_slug") or "unknown") / image_role / f"{row.get('slug')}{suffix}.webp")


def policy_snapshot_for(row: dict[str, str], *, image_role: str) -> dict[str, Any]:
    policy = policy_for(row)
    return {
        "category_slug": row.get("category_slug") or "",
        "category_leaf": category_leaf_for(row),
        "article_pattern_id": row.get("article_pattern_id") or "",
        "image_role": image_role,
        "slot_index": slot_index_for(image_role),
        "layout_policy": policy.get("layout_policy"),
        "allowed_roles": list(roles_for(row)),
        "style": policy.get("style"),
        "anchors": list(policy.get("anchors") or ()),
        "live_apply_status_default": "blocked",
    }


def build_prompt_payload(row: dict[str, str], *, image_role: str) -> dict[str, Any]:
    return {
        "remote_post_id": row.get("remote_post_id", ""),
        "category_slug": row.get("category_slug", ""),
        "slug": row.get("slug", ""),
        "title": row.get("title", ""),
        "article_pattern_id": row.get("article_pattern_id", ""),
        "image_role": image_role,
        "reasons": sorted(reason_set(row)),
    }


def build_image_prompt(row: dict[str, str], *, image_role: str = "hero") -> str:
    category = row.get("category_slug") or ""
    title = row.get("title") or row.get("slug") or ""
    policy = policy_for(row)
    role_purpose = {
        "hero": "represent the overall post topic as one premium editorial hero image",
        "inline_1": "support the first inline slot with route, access, viewing flow, or queue context",
        "inline_2": "support the second inline slot with highlight, risk, time-of-day, booth, artwork, or space context",
    }.get(image_role, "represent the requested image role")
    return "\n".join(
        [
            "Use case: editorial blog image",
            "Asset type: Cloudflare blog canonical ImageGen asset",
            f"Post title: {title}",
            f"Category: {category}",
            f"Image role: {image_role}",
            f"Role purpose: {role_purpose}",
            f"Layout policy: {policy.get('layout_policy')}",
            f"Visual policy: {policy.get('style')}",
            f"Required anchors: {', '.join(str(item) for item in policy.get('anchors') or [])}",
            "Composition: one single 16:9 polished editorial image. Do not force a universal 3x3 collage.",
            "Requirements: no text overlays, no logos, no watermarks, no UI brand marks, no unrelated category imagery.",
            "Mood: premium Korean editorial archive, clear subject hierarchy, high readability at thumbnail size.",
            "Output intent: PNG backup first, then WebP conversion and R2 upload by BloggerGent. Do not update live directly from generation.",
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
            for image_role in roles_for(row):
                prompt_payload = build_prompt_payload(row, image_role=image_role)
                policy_snapshot = policy_snapshot_for(row, image_role=image_role)
                image_targets.append(
                    {
                        **base,
                        "job_id": f"{row.get('remote_post_id') or row.get('slug')}::{image_role}",
                        "article_pattern_id": row.get("article_pattern_id", ""),
                        "image_role": image_role,
                        "slot_index": str(slot_index_for(image_role)),
                        "prompt_payload_json": json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":")),
                        "policy_snapshot_json": json.dumps(policy_snapshot, ensure_ascii=False, separators=(",", ":")),
                        "imagegen_prompt": build_image_prompt(row, image_role=image_role),
                        "policy_path": str(category_policy_path(row.get("category_slug", ""))),
                        "png_path": local_png_for(row, image_role=image_role),
                        "webp_path": local_webp_for(row, image_role=image_role),
                        "r2_key": r2_key_for(row, image_role=image_role),
                        "public_url": public_url_for(row, image_role=image_role),
                        "generation_status": "queued",
                        "r2_upload_status": "blocked",
                        "verify_status": "blocked",
                        "live_apply_status": "blocked",
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
        "job_id",
        "remote_post_id",
        "category_slug",
        "slug",
        "title",
        "post_url",
        "thumbnail_url",
        "reasons",
        "article_pattern_id",
        "image_role",
        "slot_index",
        "prompt_payload_json",
        "policy_snapshot_json",
        "imagegen_prompt",
        "policy_path",
        "png_path",
        "webp_path",
        "r2_key",
        "public_url",
        "generation_status",
        "r2_upload_status",
        "verify_status",
        "live_apply_status",
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
        "image_generation_target_posts": len({row.get("remote_post_id") or row.get("slug") for row in image_targets}),
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
- 기본은 한 게시글당 `hero` 1장만 생성한다.
- `문화와-공간`, `축제와-현장`만 `hero`, `inline_1`, `inline_2`를 생성할 수 있다.
- PNG 원본은 `03-generated-png/<category>/<image_role>/<slug>.png`에 둔다.
- WebP 변환본은 `04-webp/<category>/<image_role>/<slug>.webp`에 둔다.
- R2 key는 `assets/media/cloudflare/dongri-archive/<category-leaf>/YYYY/MM/<slug>/<slug>[-inline-1|-inline-2].webp`만 허용한다.
- 공개 URL은 `https://api.dongriarchive.com/assets/media/cloudflare/dongri-archive/...`만 허용한다.
- live 반영은 `HEAD/GET 200`과 `Content-Type image/*` 확인 후에만 한다.
- 큐 생성 단계의 기본 `live_apply_status`는 `blocked`다.

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
- 필수 컬럼: `job_id`, `remote_post_id`, `category_slug`, `slug`, `title`, `article_pattern_id`, `image_role`, `slot_index`, `prompt_payload_json`, `policy_snapshot_json`, `imagegen_prompt`, `png_path`, `webp_path`, `r2_key`, `public_url`, `generation_status`, `r2_upload_status`, `verify_status`, `live_apply_status`

## 생성
- 내장 `image_gen` 스킬을 사용한다.
- 별도 CLI fallback은 쓰지 않는다.
- `image_role`은 `hero`, `inline_1`, `inline_2` 중 하나여야 한다.
- 이미지에는 텍스트, 로고, 워터마크를 넣지 않는다.
- 카테고리 정책은 `policy_path`를 기준으로 한다.

## 저장
- 생성 결과는 반드시 `png_path`에 복사한다.
- 프로젝트/게시글에 참조되는 이미지를 Codex 기본 생성 폴더에만 남기지 않는다.

## 반영
- WebP 변환과 R2 업로드 후 `public_url`이 이미지로 열릴 때만 live 반영한다.
- `verify_status=ok` 전에는 `live_apply_status=blocked`를 유지한다.
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
