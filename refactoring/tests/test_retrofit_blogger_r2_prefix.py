from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    root = Path(__file__).resolve().parents[2]
    script_path = root / "refactoring" / "scripts" / "retrofit_blogger_r2_prefix.py"
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "apps" / "api"))
    spec = importlib.util.spec_from_file_location("retrofit_blogger_r2_prefix", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_legacy_url_to_canonical():
    mod = _load_module()
    old = "https://api.dongriarchive.com/assets/assets/media/blogger/korea-travel/travel/2026/04/a/b.webp"
    new = mod.normalize_legacy_url_to_canonical(old)
    assert new == "https://api.dongriarchive.com/assets/media/google-blogger/korea-travel/travel/2026/04/a/b.webp"


def test_canonical_key_from_legacy_key():
    mod = _load_module()
    key = "assets/assets/media/blogger/korea-travel/travel/2026/04/a/b.webp"
    assert (
        mod.canonical_key_from_legacy_key(key)
        == "assets/media/google-blogger/korea-travel/travel/2026/04/a/b.webp"
    )


def test_legacy_key_candidates_from_url():
    mod = _load_module()
    url = "https://api.dongriarchive.com/assets/assets/assets/media/blogger/world-mystery/mystery/2026/04/x/y.webp"
    candidates = mod.legacy_key_candidates_from_url(url)
    assert "assets/assets/assets/media/blogger/world-mystery/mystery/2026/04/x/y.webp" in candidates
    assert "assets/media/blogger/world-mystery/mystery/2026/04/x/y.webp" in candidates
