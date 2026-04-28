from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

if "DATABASE_URL" not in os.environ and not Path("/.dockerenv").exists():
    os.environ["DATABASE_URL"] = "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent"
if "STORAGE_ROOT" not in os.environ and not Path("/.dockerenv").exists():
    os.environ["STORAGE_ROOT"] = r"D:\Donggri_Runtime\BloggerGent\storage"

from app.db.session import SessionLocal
from app.models.entities import ManualImageSlotStatus
from app.services.content.manual_image_service import (
    apply_manual_image_slots,
    format_manual_image_slots_for_chat,
    list_manual_image_slots,
)


def _parse_apply_lines(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid apply line: {line}")
        serial_code, file_path = line.split("=", 1)
        serial_code = serial_code.strip()
        file_path = file_path.strip().strip('"')
        if not serial_code or not file_path:
            raise ValueError(f"Invalid apply line: {line}")
        items.append({"serial_code": serial_code, "file_path": file_path})
    return items


def _slot_to_dict(slot) -> dict:
    return {
        "id": slot.id,
        "serial_code": slot.serial_code,
        "provider": slot.provider,
        "blog_id": slot.blog_id,
        "article_id": slot.article_id,
        "remote_post_id": slot.remote_post_id,
        "slot_role": slot.slot_role,
        "prompt": slot.prompt,
        "status": slot.status.value if hasattr(slot.status, "value") else str(slot.status),
        "file_path": slot.file_path,
        "public_url": slot.public_url,
        "object_key": slot.object_key,
        "batch_key": slot.batch_key,
        "metadata": slot.slot_metadata or {},
    }


def pending_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        slots = list_manual_image_slots(
            db,
            provider=args.provider,
            status=ManualImageSlotStatus.PENDING,
            blog_id=args.blog_id,
            batch_key=args.batch_key,
            limit=args.limit,
        )
        if args.format == "json":
            print(json.dumps([_slot_to_dict(slot) for slot in slots], ensure_ascii=False, indent=2))
        else:
            print(format_manual_image_slots_for_chat(slots))
        return 0
    finally:
        db.close()


def apply_command(args: argparse.Namespace) -> int:
    input_text = sys.stdin.read() if args.stdin else "\n".join(args.item or [])
    items = _parse_apply_lines(input_text)
    if not items:
        raise ValueError("No apply items were provided.")
    db = SessionLocal()
    try:
        result = apply_manual_image_slots(db, items)
        print(json.dumps(
            {
                **{key: value for key, value in result.items() if key != "items"},
                "items": [_slot_to_dict(slot) for slot in result["items"]],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0 if result.get("failed_count", 0) == 0 else 2
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BloggerGent manual image prompt/apply operations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending = subparsers.add_parser("pending", help="Print pending manual image prompts.")
    pending.add_argument("--format", choices=["chat", "json"], default="chat")
    pending.add_argument("--provider", choices=["blogger", "cloudflare"], default=None)
    pending.add_argument("--blog-id", type=int, default=None)
    pending.add_argument("--batch-key", default=None)
    pending.add_argument("--limit", type=int, default=100)
    pending.set_defaults(func=pending_command)

    apply = subparsers.add_parser("apply", help="Apply generated local image files to pending slots.")
    apply.add_argument("--stdin", action="store_true", help="Read SERIAL=PATH mappings from stdin.")
    apply.add_argument("--item", action="append", help="SERIAL=PATH mapping. Can be repeated.")
    apply.set_defaults(func=apply_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
