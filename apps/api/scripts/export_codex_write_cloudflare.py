from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    configured = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    cursor = Path(__file__).resolve().parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "apps" / "api").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_STORAGE_ROOT = REPO_ROOT / "storage"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(DEFAULT_STORAGE_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.cloudflare.cloudflare_codex_write_service import export_codex_write_packages  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export current Cloudflare posts into codex_write JSON seeds.")
    parser.add_argument("--category", action="append", default=[], help="Canonical Cloudflare category slug (repeatable)")
    parser.add_argument("--slug", default="", help="Only export one post slug")
    parser.add_argument("--limit", type=int, default=0, help="Maximum posts to export")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing JSON files")
    parser.add_argument("--no-sync-before", action="store_true", help="Skip sync before export")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with SessionLocal() as db:
        result = export_codex_write_packages(
            db,
            category_slugs=args.category or None,
            slug=args.slug or None,
            limit=(args.limit if args.limit > 0 else None),
            overwrite=bool(args.overwrite),
            sync_before=not bool(args.no_sync_before),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
