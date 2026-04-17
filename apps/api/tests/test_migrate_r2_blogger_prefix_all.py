from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    root = Path(__file__).resolve().parents[3]
    script_path = root / "scripts" / "migrate_r2_blogger_prefix_all.py"
    spec = importlib.util.spec_from_file_location("migrate_r2_blogger_prefix_all", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_map_target_key_rewrites_prefix():
    mod = _load_module()
    source = "assets/media/blogger/korea-travel/travel/2026/04/a.webp"
    assert (
        mod.map_target_key(source, "assets/media/blogger/", "assets/media/google-blogger/")
        == "assets/media/google-blogger/korea-travel/travel/2026/04/a.webp"
    )


def test_process_one_key_skip_existing():
    mod = _load_module()
    result = mod.process_one_key(
        execute=True,
        source_key="assets/media/blogger/x.webp",
        target_key="assets/media/google-blogger/x.webp",
        exists_fn=lambda key: True,
        download_fn=lambda key: b"never",
        upload_fn=lambda key, payload: None,
    )
    assert result.status == "skipped_existing"


def test_process_one_key_failed_when_source_missing():
    mod = _load_module()

    def _missing(_key: str) -> bytes:
        raise FileNotFoundError("source missing")

    result = mod.process_one_key(
        execute=True,
        source_key="assets/media/blogger/x.webp",
        target_key="assets/media/google-blogger/x.webp",
        exists_fn=lambda key: False,
        download_fn=_missing,
        upload_fn=lambda key, payload: None,
    )
    assert result.status == "failed"
    assert "download_source_failed" in result.error


def test_process_one_key_failed_when_head_after_upload_false():
    mod = _load_module()
    calls: list[str] = []

    def _exists(_key: str) -> bool:
        calls.append("exists")
        return False

    result = mod.process_one_key(
        execute=True,
        source_key="assets/media/blogger/x.webp",
        target_key="assets/media/google-blogger/x.webp",
        exists_fn=_exists,
        download_fn=lambda key: b"abc",
        upload_fn=lambda key, payload: calls.append("upload"),
    )
    assert result.status == "failed"
    assert result.error == "head_target_false_after_upload"
    assert calls.count("upload") == 1
