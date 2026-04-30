from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup


REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
BLOGS = {
    "en": "https://donggri-korea.blogspot.com",
    "es": "https://donggri-corea.blogspot.com",
    "ja": "https://donggri-kankoku.blogspot.com",
}

SPACE_RE = re.compile(r"\s+")
NON_SPACE_RE = re.compile(r"\s+", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
FORBIDDEN_VISIBLE_TERMS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"\bSEO\b",
        r"\bGEO\b",
        r"\bCTR\b",
        r"\bLighthouse\b",
        r"\bPageSpeed\b",
        r"\barticle_pattern\b",
        r"\bpattern_key\b",
        r"\btravel-0[1-5]\b",
        r"\bhidden-path-route\b",
        r"\bcultural-insider\b",
        r"\blocal-flavor-guide\b",
        r"\bseasonal-secret\b",
        r"\bsmart-traveler-log\b",
    )
]

BROCHURE_PATTERNS = {
    "en": [
        r"\bmust-visit\b",
        r"\bultimate\b",
        r"\bvibrant\b",
        r"\bhidden gem\b",
        r"\bperfect for everyone\b",
    ],
    "es": [
        r"\bimprescindible\b",
        r"\bdefinitiv[ao]\b",
        r"\bvibrante\b",
        r"\bjoya escondida\b",
        r"\bperfect[ao] para todos\b",
    ],
    "ja": [
        "\u5b8c\u74a7",  # perfect
        "\u5fc5\u898b",  # must-see
        "\u7d76\u5bfe\u306b",  # absolutely
    ],
}

DECISION_PATTERNS = {
    "en": [
        r"\bskip\b",
        r"\bavoid\b",
        r"\breroute\b",
        r"\bbackup\b",
        r"\bnot worth\b",
        r"\bif you have little time\b",
        r"\bif you are short on time\b",
        r"\bqueue\b",
        r"\bcrowd\b",
        r"\breservation\b",
        r"\breturn route\b",
        r"\bsubway\b",
        r"\btaxi\b",
        r"\btransfer\b",
        r"\bstart\b",
    ],
    "es": [
        r"\bsi tienes poco tiempo\b",
        r"\byo lo har[ií]a as[ií]\b",
        r"\bno merece la pena\b",
        r"\bmejor\b",
        r"\bevitar?\b",
        r"\bcola\b",
        r"\bespera\b",
        r"\breserva\b",
        r"\bregreso\b",
        r"\bmetro\b",
        r"\btaxi\b",
        r"\bcambia el orden\b",
        r"\bprioridad\b",
    ],
    "ja": [
        "\u5148\u306b\u6c7a\u3081\u308b\u3053\u3068",  # decide first
        "\u907f\u3051\u308b\u3079\u304d\u52d5\u304d",  # moves to avoid
        "\u8ff7\u3063\u305f\u3089\u3053\u306e\u9806\u756a",  # if unsure, this order
        "\u6df7\u96d1",
        "\u5e30\u308a",
        "\u4e88\u7d04",
        "\u4e26\u3076",
        "\u56de\u907f",
        "\u30bf\u30af\u30b7\u30fc",
        "\u5730\u4e0b\u9244",
        "\u52d5\u7dda",
    ],
}

BLOG_VOICE_PATTERNS = {
    "en": [
        r"\bI would\b",
        r"\bI would not\b",
        r"\bI recommend\b",
        r"\bmy route\b",
        r"\bfor me\b",
        r"\bI would do\b",
    ],
    "es": [
        r"\byo lo har[ií]a\b",
        r"\bpara m[ií]\b",
        r"\bmi consejo\b",
        r"\bte recomiendo\b",
        r"\bsi fuera mi ruta\b",
        r"\bno lo har[ií]a\b",
    ],
    "ja": [
        "\u79c1\u306a\u3089",
        "\u500b\u4eba\u7684\u306b",
        "\u304a\u3059\u3059\u3081\u306f",
        "\u5148\u306b",
        "\u8ff7\u3063\u305f\u3089",
        "\u3084\u3081\u3066\u304a\u304f",
    ],
}

NOT_FOR_EVERYONE_PATTERNS = {
    "en": [r"\bnot for everyone\b", r"\bwho should skip\b", r"\bskip this\b", r"\bnot worth it if\b"],
    "es": [r"\bno es para todos\b", r"\bqui[eé]n deber[ií]a saltarse\b", r"\bno merece la pena si\b"],
    "ja": [
        "\u5411\u304b\u306a\u3044",
        "\u3084\u3081\u305f\u307b\u3046\u304c\u3044\u3044",
        "\u30b9\u30ad\u30c3\u30d7",
        "\u907f\u3051\u305f\u3044",
    ],
}


def _stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _clean_text(value: str | None) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def _plain_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _clean_text(clone.get_text(" ", strip=True))


def _non_space_len(text: str) -> int:
    return len(NON_SPACE_RE.sub("", text))


def _sitemap_urls(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(f"{base_url.rstrip('/')}/sitemap.xml")
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        url = (loc.text or "").strip()
        if not url:
            continue
        path = urlparse(url).path
        if re.search(r"/\d{4}/\d{2}/.+\.html$", path):
            urls.append(url)
    return sorted(set(urls))


def _count_matches(text: str, patterns: list[str]) -> int:
    total = 0
    for pattern in patterns:
        total += len(re.findall(pattern, text, flags=re.I))
    return total


def _repeated_sentence_count(text: str) -> int:
    sentences = [
        _clean_text(sentence)
        for sentence in SENTENCE_SPLIT_RE.split(text)
        if len(_clean_text(sentence)) >= 28
    ]
    counts = Counter(sentences)
    return sum(1 for count in counts.values() if count >= 3)


def _score_document(lang: str, url: str, html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article[data-bloggent-article='canonical']") or soup.select_one("article") or soup
    text = _plain_text(article)
    lower_text = text.lower()
    body_chars = _non_space_len(text)
    h2_count = len(article.find_all("h2"))
    h3_count = len(article.find_all("h3"))
    table_count = len(article.find_all("table"))
    li_count = len(article.find_all("li"))
    decision_hits = _count_matches(text, DECISION_PATTERNS[lang])
    blog_voice_hits = _count_matches(text, BLOG_VOICE_PATTERNS[lang])
    not_for_everyone_hits = _count_matches(text, NOT_FOR_EVERYONE_PATTERNS[lang])
    brochure_hits = _count_matches(text, BROCHURE_PATTERNS[lang])
    forbidden_hits = sum(1 for pattern in FORBIDDEN_VISIBLE_TERMS if pattern.search(text))
    repeated_sentences = _repeated_sentence_count(text)

    score = 100
    weak_dimensions: list[str] = []
    recommended_fix: list[str] = []

    if body_chars < 3000:
        score -= 5 if body_chars >= 2000 else 18
        weak_dimensions.append("body_under_3000" if body_chars >= 2000 else "body_under_2000")
        recommended_fix.append("Add route judgment content, not filler.")
    if h2_count < 5:
        score -= 4
        weak_dimensions.append("low_h2_structure")
    if h3_count < 2:
        score -= 3
        weak_dimensions.append("low_h3_structure")
    if table_count < 1:
        score -= 4
        weak_dimensions.append("missing_decision_table")
    if li_count < 3:
        score -= 3
        weak_dimensions.append("missing_checklist")
    if decision_hits < 6:
        score -= 8
        weak_dimensions.append("low_decision_density")
        recommended_fix.append("Add skip/reroute/timing/return-route decisions.")
    if blog_voice_hits < 2:
        score -= 5
        weak_dimensions.append("low_blog_voice")
        recommended_fix.append("Add channel-specific first-person or editor judgment.")
    if not_for_everyone_hits < 1:
        score -= 4
        weak_dimensions.append("missing_not_for_everyone")
        recommended_fix.append("Add a natural section for who should skip the route.")
    if brochure_hits:
        score -= min(8, brochure_hits * 2)
        weak_dimensions.append("brochure_language")
        recommended_fix.append("Remove promotional adjectives and replace them with tradeoff judgments.")
    if forbidden_hits:
        score -= 20
        weak_dimensions.append("internal_terms_visible")
        recommended_fix.append("Remove internal scoring/pattern terms from visible content.")
    if repeated_sentences:
        score -= 20
        weak_dimensions.append("repeated_sentence_3plus")
        recommended_fix.append("Rewrite repeated sentences or repeated closing blocks.")

    return {
        "language": lang,
        "url": url,
        "title": _clean_text((soup.find("title").get_text(" ", strip=True) if soup.find("title") else "")),
        "score": max(0, min(100, score)),
        "body_chars": body_chars,
        "h2": h2_count,
        "h3": h3_count,
        "tables": table_count,
        "list_items": li_count,
        "decision_hits": decision_hits,
        "blog_voice_hits": blog_voice_hits,
        "not_for_everyone_hits": not_for_everyone_hits,
        "brochure_hits": brochure_hits,
        "forbidden_hits": forbidden_hits,
        "repeated_sentence_3plus": repeated_sentences,
        "weak_dimensions": sorted(set(weak_dimensions)),
        "recommended_fix": sorted(set(recommended_fix)),
        "quality_status": "good" if score >= 90 else ("acceptable" if score >= 80 else "needs_repair"),
        "contains_water_word": any(token in lower_text for token in (" river ", "río", "\u5ddd\u6cbf\u3044")),
    }


def audit(langs: list[str], timeout: float, report_root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "BloggerGentConceptAudit/1.0"}) as client:
        for lang in langs:
            urls = _sitemap_urls(client, BLOGS[lang])
            for url in urls:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    rows.append(_score_document(lang, url, response.text))
                except Exception as exc:  # noqa: BLE001 - audit must continue.
                    errors.append({"language": lang, "url": url, "error": repr(exc)})

    summary: dict[str, Any] = {}
    for lang in langs:
        lang_rows = [row for row in rows if row["language"] == lang]
        if not lang_rows:
            summary[lang] = {"total": 0, "average_score": None}
            continue
        avg = round(sum(row["score"] for row in lang_rows) / len(lang_rows), 1)
        buckets = Counter(row["quality_status"] for row in lang_rows)
        weak = Counter(dim for row in lang_rows for dim in row["weak_dimensions"])
        summary[lang] = {
            "total": len(lang_rows),
            "average_score": avg,
            "good_90_plus": buckets.get("good", 0),
            "acceptable_80_89": buckets.get("acceptable", 0),
            "needs_repair_under_80": buckets.get("needs_repair", 0),
            "top_weak_dimensions": weak.most_common(10),
            "lowest": sorted(lang_rows, key=lambda row: row["score"])[:10],
        }

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": langs,
        "summary": summary,
        "fetch_errors": errors,
        "rows": rows,
    }
    report_path = report_root / f"travel-concept-score-audit-{_now_stamp()}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["report_path"] = str(report_path)
    return payload


def main() -> int:
    _stdout_utf8()
    parser = argparse.ArgumentParser(description="Audit travel concept suitability scores from live sitemap URLs.")
    parser.add_argument("--langs", default="en,es,ja", help="Comma-separated languages: en,es,ja")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report-root", default=str(REPORT_ROOT))
    args = parser.parse_args()
    langs = [lang.strip().lower() for lang in args.langs.split(",") if lang.strip()]
    invalid = [lang for lang in langs if lang not in BLOGS]
    if invalid:
        raise SystemExit(f"Unsupported languages: {', '.join(invalid)}")
    payload = audit(langs, args.timeout, Path(args.report_root))
    print(json.dumps({"report_path": payload["report_path"], "summary": payload["summary"], "fetch_errors": len(payload["fetch_errors"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
