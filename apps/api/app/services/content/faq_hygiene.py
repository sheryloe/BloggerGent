from __future__ import annotations

import re
from typing import Iterable, TypedDict


GENERIC_FAQ_QUESTION_PREFIXES = (
    "what should readers know about",
    "how can readers apply",
)

GENERIC_FAQ_ANSWER_SNIPPETS = (
    "this section summarizes the essential context, expectations, and constraints around",
    "use a short checklist and the key steps in this article to plan, evaluate, and execute",
)

GENERIC_FAQ_LINE_TOKENS = (
    *GENERIC_FAQ_QUESTION_PREFIXES,
    *GENERIC_FAQ_ANSWER_SNIPPETS,
)

FAQ_HEADING_REGEX = (
    r"(?:frequently asked questions|preguntas frecuentes|"
    r"よくある質問(?:（faq）|\(faq\))?|자주\s*묻는\s*질문(?:\s*\(faq\))?)"
)

GENERIC_FAQ_HEADING_PATTERN = re.compile(
    rf"^\s*{FAQ_HEADING_REGEX}\s*$",
    flags=re.IGNORECASE,
)

DETAILS_BLOCK_RE = re.compile(r"(?is)<details\b[^>]*>.*?</details>")
HANGUL_CHAR_RE = re.compile(r"[가-힣]")
STATIC_FAQ_BLOCK_RE = re.compile(
    rf"(?is)(?P<block><h2\b[^>]*>\s*{FAQ_HEADING_REGEX}\s*</h2>\s*(?P<body>.*?))"
    r"(?=(?:<h2\b|<section\b|<!--RELATED_POSTS-->|$))"
)
QUESTION_PREFIX_RE = re.compile(
    r"(?i)\b(?:what should readers know about|how can readers apply)\b"
)
DETAILS_PLACEHOLDER_RE = re.compile(r"__BLOGGENT_DETAILS_BLOCK_\d+__")


class FaqHygieneStats(TypedDict):
    faq_static_block_removed_count: int
    question_line_removed_count: int
    details_preserved_count: int


def _normalize_space(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def is_generic_faq_item(question: str | None, answer: str | None) -> bool:
    normalized_question = _normalize_space(question)
    normalized_answer = _normalize_space(answer)
    if any(normalized_question.startswith(prefix) for prefix in GENERIC_FAQ_QUESTION_PREFIXES):
        return True
    if any(snippet in normalized_answer for snippet in GENERIC_FAQ_ANSWER_SNIPPETS):
        return True
    return False


def filter_generic_faq_items(items: Iterable[dict]) -> list[dict]:
    filtered: list[dict] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question or not answer:
            continue
        if is_generic_faq_item(question, answer):
            continue
        filtered.append({"question": question, "answer": answer})
    return filtered


def _new_stats() -> FaqHygieneStats:
    return {
        "faq_static_block_removed_count": 0,
        "question_line_removed_count": 0,
        "details_preserved_count": 0,
    }


def _mask_details_blocks(html_text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return f"__BLOGGENT_DETAILS_BLOCK_{len(blocks) - 1}__"

    return DETAILS_BLOCK_RE.sub(_replace, html_text), blocks


def _restore_details_blocks(html_text: str, blocks: list[str]) -> str:
    restored = html_text
    for index, block in enumerate(blocks):
        restored = restored.replace(f"__BLOGGENT_DETAILS_BLOCK_{index}__", block)
    return restored


def strip_generic_faq_leak_html_with_stats(html_text: str) -> tuple[str, FaqHygieneStats]:
    cleaned = str(html_text or "")
    stats = _new_stats()
    if not cleaned.strip():
        return "", stats

    cleaned, details_blocks = _mask_details_blocks(cleaned)
    stats["details_preserved_count"] = len(details_blocks)

    def _remove_static_faq_block(match: re.Match[str]) -> str:
        block = str(match.group("block") or "")
        body = str(match.group("body") or "")
        lowered_body = body.casefold()
        has_question_prefix = any(prefix in lowered_body for prefix in GENERIC_FAQ_QUESTION_PREFIXES)
        has_hangul = bool(HANGUL_CHAR_RE.search(body))
        has_generic_answer = any(snippet in lowered_body for snippet in GENERIC_FAQ_ANSWER_SNIPPETS)
        if not has_question_prefix or not (has_hangul or has_generic_answer):
            return block
        stats["faq_static_block_removed_count"] += 1
        stats["question_line_removed_count"] += len(QUESTION_PREFIX_RE.findall(body))
        details_placeholders = DETAILS_PLACEHOLDER_RE.findall(block)
        if not details_placeholders:
            return ""
        return "\n".join(details_placeholders)

    cleaned = STATIC_FAQ_BLOCK_RE.sub(_remove_static_faq_block, cleaned)

    for token in GENERIC_FAQ_QUESTION_PREFIXES:
        escaped = re.escape(token)
        cleaned, removed_tag_lines = re.subn(
            rf"(?is)<(?:p|h2|h3|h4|li|summary|blockquote)\b[^>]*>[^<]*{escaped}[^<]*</(?:p|h2|h3|h4|li|summary|blockquote)>",
            "",
            cleaned,
        )
        cleaned, removed_plain_lines = re.subn(
            rf"(?im)^\s*.*{escaped}.*(?:\r?\n)?",
            "",
            cleaned,
        )
        stats["question_line_removed_count"] += int(removed_tag_lines + removed_plain_lines)

    for token in GENERIC_FAQ_ANSWER_SNIPPETS:
        escaped = re.escape(token)
        cleaned = re.sub(
            rf"(?is)<(?:p|h2|h3|h4|li|summary|blockquote)\b[^>]*>[^<]*{escaped}[^<]*</(?:p|h2|h3|h4|li|summary|blockquote)>",
            "",
            cleaned,
        )
        cleaned = re.sub(
            rf"(?im)^\s*.*{escaped}.*(?:\r?\n)?",
            "",
            cleaned,
        )

    cleaned = re.sub(
        rf"(?is)<h2\b[^>]*>\s*{FAQ_HEADING_REGEX}\s*</h2>\s*(?=(?:<h2\b|<section\b|<!--RELATED_POSTS-->|$))",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?is)<(section|div)\b[^>]*>\s*</\1>", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    cleaned = _restore_details_blocks(cleaned, details_blocks)
    stats["details_preserved_count"] = len(DETAILS_BLOCK_RE.findall(cleaned))
    return cleaned.strip(), stats


def strip_generic_faq_leak_html(html_text: str) -> str:
    cleaned, _stats = strip_generic_faq_leak_html_with_stats(html_text)
    return cleaned
