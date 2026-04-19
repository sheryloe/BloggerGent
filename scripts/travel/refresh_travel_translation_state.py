from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.content.travel_translation_state_service import refresh_travel_translation_state  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Travel EN/ES/JA translation readiness state.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--no-report", action="store_true")
    return parser.parse_args()


def _parse_blog_ids(raw: str | None) -> tuple[int, ...]:
    allowed = {34, 36, 37}
    values: list[int] = []
    for token in [segment.strip() for segment in str(raw or "").split(",") if segment.strip()]:
        blog_id = int(token)
        if blog_id not in allowed:
            raise ValueError(f"Travel translation refresh allows only {sorted(allowed)}; got {blog_id}")
        if blog_id not in values:
            values.append(blog_id)
    if not values:
        raise ValueError("--blog-ids resolved to empty set")
    return tuple(sorted(values))


def main() -> int:
    args = parse_args()
    blog_ids = _parse_blog_ids(args.blog_ids)
    report_root = Path(str(args.report_root)).resolve()
    with SessionLocal() as db:
        payload = refresh_travel_translation_state(
            db,
            blog_ids=blog_ids,
            report_root=report_root,
            write_report=not bool(args.no_report),
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
