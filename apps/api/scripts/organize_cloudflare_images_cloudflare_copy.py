from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_SOURCE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\images")

CATEGORY_RULES: dict[str, list[tuple[str, int]]] = {
    "개발과-프로그래밍": [
        ("openai", 5),
        ("codex", 5),
        ("claude", 4),
        ("gemini", 4),
        ("llm", 4),
        ("api", 4),
        ("automation", 4),
        ("workflow", 4),
        ("agent", 3),
        ("ai-", 3),
        ("coding", 3),
        ("developer", 3),
    ],
    "일상과-메모": [
        ("memo", 5),
        ("daily", 4),
        ("routine", 4),
        ("journal", 4),
        ("thought", 4),
        ("note", 4),
        ("habit", 3),
        ("morning", 3),
        ("evening", 3),
        ("commute", 3),
    ],
    "여행과-기록": [
        ("travel", 5),
        ("trip", 4),
        ("route", 4),
        ("walk", 4),
        ("temple", 4),
        ("cathedral", 4),
        ("gyeonggijeon", 4),
        ("hwaeomsa", 4),
        ("jeonju", 3),
        ("gurye", 3),
        ("course", 3),
        ("itinerary", 3),
    ],
    "축제와-현장": [
        ("festival", 6),
        ("parade", 4),
        ("ticket", 4),
        ("lodging", 4),
        ("accommodation", 4),
        ("food", 3),
        ("seafood", 3),
        ("mud", 3),
        ("firework", 3),
        ("opera", 3),
        ("film", 3),
    ],
    "문화와-공간": [
        ("museum", 5),
        ("gallery", 5),
        ("exhibition", 5),
        ("culture", 4),
        ("art", 4),
        ("curator", 4),
        ("opera", 3),
        ("library", 3),
        ("heritage", 3),
        ("space", 3),
    ],
    "미스테리아-스토리": [
        ("mystery", 6),
        ("case", 5),
        ("evidence", 4),
        ("incident", 4),
        ("unsolved", 4),
        ("investigation", 4),
        ("timeline", 3),
        ("trace", 3),
    ],
    "동그리의-생각": [
        ("reflection", 5),
        ("essay", 5),
        ("monologue", 4),
        ("thoughts", 4),
        ("mind", 3),
    ],
    "삶을-유용하게": [
        ("checklist", 5),
        ("guide", 4),
        ("tips", 4),
        ("how-to", 4),
        ("practical", 4),
        ("productivity", 3),
        ("lifehack", 3),
    ],
    "삶의-기름칠": [
        ("benefit", 5),
        ("support", 5),
        ("welfare", 5),
        ("application", 4),
        ("subsidy", 4),
        ("eligibility", 4),
        ("policy", 3),
    ],
    "주식의-흐름": [
        ("stock", 5),
        ("market", 4),
        ("earnings", 4),
        ("trading", 4),
        ("equity", 4),
        ("nasdaq", 3),
        ("ticker", 3),
    ],
    "나스닥의-흐름": [
        ("nasdaq", 6),
        ("ionq", 5),
        ("sandisk", 5),
        ("ticker", 4),
        ("quarterly", 4),
        ("guidance", 4),
    ],
    "크립토의-흐름": [
        ("crypto", 6),
        ("bitcoin", 5),
        ("ethereum", 5),
        ("token", 4),
        ("onchain", 4),
        ("defi", 4),
    ],
}


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _safe_path_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value).strip("-_.") or "file"


def _score_category(file_name_lower: str, category: str) -> tuple[int, list[str]]:
    score = 0
    matched: list[str] = []
    for keyword, weight in CATEGORY_RULES.get(category, []):
        if keyword in file_name_lower:
            score += weight
            matched.append(keyword)
    return score, matched


def _pick_category(path: Path) -> tuple[str, str, float]:
    name = path.name.casefold()
    scores: dict[str, tuple[int, list[str]]] = {}
    for category in CATEGORY_RULES:
        scores[category] = _score_category(name, category)
    sorted_items = sorted(scores.items(), key=lambda item: item[1][0], reverse=True)
    top_category, (top_score, top_keywords) = sorted_items[0]
    second_score = sorted_items[1][1][0] if len(sorted_items) > 1 else 0
    if top_score <= 0:
        return "미분류", "fallback:unmatched", 0.0
    confidence = top_score / max(1.0, float(top_score + second_score))
    rule = f"token:{'|'.join(top_keywords[:6])}" if top_keywords else "token:scored"
    return top_category, rule, round(confidence, 4)


def _build_output_path(dst_dir: Path, source_path: Path) -> Path:
    candidate = dst_dir / source_path.name
    if not candidate.exists():
        return candidate
    digest = hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:10]
    stem = _safe_path_token(source_path.stem)
    suffix = source_path.suffix.lower()
    return dst_dir / f"{stem}-{digest}{suffix}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy-only organization for runtime images into Cloudflare category folders.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="Source image root directory.")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only, no copy.")
    parser.add_argument(
        "--include-subdirs",
        action="store_true",
        help="Include nested folders under source root. Default is top-level files only.",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=610,
        help="Expected input file count. Used for report and optional truncation.",
    )
    parser.add_argument(
        "--truncate-to-expected",
        action="store_true",
        help="If input files exceed expected-count, keep oldest N files.",
    )
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"Image source root not found: {source_root}")

    now = datetime.now(timezone.utc).astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    cloudflare_root = source_root / "Cloudflare"
    manifest_dir = cloudflare_root / "_manifests"
    manifest_json_path = manifest_dir / f"classification-{stamp}.json"
    manifest_csv_path = manifest_dir / f"classification-{stamp}.csv"

    if args.include_subdirs:
        candidate_iter = source_root.rglob("*")
    else:
        candidate_iter = source_root.glob("*")

    files = [
        path
        for path in candidate_iter
        if path.is_file() and path.suffix.casefold() in IMAGE_EXTS and cloudflare_root not in path.parents
    ]
    files = sorted(files, key=lambda path: str(path).casefold())
    skipped_overflow: list[str] = []
    if args.expected_count > 0 and len(files) > args.expected_count and args.truncate_to_expected:
        files_by_age = sorted(files, key=lambda path: (path.stat().st_mtime, str(path).casefold()))
        selected = files_by_age[: args.expected_count]
        selected_set = set(selected)
        skipped_overflow = [str(path) for path in files if path not in selected_set]
        files = sorted(selected, key=lambda path: str(path).casefold())

    rows: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()

    for source_path in files:
        category, rule, confidence = _pick_category(source_path)
        category_counter[category] += 1
        target_dir = cloudflare_root / category
        target_path = _build_output_path(target_dir, source_path)
        if not args.dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        rows.append(
            {
                "source": str(source_path),
                "target_category": category,
                "target_path": str(target_path),
                "rule": rule,
                "confidence": confidence,
            },
        )

    low_confidence = [row for row in rows if float(row.get("confidence", 0.0)) < 0.55]
    summary = {
        "mode": "dry_run" if args.dry_run else "execute",
        "source_root": str(source_root),
        "target_root": str(cloudflare_root),
        "include_subdirs": bool(args.include_subdirs),
        "expected_count": int(args.expected_count),
        "input_file_count": len(files),
        "classified_count": len(rows),
        "low_confidence_count": len(low_confidence),
        "overflow_skipped_count": len(skipped_overflow),
        "overflow_skipped_files": skipped_overflow,
        "category_distribution": dict(sorted(category_counter.items(), key=lambda item: item[0])),
        "artifacts": {
            "manifest_json": str(manifest_json_path),
            "manifest_csv": str(manifest_csv_path),
        },
        "timestamp": now.isoformat(timespec="seconds"),
    }
    payload = {"summary": summary, "rows": rows, "low_confidence": low_confidence}
    _write_json(manifest_json_path, payload)
    _write_csv(
        manifest_csv_path,
        rows,
        fieldnames=["source", "target_category", "target_path", "rule", "confidence"],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
