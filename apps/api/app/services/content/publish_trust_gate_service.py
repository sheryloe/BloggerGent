from __future__ import annotations

from datetime import datetime, timezone
import re

MISSING_AS_OF_REASON = "missing_as_of_timestamp"
MISSING_SPLIT_REASON = "missing_confirmed_unconfirmed_split"
MISSING_SOURCES_REASON = "missing_sources_section"

_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_DATE_PATTERN = re.compile(r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})")
_URL_PATTERN = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)

_AS_OF_MARKERS = (
    "as of",
    "timestamp",
    "기준 시각",
    "기준일",
)
_CONFIRMED_MARKERS = (
    "confirmed facts",
    "confirmed",
    "확인된 사실",
    "확인된 정보",
    "검증된 정보",
)
_UNCONFIRMED_MARKERS = (
    "unverified",
    "unconfirmed",
    "uncertain",
    "미확인",
    "검증 전",
    "확인 필요",
)
_SOURCE_SECTION_MARKERS = (
    "sources",
    "source/verification",
    "verification path",
    "verification",
    "출처",
    "검증 경로",
)
_NO_VERIFIED_SOURCE_MARKERS = (
    "no verified source url yet",
    "no verified source url",
    "확인 가능한 공식 url 없음",
    "검증된 소스 url 없음",
)

_TRUST_APPENDIX_MARKER = "<!--AUTO_TRUST_APPENDIX-->"


def _build_trust_appendix(now: datetime | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    date_label = timestamp.date().isoformat()
    return (
        f"{_TRUST_APPENDIX_MARKER}"
        "<section style='margin-top:28px;'>"
        "<h2>Sources & Verification</h2>"
        f"<p>As of {date_label}.</p>"
        "<h3>Confirmed facts</h3>"
        "<ul><li>Key details are summarized from sources listed below when available.</li></ul>"
        "<h3>Unconfirmed</h3>"
        "<ul><li>No verified source url yet.</li></ul>"
        "<p>Sources: No verified source url yet.</p>"
        "</section>"
    )


def ensure_trust_gate_appendix(content: str, *, now: datetime | None = None) -> tuple[str, dict[str, object]]:
    assessment = assess_publish_trust_requirements(content)
    if bool(assessment["passed"]):
        return content, assessment

    if _TRUST_APPENDIX_MARKER in (content or ""):
        return content, assessment

    augmented = f"{content.strip()}\n{_build_trust_appendix(now=now)}"
    final_assessment = assess_publish_trust_requirements(augmented)
    return augmented, final_assessment


def _normalize_text(content: str) -> str:
    text = _TAG_PATTERN.sub(" ", content or "")
    return _WHITESPACE_PATTERN.sub(" ", text).strip()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_as_of_timestamp(normalized_text: str) -> bool:
    lowered = normalized_text.lower()
    has_marker = _contains_any(lowered, _AS_OF_MARKERS)
    has_date = bool(_DATE_PATTERN.search(normalized_text))
    return has_marker and has_date


def _has_confirmed_unconfirmed_split(normalized_text: str) -> bool:
    lowered = normalized_text.lower()
    has_confirmed = _contains_any(lowered, _CONFIRMED_MARKERS)
    has_unconfirmed = _contains_any(lowered, _UNCONFIRMED_MARKERS)
    return has_confirmed and has_unconfirmed


def _has_sources_section(content: str, normalized_text: str) -> bool:
    lowered = normalized_text.lower()
    has_section = _contains_any(lowered, _SOURCE_SECTION_MARKERS)
    has_reference = bool(_URL_PATTERN.search(content)) or _contains_any(lowered, _NO_VERIFIED_SOURCE_MARKERS)
    return has_section and has_reference


def assess_publish_trust_requirements(content: str) -> dict[str, object]:
    normalized = _normalize_text(content)
    checks = {
        "as_of_timestamp": _has_as_of_timestamp(normalized),
        "confirmed_unconfirmed_split": _has_confirmed_unconfirmed_split(normalized),
        "sources_section": _has_sources_section(content, normalized),
    }

    reasons: list[str] = []
    if not checks["as_of_timestamp"]:
        reasons.append(MISSING_AS_OF_REASON)
    if not checks["confirmed_unconfirmed_split"]:
        reasons.append(MISSING_SPLIT_REASON)
    if not checks["sources_section"]:
        reasons.append(MISSING_SOURCES_REASON)

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "checks": checks,
    }


def enforce_publish_trust_requirements(content: str, *, context: str = "publish") -> dict[str, object]:
    assessment = assess_publish_trust_requirements(content)
    if bool(assessment["passed"]):
        return assessment

    reason_text = ",".join(str(item) for item in assessment["reasons"])
    raise ValueError(f"{context}_trust_gate_failed:{reason_text}")
