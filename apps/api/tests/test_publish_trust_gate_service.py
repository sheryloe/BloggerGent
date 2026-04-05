from __future__ import annotations

import pytest

from app.services.publish_trust_gate_service import (
    MISSING_AS_OF_REASON,
    MISSING_SOURCES_REASON,
    enforce_publish_trust_requirements,
    assess_publish_trust_requirements,
)


def test_assess_publish_trust_requirements_passes_with_required_sections() -> None:
    content = """
    <h2>As of 2026-04-05</h2>
    <h2>Confirmed Facts</h2>
    <p>Official city website confirms transport updates.</p>
    <h2>Unverified Details</h2>
    <p>Unofficial crowd estimates may change.</p>
    <h2>Sources</h2>
    <p>https://example.com/official-notice</p>
    """

    assessment = assess_publish_trust_requirements(content)

    assert assessment["passed"] is True
    assert assessment["reasons"] == []


def test_assess_publish_trust_requirements_reports_missing_fields() -> None:
    content = """
    <h2>Confirmed Facts</h2>
    <p>Fact block.</p>
    <h2>Unverified Details</h2>
    <p>Unverified block.</p>
    """

    assessment = assess_publish_trust_requirements(content)

    assert assessment["passed"] is False
    assert MISSING_AS_OF_REASON in assessment["reasons"]
    assert MISSING_SOURCES_REASON in assessment["reasons"]


def test_enforce_publish_trust_requirements_raises_with_reason_codes() -> None:
    content = """
    <h2>As of 2026-04-05</h2>
    <h2>Confirmed Facts</h2>
    <p>Fact block only.</p>
    """

    with pytest.raises(ValueError) as exc_info:
        enforce_publish_trust_requirements(content, context="unit-test")

    error_text = str(exc_info.value)
    assert "unit-test_trust_gate_failed" in error_text
    assert MISSING_SOURCES_REASON in error_text
