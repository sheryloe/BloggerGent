from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CATEGORY_PROFILE: dict[str, str] = {
    "개발과-프로그래밍": "tech",
    "여행과-기록": "travel",
    "축제와-현장": "travel",
    "문화와-공간": "travel",
    "미스테리아-스토리": "mystery",
    "주식의-흐름": "finance",
    "나스닥의-흐름": "finance",
    "크립토의-흐름": "finance",
    "삶을-유용하게": "daily",
    "삶의-기름칠": "daily",
    "동그리의-생각": "daily",
    "일상과-메모": "daily",
}

PROFILE_TOKENS: dict[str, tuple[str, ...]] = {
    "tech": (
        "dev",
        "tool",
        "ai",
        "tech",
        "program",
        "copilot",
        "codex",
        "claude",
        "gemini",
        "mcp",
        "agent",
        "api",
        "automation",
        "workflow",
        "koding",
        "peurogeuraeming",
        "gaebal",
        "개발",
        "프로그래밍",
        "자동화",
    ),
    "travel": (
        "travel",
        "festival",
        "culture",
        "food",
        "trip",
        "tour",
        "museum",
        "popup",
        "yeohaeng",
        "chukje",
        "munhwa",
        "여행",
        "축제",
        "문화",
        "맛집",
        "전시",
        "카페",
        "동선",
    ),
    "finance": (
        "stock",
        "crypto",
        "coin",
        "blockchain",
        "nasdaq",
        "etf",
        "bitcoin",
        "biteukoin",
        "ideorium",
        "keuripto",
        "sec",
        "jusig",
        "kripto",
        "주식",
        "코인",
        "크립토",
        "나스닥",
        "가상자산",
    ),
    "mystery": (
        "mystery",
        "mysteria",
        "unsolved",
        "legend",
        "lore",
        "dyatlov",
        "zodiac",
        "case",
        "괴담",
        "전설",
        "미스터리",
        "미스테리",
        "사건",
    ),
    "daily": (
        "daily",
        "life",
        "memo",
        "welfare",
        "routine",
        "habit",
        "ilsang",
        "saenggag",
        "bokji",
        "일상",
        "메모",
        "복지",
        "생각",
        "정리",
    ),
}

CATEGORY_FORBIDDEN_TOKENS: dict[str, tuple[str, ...]] = {
    "개발과-프로그래밍": (
        "iran",
        "war",
        "tariff",
        "inflation",
        "festival",
        "travel",
        "yeohaeng",
        "chukje",
        "stock",
        "nasdaq",
        "crypto",
        "coin",
        "etf",
        "mystery",
        "dyatlov",
        "전쟁",
        "관세",
        "축제",
        "여행",
        "주식",
        "크립토",
        "미스터리",
    ),
    "나스닥의-흐름": ("travel", "festival", "yeohaeng", "chukje", "mystery", "dyatlov", "전설", "괴담"),
    "크립토의-흐름": ("travel", "festival", "yeohaeng", "chukje", "mystery", "dyatlov", "전설", "괴담"),
    "주식의-흐름": ("travel", "festival", "yeohaeng", "chukje", "mystery", "dyatlov", "전설", "괴담"),
    "여행과-기록": ("stock", "nasdaq", "crypto", "coin", "etf", "주식", "크립토", "나스닥"),
    "축제와-현장": ("stock", "nasdaq", "crypto", "coin", "etf", "주식", "크립토", "나스닥"),
    "문화와-공간": ("stock", "nasdaq", "crypto", "coin", "etf", "주식", "크립토", "나스닥"),
    "미스테리아-스토리": ("stock", "nasdaq", "crypto", "coin", "etf", "travel", "festival", "여행", "축제"),
    "삶을-유용하게": ("stock", "nasdaq", "crypto", "coin", "etf", "dyatlov", "mystery"),
    "삶의-기름칠": ("stock", "nasdaq", "crypto", "coin", "etf", "dyatlov", "mystery"),
    "동그리의-생각": ("stock", "nasdaq", "crypto", "coin", "etf"),
    "일상과-메모": ("stock", "nasdaq", "crypto", "coin", "etf"),
}

SPACE_RE = re.compile(r"\s+")


@dataclass
class PostRow:
    id: int
    remote_post_id: str
    slug: str
    title: str
    category_slug: str
    published_at: str
    normalized_title: str
    duplicate_group_id: str
    duplicate_group_size: int
    is_group_keeper: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cloudflare category audit report (report-only).")
    parser.add_argument("--postgres-container", default="bloggent-postgres-1")
    parser.add_argument("--db-user", default="bloggent")
    parser.add_argument("--db-name", default="bloggent")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument(
        "--report-root",
        default="",
        help="Override report root. Default: D:\\Donggri_Runtime\\BloggerGent\\storage\\cloudflare\\reports.",
    )
    return parser.parse_args()


def resolve_report_root(arg_value: str) -> Path:
    if arg_value.strip():
        return Path(arg_value).resolve()
    runtime_root = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
    if runtime_root.exists() or runtime_root.parent.exists():
        return runtime_root
    return runtime_root


def query_rows(*, postgres_container: str, db_user: str, db_name: str) -> list[dict[str, str]]:
    sql = (
        "select id, coalesce(remote_post_id,''), coalesce(slug,''), coalesce(title,''), "
        "coalesce(canonical_category_slug,''), coalesce(to_char(published_at,'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),''), "
        "coalesce(status,'') "
        "from synced_cloudflare_posts "
        "where status='published' "
        "order by published_at desc nulls last, id desc"
    )
    cmd = [
        "docker",
        "exec",
        postgres_container,
        "psql",
        "-U",
        db_user,
        "-d",
        db_name,
        "-A",
        "-F",
        "\t",
        "-t",
        "-c",
        sql,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"psql query failed: {stderr}")

    rows: list[dict[str, str]] = []
    stdout = result.stdout.decode("utf-8", errors="ignore")
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "id": parts[0].strip(),
                "remote_post_id": parts[1].strip(),
                "slug": parts[2].strip(),
                "title": parts[3].strip(),
                "category_slug": parts[4].strip(),
                "published_at": parts[5].strip(),
                "status": parts[6].strip(),
            }
        )
    return rows


def normalize_title(title: str) -> str:
    lowered = str(title or "").strip().lower()
    return SPACE_RE.sub(" ", lowered).strip()


def profile_hits(text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    lowered = text.lower()
    for profile, tokens in PROFILE_TOKENS.items():
        matched = [token for token in tokens if token in lowered]
        if matched:
            hits[profile] = matched
    return hits


def predict_profile(text: str) -> tuple[str, dict[str, list[str]]]:
    hits = profile_hits(text)
    if not hits:
        return "unknown", hits
    ranked = sorted(hits.items(), key=lambda item: (len(item[1]), item[0]), reverse=True)
    return ranked[0][0], hits


def detect_forbidden_tokens(category_slug: str, text: str) -> list[str]:
    tokens = CATEGORY_FORBIDDEN_TOKENS.get(category_slug, ())
    lowered = text.lower()
    return [token for token in tokens if token in lowered]


def group_duplicates(rows: list[dict[str, str]]) -> list[PostRow]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[normalize_title(row["title"])].append(row)

    post_rows: list[PostRow] = []
    for normalized, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                str(item.get("published_at") or ""),
                int(item.get("id") or 0),
            ),
            reverse=True,
        )
        group_id = f"dup-{hashlib.sha1(normalized.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
        keeper_id = int(ordered[0]["id"]) if ordered else -1
        group_size = len(ordered)
        for item in ordered:
            item_id = int(item["id"])
            post_rows.append(
                PostRow(
                    id=item_id,
                    remote_post_id=item["remote_post_id"],
                    slug=item["slug"],
                    title=item["title"],
                    category_slug=item["category_slug"],
                    published_at=item["published_at"],
                    normalized_title=normalized,
                    duplicate_group_id=group_id,
                    duplicate_group_size=group_size,
                    is_group_keeper=item_id == keeper_id,
                )
            )
    return post_rows


def classify_keeper(row: PostRow) -> dict[str, str]:
    expected_profile = CATEGORY_PROFILE.get(row.category_slug, "unknown")
    text = f"{row.slug} {row.title}"
    predicted_profile, hits = predict_profile(text)
    forbidden_hits = detect_forbidden_tokens(row.category_slug, text)
    matched_rules: list[str] = []

    for profile, tokens in sorted(hits.items()):
        matched_rules.append(f"profile:{profile}({len(tokens)})")
    if forbidden_hits:
        matched_rules.append("forbidden:" + ",".join(sorted(set(forbidden_hits))))

    if forbidden_hits:
        confidence = "high"
        reason_code = "forbidden_token_hit"
    elif predicted_profile not in {"unknown", expected_profile} and expected_profile != "unknown":
        confidence = "medium"
        reason_code = "profile_mismatch"
    else:
        confidence = "normal"
        reason_code = "aligned_or_unknown"

    return {
        "category_slug": row.category_slug,
        "slug": row.slug,
        "title": row.title,
        "published_at": row.published_at,
        "remote_post_id": row.remote_post_id,
        "expected_profile": expected_profile,
        "predicted_profile": predicted_profile,
        "confidence_level": confidence,
        "matched_rules": "|".join(matched_rules),
        "reason_code": reason_code,
        "duplicate_group_id": row.duplicate_group_id,
        "is_group_keeper": "1" if row.is_group_keeper else "0",
    }


def write_csv(path: Path, rows: Iterable[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def main() -> None:
    args = parse_args()
    report_root = resolve_report_root(args.report_root)
    report_root.mkdir(parents=True, exist_ok=True)

    raw_rows = query_rows(
        postgres_container=args.postgres_container,
        db_user=args.db_user,
        db_name=args.db_name,
    )
    if not raw_rows:
        raise RuntimeError("No published rows found from synced_cloudflare_posts.")

    all_grouped = group_duplicates(raw_rows)
    keepers = [row for row in all_grouped if row.is_group_keeper]
    classified = [classify_keeper(row) for row in keepers]
    high_confidence = [row for row in classified if row["confidence_level"] == "high"]
    review = [row for row in classified if row["confidence_level"] == "medium"]

    by_category_rows: list[dict[str, str]] = []
    all_categories = sorted(set(CATEGORY_PROFILE.keys()) | {row.category_slug for row in all_grouped})
    by_cat_total_all = Counter(row.category_slug for row in all_grouped)
    by_cat_keepers = Counter(row.category_slug for row in keepers)
    by_cat_high = Counter(row["category_slug"] for row in high_confidence)
    by_cat_review = Counter(row["category_slug"] for row in review)
    by_cat_normal = Counter(row["category_slug"] for row in classified if row["confidence_level"] == "normal")

    for category in all_categories:
        total_posts = by_cat_total_all.get(category, 0)
        keeper_posts = by_cat_keepers.get(category, 0)
        by_category_rows.append(
            {
                "category_slug": category,
                "total_posts": str(total_posts),
                "keeper_posts": str(keeper_posts),
                "duplicate_rows_removed": str(max(total_posts - keeper_posts, 0)),
                "high_confidence_count": str(by_cat_high.get(category, 0)),
                "review_count": str(by_cat_review.get(category, 0)),
                "normal_count": str(by_cat_normal.get(category, 0)),
            }
        )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "synced_cloudflare_posts",
        "source_scope": "integrations published",
        "published_total_rows": len(raw_rows),
        "duplicate_group_count": len({row.duplicate_group_id for row in all_grouped}),
        "keeper_rows": len(keepers),
        "duplicate_rows_removed": len(raw_rows) - len(keepers),
        "high_confidence_count": len(high_confidence),
        "review_count": len(review),
        "normal_count": sum(1 for row in classified if row["confidence_level"] == "normal"),
        "target_known_case_found": any(
            row["slug"] == "iran-jeonjaeng-2026-04-04-gijun-sangtae-hwakindoen-sageongwa-hyanghu-sinario"
            and row["confidence_level"] == "high"
            for row in high_confidence
        ),
        "report_root": str(report_root),
    }

    date_tag = args.date
    summary_path = report_root / f"cloudflare-category-audit-summary-{date_tag}.json"
    by_category_path = report_root / f"cloudflare-category-audit-by-category-{date_tag}.csv"
    high_path = report_root / f"cloudflare-category-audit-high-confidence-{date_tag}.csv"
    review_path = report_root / f"cloudflare-category-audit-review-{date_tag}.csv"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(
        by_category_path,
        by_category_rows,
        [
            "category_slug",
            "total_posts",
            "keeper_posts",
            "duplicate_rows_removed",
            "high_confidence_count",
            "review_count",
            "normal_count",
        ],
    )
    detail_columns = [
        "category_slug",
        "slug",
        "title",
        "published_at",
        "remote_post_id",
        "expected_profile",
        "predicted_profile",
        "confidence_level",
        "matched_rules",
        "reason_code",
        "duplicate_group_id",
        "is_group_keeper",
    ]
    write_csv(high_path, high_confidence, detail_columns)
    write_csv(review_path, review, detail_columns)

    print(json.dumps(
        {
            "summary": str(summary_path),
            "by_category": str(by_category_path),
            "high_confidence": str(high_path),
            "review": str(review_path),
            **summary,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
