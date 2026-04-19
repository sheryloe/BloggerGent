from __future__ import annotations

from app.services.content.publish_trust_gate_service import (
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

    assert assessment["passed"] is True
    assert assessment["reasons"] == []


def test_enforce_publish_trust_requirements_is_noop() -> None:
    content = """
    <h2>As of 2026-04-05</h2>
    <h2>Confirmed Facts</h2>
    <p>Fact block only.</p>
    """

    result = enforce_publish_trust_requirements(content, context="unit-test")
    assert result["passed"] is True
