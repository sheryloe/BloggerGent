from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from scripts.curate_mystery_unique_images import (
    CandidateEdge,
    _assign_unique_hashes,
    _archive_root,
    _canonical_image_root,
    _discover_file_records,
    _override_manifest_path,
    _final_manifest_path,
    _match_alias_to_slug,
    _mystery_local_root,
    _review_manifest_path,
    _run_apply,
    _run_cleanup,
)


def _edge(*, slug: str, sha256: str, kind: str, score: int, relative_path: str) -> CandidateEdge:
    return CandidateEdge(
        slug=slug,
        sha256=sha256,
        match_kind=kind,
        score=score,
        path=Path(f"/tmp/{Path(relative_path).name}"),
        relative_path=relative_path,
        source_rank=0,
        ext_rank=0,
        size_bytes=100,
        alias=Path(relative_path).stem,
    )


def test_match_alias_to_slug_prioritizes_exact_prefix_and_token() -> None:
    assert _match_alias_to_slug("db-cooper-mystery-evidence-review-what", "db-cooper-mystery-evidence-review-what") == (
        "exact",
        100,
    )
    assert _match_alias_to_slug("the-oakville-blobs-incident-eyewitness-20260417010101", "the-oakville-blobs-incident-eyewitness") == (
        "prefix",
        95,
    )
    token_match = _match_alias_to_slug(
        "lead-masks-case-brazil-unsolved-deaths-messages",
        "the-lead-masks-case-brazils-unsolved",
    )
    assert token_match is not None
    assert token_match[0] == "token"
    assert token_match[1] < 90


def test_assign_unique_hashes_reassigns_to_preserve_one_to_one() -> None:
    slug_to_edges = {
        "alpha-case": [
            _edge(
                slug="alpha-case",
                sha256="shared",
                kind="exact",
                score=100,
                relative_path="images/mystery/alpha-case.webp",
            ),
            _edge(
                slug="alpha-case",
                sha256="alpha-alt",
                kind="prefix",
                score=95,
                relative_path="images/mystery/alpha-case-20260401.webp",
            ),
        ],
        "beta-case": [
            _edge(
                slug="beta-case",
                sha256="shared",
                kind="exact",
                score=100,
                relative_path="images/mystery/beta-case.webp",
            ),
        ],
    }
    assigned = _assign_unique_hashes(["alpha-case", "beta-case"], slug_to_edges)
    assert set(assigned) == {"alpha-case", "beta-case"}
    assert assigned["beta-case"].sha256 == "shared"
    assert assigned["alpha-case"].sha256 == "alpha-alt"


def test_discover_file_records_prioritizes_mapped_extra_source(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    extra_root = tmp_path / "app" / "storage" / "images"
    mystery_root = storage_root / "images" / "mystery"
    mystery_root.mkdir(parents=True, exist_ok=True)
    extra_root.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (8, 8), (10, 10, 10)).save(mystery_root / "the-beast-of-gevaudan-unraveling.webp", format="WEBP")
    Image.new("RGB", (8, 8), (20, 20, 20)).save(extra_root / "beast-gevaudan-18th-century-france-mystery.webp", format="WEBP")
    Image.new("RGB", (8, 8), (30, 30, 30)).save(extra_root / "cover-a3fef6ae4d91.webp", format="WEBP")

    records, unmapped = _discover_file_records(storage_root, [extra_root])
    extra_records = [
        record
        for record in records
        if record.relative_path.endswith("beast-gevaudan-18th-century-france-mystery.webp")
    ]

    assert extra_records
    assert extra_records[0].source_rank == -2
    assert "the-beast-of-gevaudan-unraveling" in extra_records[0].aliases
    assert len(unmapped) == 1
    assert unmapped[0]["relative_to_extra_root"] == "cover-a3fef6ae4d91.webp"


def test_run_cleanup_preserves_archive_canonical_files(tmp_path: Path) -> None:
    storage_root = tmp_path
    mystery_root = _mystery_local_root(storage_root)
    archive_root = _archive_root(storage_root)
    canonical_file = _canonical_image_root(storage_root) / "alpha-case" / "alpha-case.webp"
    mystery_keep = mystery_root / "alpha-case.webp"
    mystery_delete = mystery_root / "alpha-case-20260401.png"

    canonical_file.parent.mkdir(parents=True, exist_ok=True)
    mystery_keep.parent.mkdir(parents=True, exist_ok=True)
    mystery_delete.parent.mkdir(parents=True, exist_ok=True)
    canonical_file.write_bytes(b"canonical")
    mystery_keep.write_bytes(b"keep")
    mystery_delete.write_bytes(b"delete")

    final_payload = {
        "items": [
            {
                "slug": "alpha-case",
                "status": "applied",
            }
        ],
        "candidate_file_paths": [
            {"path": "images/mystery/alpha-case.webp"},
            {"path": "images/mystery/alpha-case-20260401.png"},
            {"path": "the-midnight-archives/images/slug-canonical/alpha-case/alpha-case.webp"},
        ],
    }
    _final_manifest_path(storage_root).parent.mkdir(parents=True, exist_ok=True)
    _final_manifest_path(storage_root).write_text(json.dumps(final_payload), encoding="utf-8")

    summary = _run_cleanup(
        argparse.Namespace(blog_id=35, storage_root=str(storage_root), extra_source_root=[], cleanup_extra_source=False)
    )

    assert summary["summary"]["deleted_candidate_files"] == 1
    assert mystery_keep.exists()
    assert not mystery_delete.exists()
    assert canonical_file.exists()
    assert archive_root.exists()


def test_run_cleanup_archives_extra_source_before_delete(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    extra_root = tmp_path / "app" / "storage" / "images"
    extra_file = extra_root / "beast-gevaudan-18th-century-france-mystery.webp"
    extra_file.parent.mkdir(parents=True, exist_ok=True)
    extra_file.write_bytes(b"extra")
    keep = _mystery_local_root(storage_root) / "alpha-case.webp"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_bytes(b"keep")

    final_payload = {
        "items": [{"slug": "alpha-case", "status": "applied"}],
        "candidate_file_paths": [{"path": str(extra_file)}],
    }
    _final_manifest_path(storage_root).parent.mkdir(parents=True, exist_ok=True)
    _final_manifest_path(storage_root).write_text(json.dumps(final_payload), encoding="utf-8")

    summary = _run_cleanup(
        argparse.Namespace(
            blog_id=35,
            storage_root=str(storage_root),
            extra_source_root=[str(extra_root)],
            cleanup_extra_source=True,
        )
    )

    imported = storage_root / "the-midnight-archives" / "images" / "app-storage-imported" / extra_file.name
    assert summary["summary"]["archived_extra_source_files"] == 1
    assert summary["summary"]["deleted_extra_source_files"] == 1
    assert imported.exists()
    assert not extra_file.exists()


def test_run_apply_falls_back_to_curated_local_webp_when_selected_source_is_missing(tmp_path: Path, monkeypatch) -> None:
    storage_root = tmp_path
    mystery_root = _mystery_local_root(storage_root)
    mystery_root.mkdir(parents=True, exist_ok=True)
    local_webp = mystery_root / "alpha-case.webp"

    image = Image.new("RGB", (8, 8), (20, 20, 20))
    image.save(local_webp, format="WEBP", quality=86)

    review_payload = {
        "selections": [
            {
                "slug": "alpha-case",
                "status": "auto_confirmed",
                "selected_sha256": "unused",
                "selected_path": "images/mystery/alpha-case-20260401.png",
                "canonical_object_key": "assets/the-midnight-archives/mystery/2026/04/alpha-case/alpha-case.webp",
            }
        ]
    }
    _review_manifest_path(storage_root).parent.mkdir(parents=True, exist_ok=True)
    _review_manifest_path(storage_root).write_text(json.dumps(review_payload), encoding="utf-8")
    _override_manifest_path(storage_root).parent.mkdir(parents=True, exist_ok=True)
    _override_manifest_path(storage_root).write_text(json.dumps({"choices": {}}), encoding="utf-8")

    monkeypatch.setattr(
        "scripts.curate_mystery_unique_images.SessionLocal",
        lambda: _DummySession(),
    )
    monkeypatch.setattr(
        "scripts.curate_mystery_unique_images.get_settings_map",
        lambda db: {},
    )
    monkeypatch.setattr(
        "scripts.curate_mystery_unique_images._load_review_context",
        lambda db, *, blog_id: (_DummyBlog(), {}, {}, {}),
    )
    monkeypatch.setattr(
        "scripts.curate_mystery_unique_images.upload_binary_to_cloudflare_r2",
        lambda db, object_key, filename, content: ("https://example.com/test.webp", {}, {"bucket": "mysteryarchive"}),
    )

    result = _run_apply(
        argparse.Namespace(blog_id=35, storage_root=str(storage_root), extra_source_root=[], cleanup_extra_source=False)
    )

    assert result["summary"]["applied_posts"] == 1
    assert (_canonical_image_root(storage_root) / "alpha-case" / "alpha-case.webp").exists()


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None

    def add(self, _):
        return None


class _DummyBlog:
    profile_key = "world_mystery"
