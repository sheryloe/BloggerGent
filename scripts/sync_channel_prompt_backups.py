from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.content.channel_prompt_service import sync_all_channel_prompt_backups  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        flows = sync_all_channel_prompt_backups(db, include_disconnected=True)

    payload = {
        "status": "ok",
        "synced_channels": len(flows),
        "channels": [
            {
                "channel_id": flow.channel_id,
                "provider": flow.provider,
                "backup_directory": flow.backup_directory,
                "step_files": [step.backup_relative_path for step in flow.steps if step.backup_relative_path],
            }
            for flow in flows
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
