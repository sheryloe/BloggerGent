from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
WINDOWS_RUNTIME_STORAGE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage")

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    default_storage_root = WINDOWS_RUNTIME_STORAGE_ROOT if WINDOWS_RUNTIME_STORAGE_ROOT.exists() else LOCAL_STORAGE_ROOT
    os.environ["STORAGE_ROOT"] = str(default_storage_root)

sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import sync_cloudflare_prompts_from_files  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Cloudflare prompt templates from prompts/cloudflare/*.md")
    parser.add_argument("--execute", action="store_true", help="Apply prompt updates (default: dry-run)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with SessionLocal() as db:
        result = sync_cloudflare_prompts_from_files(db, execute=bool(args.execute))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
