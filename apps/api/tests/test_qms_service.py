from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.entities import AnalyticsArticleFact, Blog, GoogleIndexUrlState, PublishMode
from app.services.qms import qms_service


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = SessionLocal()
    session._test_engine = engine  # type: ignore[attr-defined]
    return session


def _close(session: Session) -> None:
    engine = session._test_engine  # type: ignore[attr-defined]
    session.close()
    engine.dispose()


def _blog(db: Session) -> Blog:
    blog = Blog(
        id=1,
        name="QMS Blog",
        slug="qms-blog",
        content_category="test",
        primary_language="ko",
        profile_key="test",
        publish_mode=PublishMode.DRAFT,
        is_active=True,
    )
    db.add(blog)
    db.commit()
    return blog


def test_compute_current_kpi_counts_published_quality_coverage() -> None:
    db = _session()
    try:
        _blog(db)
        db.add_all(
            [
                AnalyticsArticleFact(
                    blog_id=1,
                    month="2026-04",
                    title="Indexed post",
                    status="published",
                    actual_url="https://example.com/a",
                    source_type="generated",
                    seo_score=80,
                    geo_score=70,
                    lighthouse_score=90,
                ),
                AnalyticsArticleFact(
                    blog_id=1,
                    month="2026-04",
                    title="Live post",
                    status="live",
                    actual_url="https://example.com/b",
                    source_type="generated",
                    seo_score=None,
                    geo_score=65,
                    lighthouse_score=None,
                ),
            ]
        )
        db.add(GoogleIndexUrlState(blog_id=1, url="https://example.com/a", index_status="indexed"))
        db.commit()

        result = qms_service.compute_current_kpi(db)

        assert result["published_total"] == 2
        assert result["seo_scored_count"] == 1
        assert result["geo_scored_count"] == 2
        assert result["lighthouse_scored_count"] == 1
        assert result["indexed_count"] == 1
        assert result["unknown_index_count"] == 1
    finally:
        _close(db)


def test_runtime_scan_masks_env_values_and_captures_only_keys(tmp_path: Path, monkeypatch) -> None:
    db = _session()
    try:
        runtime_root = tmp_path / "runtime"
        env_file = runtime_root / "env" / "runtime.settings.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("OPENAI_API_KEY=secret-value\nPUBLIC_WEB_BASE_URL=http://localhost\n", encoding="utf-8")
        report_dir = runtime_root / "storage" / "reports"
        report_dir.mkdir(parents=True)
        (report_dir / "sample.json").write_text('{"status":"ok"}', encoding="utf-8")
        monkeypatch.setattr(qms_service, "RUNTIME_ROOT", runtime_root)
        monkeypatch.setattr(qms_service, "QMS_REPORT_DIR", runtime_root / "storage" / "reports" / "qms")
        monkeypatch.setattr(qms_service, "RUNTIME_SCAN_TARGETS", [env_file, report_dir])

        scan = qms_service.scan_runtime_evidence(db, max_files_per_root=20)

        assert scan.status == "completed"
        assert scan.file_count == 2
        assert scan.secrets_masked_count == 1
        evidence_payloads = [item.evidence_payload for item in qms_service.list_evidence(db)]
        env_payload = next(item for item in evidence_payloads if item.get("env_keys"))
        assert "OPENAI_API_KEY" in env_payload["env_keys"]
        assert "secret-value" not in str(evidence_payloads)
    finally:
        _close(db)
