from __future__ import annotations

import html
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from slugify import slugify

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "ja", "es")
LANGUAGE_SEQUENCE_INDEX: dict[str, int] = {"en": 0, "ja": 1, "es": 2}
LANGUAGE_PUBLISH_OFFSET_MINUTES: dict[str, int] = {"en": 0, "ja": 30, "es": 60}

BLOG_HOST_LANGUAGE_MAP: dict[str, str] = {
    "donggri-korea.blogspot.com": "en",
    "donggri-kankoku.blogspot.com": "ja",
    "donggri-corea.blogspot.com": "es",
}

BLOG_SLUG_LANGUAGE_HINTS: dict[str, str] = {
    "donggri-korea": "en",
    "donggri-kankoku": "ja",
    "donggri-corea": "es",
}

LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "ja": "\u65e5\u672c\u8a9e",
    "es": "Espa\u00f1ol",
}

LANGUAGE_SWITCH_HEADINGS: dict[str, str] = {
    "en": "Read this guide in other languages",
    "ja": "\u3053\u306e\u30ac\u30a4\u30c9\u3092\u4ed6\u8a00\u8a9e\u3067\u8aad\u3080",
    "es": "Lee esta gu\u00eda en otros idiomas",
}

CURRENT_LANGUAGE_SUFFIX: dict[str, str] = {
    "en": "(Current)",
    "ja": "(\u73fe\u5728\u30da\u30fc\u30b8)",
    "es": "(P\u00e1gina actual)",
}

DEFAULT_TARGET_AUDIENCE: dict[str, str] = {
    "en": "US-first Korea travelers with UK/EU planning needs mixed in",
    "ja": "20\u301c40\u4ee3\u306e\u500b\u4eba\u65c5\u884c\u8005\u5411\u3051\uff08\u52d5\u7dda\u3001\u6df7\u96d1\u56de\u907f\u3001\u4e88\u7b97\u91cd\u8996\uff09",
    "es": "Viajeros hispanohablantes globales que priorizan claridad, costos y decisiones pr\u00e1cticas",
}


@dataclass(frozen=True, slots=True)
class BundleContext:
    bundle_key: str
    facts: list[str]
    prohibited_claims: list[str]
    notes: str
    raw: str


def _normalize_language(value: str | None) -> str | None:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return None
    if lowered in SUPPORTED_LANGUAGES:
        return lowered
    if lowered.startswith("en"):
        return "en"
    if lowered.startswith("ja"):
        return "ja"
    if lowered.startswith("es"):
        return "es"
    return None


def _extract_host(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    return parsed.netloc.strip().lower()


def _contains_hint(text: str, hint: str) -> bool:
    return hint in text.casefold()


def resolve_blog_bundle_language(blog) -> str | None:
    host = _extract_host(getattr(blog, "blogger_url", None))
    if host in BLOG_HOST_LANGUAGE_MAP:
        return BLOG_HOST_LANGUAGE_MAP[host]

    slug = str(getattr(blog, "slug", "") or "").strip().lower()
    if slug:
        for hint, language in BLOG_SLUG_LANGUAGE_HINTS.items():
            if _contains_hint(slug, hint):
                return language

    name = str(getattr(blog, "name", "") or "").strip().lower()
    if name:
        for hint, language in BLOG_SLUG_LANGUAGE_HINTS.items():
            if _contains_hint(name, hint):
                return language

    return _normalize_language(getattr(blog, "primary_language", None))


def default_target_audience_for_language(language: str | None) -> str:
    normalized = _normalize_language(language)
    if not normalized:
        return ""
    return DEFAULT_TARGET_AUDIENCE.get(normalized, "")


def bundle_publish_offset_minutes(language: str | None) -> int:
    normalized = _normalize_language(language)
    if not normalized:
        return 0
    return LANGUAGE_PUBLISH_OFFSET_MINUTES.get(normalized, 0)


def language_sequence_index(language: str | None) -> int:
    normalized = _normalize_language(language)
    if not normalized:
        return 999
    return LANGUAGE_SEQUENCE_INDEX.get(normalized, 999)


def normalize_bundle_key(raw_value: str | None) -> str:
    normalized = slugify(str(raw_value or "").strip())
    return normalized[:80] if normalized else ""


def _split_list_value(raw_value: str | list[str] | None) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        values = [str(item).strip() for item in raw_value]
    else:
        text = str(raw_value).replace("\r", "\n")
        values = []
        for chunk in text.replace("|", "\n").replace(";", "\n").split("\n"):
            for sub_chunk in chunk.split(","):
                value = sub_chunk.strip()
                if value:
                    values.append(value)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def parse_planner_bundle_context(raw_text: str | None) -> BundleContext:
    raw = str(raw_text or "").strip()
    if not raw:
        return BundleContext(bundle_key="", facts=[], prohibited_claims=[], notes="", raw="")

    json_payload: dict | None = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            json_payload = parsed
    except Exception:  # noqa: BLE001
        json_payload = None

    bundle_key = ""
    facts: list[str] = []
    prohibited_claims: list[str] = []
    note_lines: list[str] = []

    if json_payload is not None:
        bundle_key = normalize_bundle_key(
            str(
                json_payload.get("bundle_key")
                or json_payload.get("bundle")
                or json_payload.get("bundleKey")
                or ""
            )
        )
        facts = _split_list_value(json_payload.get("facts"))
        prohibited_claims = _split_list_value(
            json_payload.get("prohibited_claims")
            or json_payload.get("forbidden_claims")
            or json_payload.get("prohibitedClaims")
        )
        notes = str(json_payload.get("notes") or "").strip()
        if notes:
            note_lines.append(notes)
    else:
        for raw_line in raw.replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                note_lines.append(line)
                continue
            key, value = line.split(":", maxsplit=1)
            key_normalized = key.strip().casefold().replace(" ", "_")
            value_text = value.strip()
            if key_normalized in {"bundle_key", "bundle", "bundlekey"}:
                bundle_key = normalize_bundle_key(value_text)
                continue
            if key_normalized in {"facts", "fact", "confirmed_facts"}:
                facts.extend(_split_list_value(value_text))
                continue
            if key_normalized in {
                "prohibited_claims",
                "forbidden_claims",
                "prohibited",
                "forbidden",
                "dont_claim",
                "do_not_claim",
            }:
                prohibited_claims.extend(_split_list_value(value_text))
                continue
            note_lines.append(line)

        facts = _split_list_value(facts)
        prohibited_claims = _split_list_value(prohibited_claims)

    return BundleContext(
        bundle_key=bundle_key,
        facts=facts,
        prohibited_claims=prohibited_claims,
        notes="\n".join(note_lines).strip(),
        raw=raw,
    )


def build_language_switch_block(*, current_language: str, urls_by_language: dict[str, str]) -> str:
    normalized_current = _normalize_language(current_language)
    if not normalized_current:
        return ""

    ordered_languages = [lang for lang in SUPPORTED_LANGUAGES if urls_by_language.get(lang)]
    if len(ordered_languages) < 2:
        return ""

    heading = LANGUAGE_SWITCH_HEADINGS.get(normalized_current, LANGUAGE_SWITCH_HEADINGS["en"])
    current_suffix = CURRENT_LANGUAGE_SUFFIX.get(normalized_current, CURRENT_LANGUAGE_SUFFIX["en"])

    list_items: list[str] = []
    for language in ordered_languages:
        url = str(urls_by_language.get(language) or "").strip()
        if not url:
            continue
        language_label = LANGUAGE_LABELS.get(language, language.upper())
        escaped_url = html.escape(url, quote=True)
        escaped_label = html.escape(language_label, quote=True)
        if language == normalized_current:
            list_items.append(
                "<li style='margin:0 0 8px;'>"
                f"<strong>{escaped_label} {html.escape(current_suffix)}</strong>"
                "</li>"
            )
            continue
        list_items.append(
            "<li style='margin:0 0 8px;'>"
            f"<a href=\"{escaped_url}\" target=\"_blank\" rel=\"noopener\">{escaped_label}</a>"
            "</li>"
        )

    if not list_items:
        return ""

    return (
        "<section style='margin-top:30px;padding:18px 20px;border:1px solid #e2e8f0;border-radius:18px;background:#f8fafc;'>"
        f"<h2 style='margin:0 0 12px;font-size:22px;line-height:1.35;color:#0f172a;'>{html.escape(heading)}</h2>"
        "<ul style='margin:0;padding-left:20px;color:#1e293b;font-size:16px;line-height:1.75;'>"
        + "".join(list_items)
        + "</ul></section>"
    )
