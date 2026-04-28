from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.content.channel_prompt_service import build_prompt_flow


CHANNEL_ID = "cloudflare:dongriarchive"
MANAGED_CHANNEL_ID = 7
CATEGORY_KEY = "\ubbf8\uc2a4\ud14c\ub9ac\uc544-\uc2a4\ud1a0\ub9ac"
CATEGORY_NAME = "\ubbf8\uc2a4\ud14c\ub9ac\uc544 \uc2a4\ud1a0\ub9ac"
GROUP_NAME = "\uc138\uc0c1\uc758 \uae30\ub85d"
DIRECTORY_SLUG = "miseuteria-seutori"
GENERATION_GATE_POLICY = {
    "duplicate_gate": "hard",
    "scope": "same_blog_or_channel_category",
    "stop_before_article_generation": True,
    "stop_before_image_prompt_generation": True,
    "stop_before_image_generation": True,
    "no_db_write_for_blocked_topic": True,
    "no_publish_payload_for_blocked_topic": True,
    "body_h1_policy": "article_body_must_not_emit_h1",
}


def _repo_root() -> Path:
    resolved = Path(__file__).resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / "prompts").exists() and ((candidate / "app").exists() or (candidate / "apps").exists()):
            return candidate
    return Path.cwd()


REPO_ROOT = _repo_root()
ROOT_DIR = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive"
ROOT_CHANNEL_JSON = ROOT_DIR / "channel.json"
MYSTERY_CHANNEL_JSON = ROOT_DIR / GROUP_NAME / DIRECTORY_SLUG / "channel.json"


def _root_payload() -> dict:
    with SessionLocal() as db:
        flow = build_prompt_flow(db, CHANNEL_ID, sync_backup=False)
    return {
        "channel_id": flow.channel_id,
        "channel_name": flow.channel_name,
        "provider": flow.provider,
        "backup_directory": flow.backup_directory,
        "backup_files": sorted(
            [
                str(step.backup_relative_path or "").strip()
                for step in flow.steps
                if str(step.backup_relative_path or "").strip()
            ]
        ),
        "steps": [
            {
                "id": step.id,
                "stage_type": step.stage_type,
                "stage_label": step.stage_label,
                "name": step.name,
                "role_name": step.role_name,
                "objective": step.objective,
                "provider_hint": step.provider_hint,
                "provider_model": step.provider_model,
                "is_enabled": step.is_enabled,
                "is_required": step.is_required,
                "prompt_enabled": step.prompt_enabled,
                "sort_order": step.sort_order,
                "backup_relative_path": step.backup_relative_path,
                "planner_provider_hint": step.planner_provider_hint,
                "planner_provider_model": step.planner_provider_model,
                "pass_provider_hint": step.pass_provider_hint,
                "pass_provider_model": step.pass_provider_model,
                "structure_mode": step.structure_mode,
                "structure_segments": step.structure_segments,
                "locked_image_model": step.locked_image_model,
                "image_policy_version": step.image_policy_version,
                "image_layout_policy": step.image_layout_policy,
                "text_generation_route": step.text_generation_route,
                "policy_config": step.policy_config,
            }
            for step in sorted(flow.steps, key=lambda item: (item.sort_order, str(item.id)))
        ],
        "generation_gate_policy": GENERATION_GATE_POLICY,
    }


def _mystery_payload(root_payload: dict) -> dict:
    mystery_steps = [step for step in root_payload["steps"] if str(step["id"]).startswith(f"{CATEGORY_KEY}::")]
    backup_directory = f"channels/cloudflare/dongri-archive/{GROUP_NAME}/{DIRECTORY_SLUG}"
    return {
        "channel_id": f"{CHANNEL_ID}::{CATEGORY_KEY}",
        "root_channel_id": CHANNEL_ID,
        "channel_name": f"{root_payload['channel_name']} | {GROUP_NAME} | {CATEGORY_NAME}",
        "provider": "cloudflare",
        "backup_directory": backup_directory,
        "backup_files": sorted(
            [
                str(step.get("backup_relative_path") or "").strip()
                for step in mystery_steps
                if str(step.get("backup_relative_path") or "").strip()
            ]
        ),
        "steps": sorted(mystery_steps, key=lambda item: (item["sort_order"], str(item["id"]))),
        "generation_gate_policy": GENERATION_GATE_POLICY,
    }


def _verify_scope() -> dict:
    with SessionLocal() as db:
        channel = db.execute(
            select(ManagedChannel.id, ManagedChannel.channel_id, ManagedChannel.display_name, ManagedChannel.base_url).where(
                ManagedChannel.id == MANAGED_CHANNEL_ID
            )
        ).one()
        mystery_count = db.execute(
            select(func.count())
            .select_from(SyncedCloudflarePost)
            .where(
                SyncedCloudflarePost.managed_channel_id == MANAGED_CHANNEL_ID,
                SyncedCloudflarePost.canonical_category_slug == CATEGORY_KEY,
            )
        ).scalar_one()
    return {
        "managed_channel_id": channel.id,
        "channel_id": channel.channel_id,
        "display_name": channel.display_name,
        "base_url": channel.base_url,
        "mystery_post_count": int(mystery_count or 0),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair active Cloudflare mystery prompt metadata only.")
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    args = parser.parse_args()

    scope = _verify_scope()
    root_payload = _root_payload()
    mystery_payload = _mystery_payload(root_payload)
    result = {
        "mode": args.mode,
        "scope": scope,
        "root_channel_json": str(ROOT_CHANNEL_JSON),
        "mystery_channel_json": str(MYSTERY_CHANNEL_JSON),
        "root_channel_id": root_payload["channel_id"],
        "root_step_count": len(root_payload["steps"]),
        "mystery_channel_id": mystery_payload["channel_id"],
        "mystery_step_count": len(mystery_payload["steps"]),
        "mystery_backup_files": mystery_payload["backup_files"],
    }
    if args.mode == "apply":
        _write_json(ROOT_CHANNEL_JSON, root_payload)
        _write_json(MYSTERY_CHANNEL_JSON, mystery_payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
