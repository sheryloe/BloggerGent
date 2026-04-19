from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
DEFAULT_ARCHIVE_TAG = "2026-04-travel-r2"
SCRIPT_TARGETS = (
    REPO_ROOT / "scripts",
    REPO_ROOT / "apps" / "api" / "scripts",
)
KEEP_FILES = {
    "migrate_travel_assets_to_root_layout.py",
    "sync_travel_live_db_and_related.py",
    "audit_blogger_images.py",
    "archive_oneoff_scripts.py",
}
DATE_SUFFIX_RE = re.compile(r"_20\d{6,8}\.py$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive one-off Python scripts into _oneoff_archive folders (Travel-safe mode)."
    )
    parser.add_argument("--execute", action="store_true", help="Move files instead of dry-run listing.")
    parser.add_argument("--archive-tag", default=DEFAULT_ARCHIVE_TAG)
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    return parser.parse_args()


def _should_archive(path: Path) -> tuple[bool, str]:
    name = path.name
    lowered = name.lower()
    if name in KEEP_FILES:
        return False, "keep_core"
    if lowered.startswith("tmp_"):
        return True, "tmp_prefix"
    if lowered.startswith("manual_"):
        return True, "manual_prefix"
    if DATE_SUFFIX_RE.search(lowered):
        return True, "date_suffix"
    if "retrofit_batch" in lowered:
        return True, "retrofit_batch"
    if "canary" in lowered and "travel" not in lowered:
        return True, "canary_helper"
    return False, "not_candidate"


def _report_path(report_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = report_root / "reports" / f"travel-oneoff-archive-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _archive_dir(base_dir: Path, archive_tag: str) -> Path:
    return base_dir / "_oneoff_archive" / archive_tag


def main() -> int:
    args = parse_args()
    report_root = Path(str(args.report_root)).resolve()
    archive_tag = str(args.archive_tag or DEFAULT_ARCHIVE_TAG).strip() or DEFAULT_ARCHIVE_TAG

    items: list[dict[str, Any]] = []
    moved_count = 0
    candidate_count = 0
    skipped_count = 0

    for base_dir in SCRIPT_TARGETS:
        if not base_dir.exists():
            continue
        archive_dir = _archive_dir(base_dir, archive_tag)
        files = sorted(base_dir.glob("*.py"))
        for path in files:
            should_archive, reason = _should_archive(path)
            if not should_archive:
                continue
            candidate_count += 1
            destination = archive_dir / path.name
            row: dict[str, Any] = {
                "source": str(path),
                "destination": str(destination),
                "reason": reason,
                "status": "planned",
            }
            if args.execute:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    row["status"] = "skipped"
                    row["reason"] = "destination_exists"
                    skipped_count += 1
                else:
                    shutil.move(str(path), str(destination))
                    row["status"] = "moved"
                    moved_count += 1
            items.append(row)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execute": bool(args.execute),
        "archive_tag": archive_tag,
        "report_root": str(report_root),
        "summary": {
            "candidate_count": candidate_count,
            "moved_count": moved_count,
            "skipped_count": skipped_count,
        },
        "items": items,
    }
    output_path = _report_path(report_root)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**payload["summary"], "report_path": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
