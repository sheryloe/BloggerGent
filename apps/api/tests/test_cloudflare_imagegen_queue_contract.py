from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cloudflare" / "prepare_codex_imagegen_recovery.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prepare_codex_imagegen_recovery", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_imagegen_policy_roles_are_category_specific() -> None:
    module = _load_module()

    assert module.roles_for("개발과-프로그래밍") == ("hero",)
    assert module.roles_for("문화와-공간") == ("hero", "inline_1", "inline_2")
    assert module.roles_for("축제와-현장") == ("hero", "inline_1", "inline_2")
    assert module.roles_for("나스닥의-흐름") == ("hero",)
    assert module.policy_for("나스닥의-흐름")["layout_policy"] == "hero_only_nasdaq_infographic"


def test_imagegen_queue_fields_include_role_status_and_policy_snapshot() -> None:
    module = _load_module()
    row = {
        "remote_post_id": "post-1",
        "category_slug": "문화와-공간",
        "slug": "sample-culture-post",
        "title": "문화 공간 샘플",
        "thumbnail_url": "",
        "reasons": "fallback_placeholder",
        "article_pattern_id": "info-deep-dive",
    }

    snapshot = module.policy_snapshot_for(row, image_role="inline_1")
    payload = module.build_prompt_payload(row, image_role="inline_1")

    assert snapshot["image_role"] == "inline_1"
    assert snapshot["slot_index"] == 1
    assert snapshot["live_apply_status_default"] == "blocked"
    assert snapshot["allowed_roles"] == ["hero", "inline_1", "inline_2"]
    assert payload["article_pattern_id"] == "info-deep-dive"
    json.dumps(snapshot, ensure_ascii=False)
    json.dumps(payload, ensure_ascii=False)


def test_imagegen_r2_key_uses_role_specific_filename() -> None:
    module = _load_module()
    row = {
        "category_slug": "문화와-공간",
        "slug": "sample-culture-post",
        "thumbnail_url": "",
    }

    assert module.r2_key_for(row, image_role="hero").endswith(
        "/sample-culture-post/sample-culture-post.webp"
    )
    assert module.r2_key_for(row, image_role="inline_2").endswith(
        "/sample-culture-post/sample-culture-post-inline-2.webp"
    )
