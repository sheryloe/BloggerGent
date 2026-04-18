from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.db.base import Base
from app.models.entities import ManagedChannel
from app.services.cloudflare import cloudflare_asset_bootstrap_service as bootstrap_service
from app.services.cloudflare.cloudflare_asset_policy import ensure_cloudflare_channel_metadata
from app.services.integrations import storage_service


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


def _create_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    session._engine = engine  # type: ignore[attr-defined]
    return session


def _close_db(session: Session) -> None:
    engine = session._engine  # type: ignore[attr-defined]
    session.close()
    engine.dispose()


def test_bootstrap_cloudflare_assets_creates_missing_categories_and_backfills_metadata(tmp_path: Path, monkeypatch) -> None:
    db = _create_db()
    try:
        local_root = tmp_path / "storage" / "images" / "Cloudflare"
        existing_slugs = ensure_cloudflare_channel_metadata({})["allowed_category_slugs"][:8]
        for slug in existing_slugs:
            (local_root / slug).mkdir(parents=True, exist_ok=True)

        channel = ManagedChannel(
            provider="cloudflare",
            channel_id="cloudflare:dongriarchive",
            display_name="Dongri Archive",
            status="active",
            channel_metadata={"api_base_url": "https://api.dongriarchive.com", "token_configured": True, "local_asset_root": str(local_root)},
            is_enabled=True,
        )
        db.add(channel)
        db.commit()

        monkeypatch.setattr(bootstrap_service, "ensure_managed_channels", lambda _db: [channel])
        monkeypatch.setattr(
            bootstrap_service,
            "ensure_cloudflare_r2_bucket",
            lambda *_args, **_kwargs: {
                "bucket_name": "dongriarchive-cloudflare",
                "bucket_created": True,
                "bucket_verified": True,
                "sample_uploaded_keys": ["assets/media/cloudflare/dongri-archive/bootstrap/probe.webp"],
            },
        )

        result = bootstrap_service.bootstrap_cloudflare_assets(
            db,
            bucket_name="dongriarchive-cloudflare",
            create_missing_categories=True,
            backfill_channel_metadata=True,
            verify_bucket=True,
        )

        db.refresh(channel)
        metadata = dict(channel.channel_metadata or {})
        assert result["bucket_name"] == "dongriarchive-cloudflare"
        assert result["bucket_created"] is True
        assert result["bucket_verified"] is True
        assert len(result["created_categories"]) == 4
        assert metadata["hero_only"] is True
        assert len(metadata["allowed_category_slugs"]) == 12
        assert (local_root / "_manifests").exists()
        for slug in metadata["allowed_category_slugs"]:
            assert (local_root / slug).exists()
        assert Path(result["report_path"]).exists()
        assert Path(result["csv_path"]).exists()
    finally:
        _close_db(db)


def test_ensure_cloudflare_r2_bucket_creates_and_verifies(monkeypatch) -> None:
    db = _create_db()
    try:
        monkeypatch.setattr(
            storage_service,
            "get_settings_map",
            lambda _db: {
                "cloudflare_account_id": "acct-123",
                "cloudflare_r2_bucket": "ignored-default",
                "cloudflare_r2_access_key_id": "access-key",
                "cloudflare_r2_secret_access_key": "secret-key",
                "cloudflare_r2_public_base_url": "https://api.dongriarchive.com",
                "cloudflare_r2_prefix": "assets",
            },
        )

        bucket_calls: list[str] = []
        object_calls: list[str] = []

        def _fake_request(method: str, url: str, **_kwargs):
            bucket_calls.append(f"{method.upper()} {url}")
            if method.upper() == "HEAD":
                return _FakeResponse(404)
            if method.upper() == "PUT":
                return _FakeResponse(200)
            raise AssertionError(f"unexpected bucket method: {method}")

        def _fake_put(url: str, **_kwargs):
            object_calls.append(f"PUT {url}")
            return _FakeResponse(200)

        def _fake_head(url: str, **_kwargs):
            object_calls.append(f"HEAD {url}")
            return _FakeResponse(200, headers={"Content-Length": "68"})

        def _fake_delete(url: str, **_kwargs):
            object_calls.append(f"DELETE {url}")
            return _FakeResponse(204)

        monkeypatch.setattr(storage_service.httpx, "request", _fake_request)
        monkeypatch.setattr(storage_service.httpx, "put", _fake_put)
        monkeypatch.setattr(storage_service.httpx, "head", _fake_head)
        monkeypatch.setattr(storage_service.httpx, "delete", _fake_delete)

        result = storage_service.ensure_cloudflare_r2_bucket(
            db,
            bucket_name="dongriarchive-cloudflare",
            verify=True,
            create_if_missing=True,
        )

        assert result["bucket_name"] == "dongriarchive-cloudflare"
        assert result["bucket_created"] is True
        assert result["bucket_verified"] is True
        assert len(result["sample_uploaded_keys"]) == 1
        assert result["sample_uploaded_keys"][0].endswith(".webp")
        assert any("HEAD https://acct-123.r2.cloudflarestorage.com/dongriarchive-cloudflare" == item for item in bucket_calls)
        assert any("PUT https://acct-123.r2.cloudflarestorage.com/dongriarchive-cloudflare" == item for item in bucket_calls)
        assert len(object_calls) == 3
    finally:
        _close_db(db)


def test_ensure_cloudflare_r2_bucket_verifies_existing_bucket_without_root_probe(monkeypatch) -> None:
    db = _create_db()
    try:
        monkeypatch.setattr(
            storage_service,
            "get_settings_map",
            lambda _db: {
                "cloudflare_account_id": "acct-123",
                "cloudflare_r2_bucket": "ignored-default",
                "cloudflare_r2_access_key_id": "access-key",
                "cloudflare_r2_secret_access_key": "secret-key",
                "cloudflare_r2_public_base_url": "https://api.dongriarchive.com",
                "cloudflare_r2_prefix": "assets",
            },
        )

        bucket_calls: list[str] = []
        object_calls: list[str] = []

        def _fake_request(method: str, url: str, **_kwargs):
            bucket_calls.append(f"{method.upper()} {url}")
            return _FakeResponse(200)

        def _fake_put(url: str, **_kwargs):
            object_calls.append(f"PUT {url}")
            return _FakeResponse(200)

        def _fake_head(url: str, **_kwargs):
            object_calls.append(f"HEAD {url}")
            return _FakeResponse(200, headers={"Content-Length": "68"})

        def _fake_delete(url: str, **_kwargs):
            object_calls.append(f"DELETE {url}")
            return _FakeResponse(204)

        monkeypatch.setattr(storage_service.httpx, "request", _fake_request)
        monkeypatch.setattr(storage_service.httpx, "put", _fake_put)
        monkeypatch.setattr(storage_service.httpx, "head", _fake_head)
        monkeypatch.setattr(storage_service.httpx, "delete", _fake_delete)

        result = storage_service.ensure_cloudflare_r2_bucket(
            db,
            bucket_name="dongriarchive-cloudflare",
            verify=True,
            create_if_missing=False,
        )

        assert result["bucket_name"] == "dongriarchive-cloudflare"
        assert result["bucket_created"] is False
        assert result["bucket_verified"] is True
        assert bucket_calls == []
        assert len(object_calls) == 3
    finally:
        _close_db(db)
