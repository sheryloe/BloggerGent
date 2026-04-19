from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RULE_RE = re.compile(r"^profile:([a-z]+)\((\d+)\)$")

PROFILE_PRIMARY_CATEGORY = {
    "tech": "개발과-프로그래밍",
    "travel": "여행과-기록",
    "finance": "주식의-흐름",
    "mystery": "미스테리아-스토리",
    "daily": "일상과-메모",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Cloudflare category audit approval list from review CSV.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument(
        "--report-root",
        default=r"D:\Donggri_Runtime\BloggerGent\storage\CloudFlare\_reports",
    )
    parser.add_argument(
        "--input",
        default="",
        help="Override review CSV path. Default: cloudflare-category-audit-review-<date>.csv in report root.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def parse_profile_scores(matched_rules: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for chunk in str(matched_rules or "").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = RULE_RE.match(chunk)
        if not m:
            continue
        profile = m.group(1)
        score = int(m.group(2))
        scores[profile] = score
    return scores


def recommend_action(row: dict[str, str]) -> dict[str, str]:
    expected = str(row.get("expected_profile") or "").strip()
    predicted = str(row.get("predicted_profile") or "").strip()
    scores = parse_profile_scores(str(row.get("matched_rules") or ""))
    predicted_score = int(scores.get(predicted, 0))
    expected_score = int(scores.get(expected, 0))

    recommended_target = PROFILE_PRIMARY_CATEGORY.get(predicted, "")
    action = "hold"
    rationale = "evidence_not_strong_enough"

    # Conservative move rule:
    # move only when predicted evidence is clearly stronger.
    if predicted and predicted != expected:
        if predicted_score >= 2 and predicted_score > expected_score:
            action = "move"
            rationale = "predicted_profile_stronger"
        elif predicted_score >= 3:
            action = "move"
            rationale = "predicted_profile_very_strong"

    if action == "hold":
        recommended_target = ""

    return {
        "recommended_action": action,
        "recommended_target_category_slug": recommended_target,
        "predicted_score": str(predicted_score),
        "expected_score": str(expected_score),
        "approval_rationale": rationale,
    }


def main() -> None:
    args = parse_args()
    report_root = Path(args.report_root).resolve()
    input_path = Path(args.input).resolve() if args.input.strip() else report_root / f"cloudflare-category-audit-review-{args.date}.csv"
    if not input_path.exists():
        raise FileNotFoundError(f"Review CSV not found: {input_path}")

    rows = read_csv(input_path)
    output_rows: list[dict[str, str]] = []
    for row in rows:
        decision = recommend_action(row)
        output_rows.append(
            {
                "category_slug": str(row.get("category_slug") or "").strip(),
                "slug": str(row.get("slug") or "").strip(),
                "title": str(row.get("title") or "").strip(),
                "published_at": str(row.get("published_at") or "").strip(),
                "remote_post_id": str(row.get("remote_post_id") or "").strip(),
                "expected_profile": str(row.get("expected_profile") or "").strip(),
                "predicted_profile": str(row.get("predicted_profile") or "").strip(),
                "confidence_level": str(row.get("confidence_level") or "").strip(),
                "matched_rules": str(row.get("matched_rules") or "").strip(),
                "reason_code": str(row.get("reason_code") or "").strip(),
                "duplicate_group_id": str(row.get("duplicate_group_id") or "").strip(),
                "is_group_keeper": str(row.get("is_group_keeper") or "").strip(),
                **decision,
            }
        )

    by_category: dict[str, Counter] = defaultdict(Counter)
    for row in output_rows:
        cat = row["category_slug"]
        by_category[cat]["total"] += 1
        by_category[cat][row["recommended_action"]] += 1

    by_category_rows: list[dict[str, str]] = []
    for cat in sorted(by_category.keys()):
        counters = by_category[cat]
        by_category_rows.append(
            {
                "category_slug": cat,
                "total_review_rows": str(counters.get("total", 0)),
                "move_count": str(counters.get("move", 0)),
                "hold_count": str(counters.get("hold", 0)),
            }
        )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "review_total": len(output_rows),
        "move_total": sum(1 for row in output_rows if row["recommended_action"] == "move"),
        "hold_total": sum(1 for row in output_rows if row["recommended_action"] == "hold"),
        "report_root": str(report_root),
    }

    detail_path = report_root / f"cloudflare-category-audit-approval-{args.date}.csv"
    by_category_path = report_root / f"cloudflare-category-audit-approval-by-category-{args.date}.csv"
    summary_path = report_root / f"cloudflare-category-audit-approval-summary-{args.date}.json"

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
        "predicted_score",
        "expected_score",
        "recommended_action",
        "recommended_target_category_slug",
        "approval_rationale",
    ]
    write_csv(detail_path, output_rows, detail_columns)
    write_csv(
        by_category_path,
        by_category_rows,
        ["category_slug", "total_review_rows", "move_count", "hold_count"],
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "summary": str(summary_path),
                "by_category": str(by_category_path),
                "detail": str(detail_path),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
