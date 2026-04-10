from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


ARTICLE_TAG_RE = re.compile(r"<(/?)article\b([^>]*)>", re.IGNORECASE)
ATTR_RE = re.compile(
    r"([A-Za-z_:][A-Za-z0-9:._-]*)"
    r"(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+)))?",
)
BODY_TAG_RE = re.compile(r"<body\b[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)
BLOGGENT_ATTR_PREFIX = "data-bloggent-"
ARTICLE_MARKER_ATTRS = ("data-bloggent-meta-description", "data-bloggent-article")
ARTICLE_HINT_TOKENS = (
    "post-body",
    "post-outer",
    "entry-content",
    "article-body",
    "bloggent-body",
)
ISSUE_EMPTY_FIGURE = "empty_figure"
ISSUE_MISSING_COVER = "missing_cover"
ISSUE_MISSING_INLINE = "missing_inline"
ISSUE_DUPLICATE_IMAGES = "duplicate_images"
ISSUE_BROKEN_IMAGE = "broken_image"
ISSUE_SLOT_MISMATCH = "slot_mismatch"
ISSUE_MISSING_PUBLIC_URL = "missing_public_url"
ISSUE_AUDIT_FAILED = "audit_failed"


@dataclass(slots=True)
class BloggerLiveImageAuditResult:
    live_image_count: int | None
    live_cover_present: bool | None
    live_inline_present: bool | None
    live_image_issue: str | None
    source_fragment: str
    raw_image_count: int
    empty_figure_count: int
    raw_figure_count: int
    renderable_image_urls: tuple[str, ...]


@dataclass(slots=True)
class _ArticleFragment:
    attrs: dict[str, str]
    html: str


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_attrs(raw_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in ATTR_RE.finditer(raw_text or ""):
        key = str(match.group(1) or "").strip().lower()
        if not key:
            continue
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        attrs[key] = str(value or "").strip()
    return attrs


def _extract_article_fragments(html: str) -> list[_ArticleFragment]:
    stack: list[tuple[int, dict[str, str]]] = []
    fragments: list[_ArticleFragment] = []
    for match in ARTICLE_TAG_RE.finditer(html or ""):
        is_end = match.group(1) == "/"
        if not is_end:
            stack.append((match.start(), _parse_attrs(match.group(2) or "")))
            continue
        if not stack:
            continue
        start_index, attrs = stack.pop()
        fragments.append(_ArticleFragment(attrs=attrs, html=html[start_index:match.end()]))
    return fragments


def _article_priority(fragment: _ArticleFragment) -> tuple[int, int, int]:
    attrs = fragment.attrs
    text_blob = " ".join([attrs.get("class", ""), attrs.get("id", ""), " ".join(attrs.keys())]).lower()
    has_bloggent_marker = any(key in attrs for key in ARTICLE_MARKER_ATTRS) or any(
        key.startswith(BLOGGENT_ATTR_PREFIX) for key in attrs
    )
    has_hint_token = any(token in text_blob for token in ARTICLE_HINT_TOKENS)
    # Prefer innermost article with explicit bloggent markers, then body-like hints, then longest fragment.
    return (
        0 if has_bloggent_marker else 1,
        0 if has_hint_token else 1,
        -len(fragment.html),
    )


def extract_primary_article_fragment(page_html: str) -> str:
    fragments = _extract_article_fragments(page_html or "")
    if fragments:
        selected = sorted(fragments, key=_article_priority)[0]
        return selected.html
    body_match = BODY_TAG_RE.search(page_html or "")
    if body_match:
        return str(body_match.group(1) or "")
    return str(page_html or "")


def _is_renderable_candidate(url: str) -> bool:
    lowered = _normalize_space(url).lower()
    if not lowered or lowered.startswith("data:"):
        return False
    if lowered.startswith("//") or lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("/"):
        return True
    return False


def _srcset_first_url(value: str) -> str:
    for token in (value or "").split(","):
        candidate = str(token).strip().split(" ")[0].strip()
        if candidate:
            return candidate
    return ""


def _normalize_image_url(page_url: str, raw_url: str) -> str:
    joined = urljoin(page_url, raw_url)
    parsed = urlsplit(joined)
    path = parsed.path or ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _duplicate_key(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.netloc.lower()}{parsed.path.lower()}"


def _probe_image_url(url: str, *, client: httpx.Client, timeout: float) -> bool:
    try:
        response = client.head(url, follow_redirects=True, timeout=timeout)
        if response.status_code < 400:
            return True
        if response.status_code not in {403, 405}:
            return False
    except Exception:
        pass
    try:
        response = client.get(url, follow_redirects=True, timeout=timeout)
        return response.status_code < 400
    except Exception:
        return False


class _FragmentImageParser(HTMLParser):
    def __init__(self, *, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.raw_image_count = 0
        self.empty_figure_count = 0
        self.raw_figure_count = 0
        self.renderable_images: list[dict[str, str | int | None]] = []
        self._figure_stack: list[dict[str, str | int | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "figure":
            return
        if not self._figure_stack:
            return
        figure = self._figure_stack.pop()
        if int(figure.get("img_count") or 0) == 0:
            self.empty_figure_count += 1

    def _handle_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {str(key or "").strip().lower(): str(value or "").strip() for key, value in attrs}
        if lowered == "figure":
            self.raw_figure_count += 1
            slot = attr_map.get("data-bloggent-normalize-slot") or attr_map.get("data-bloggent-restore-slot") or None
            self._figure_stack.append({"img_count": 0, "slot": slot})
            return
        if lowered != "img":
            return

        self.raw_image_count += 1
        raw_url = attr_map.get("src") or _srcset_first_url(attr_map.get("srcset", ""))
        if not _is_renderable_candidate(raw_url):
            return
        normalized_url = _normalize_image_url(self.page_url, raw_url)
        current_slot = str(self._figure_stack[-1].get("slot") or "") if self._figure_stack else ""
        if self._figure_stack:
            self._figure_stack[-1]["img_count"] = int(self._figure_stack[-1].get("img_count") or 0) + 1
        self.renderable_images.append(
            {
                "url": normalized_url,
                "slot": current_slot or None,
            }
        )


def audit_blogger_article_fragment(
    fragment_html: str,
    *,
    page_url: str,
    probe_images: bool = False,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
    image_probe: Callable[[str], bool] | None = None,
) -> BloggerLiveImageAuditResult:
    parser = _FragmentImageParser(page_url=page_url)
    parser.feed(fragment_html or "")
    parser.close()

    issue_codes: list[str] = []
    unique_urls: list[str] = []
    seen_urls: set[str] = set()
    duplicate_keys: set[str] = set()
    seen_duplicate_keys: set[str] = set()
    slot_counts: dict[str, int] = {}

    for item in parser.renderable_images:
        url = str(item.get("url") or "").strip()
        slot = str(item.get("slot") or "").strip().lower()
        if slot:
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
        if not url:
            continue
        duplicate_key = _duplicate_key(url)
        if duplicate_key in seen_duplicate_keys:
            duplicate_keys.add(duplicate_key)
            continue
        seen_duplicate_keys.add(duplicate_key)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_urls.append(url)

    if parser.empty_figure_count:
        issue_codes.append(ISSUE_EMPTY_FIGURE)
    if duplicate_keys:
        issue_codes.append(ISSUE_DUPLICATE_IMAGES)

    if slot_counts:
        cover_present = slot_counts.get("cover", 0) == 1
        inline_present = slot_counts.get("inline", 0) == 1
        if slot_counts.get("cover", 0) > 1 or slot_counts.get("inline", 0) > 1:
            issue_codes.append(ISSUE_SLOT_MISMATCH)
        if any(slot not in {"cover", "inline"} for slot in slot_counts):
            issue_codes.append(ISSUE_SLOT_MISMATCH)
    else:
        cover_present = len(unique_urls) >= 1
        inline_present = len(unique_urls) >= 2
        if len(unique_urls) > 2:
            issue_codes.append(ISSUE_SLOT_MISMATCH)

    if not cover_present:
        issue_codes.append(ISSUE_MISSING_COVER)
    if not inline_present:
        issue_codes.append(ISSUE_MISSING_INLINE)

    if probe_images and unique_urls:
        broken_found = False
        if image_probe is not None:
            broken_found = any(not image_probe(url) for url in unique_urls[:4])
        elif client is not None:
            broken_found = any(not _probe_image_url(url, client=client, timeout=timeout) for url in unique_urls[:4])
        if broken_found:
            issue_codes.append(ISSUE_BROKEN_IMAGE)

    normalized_issues = ",".join(sorted(set(issue_codes))) or None
    return BloggerLiveImageAuditResult(
        live_image_count=len(unique_urls),
        live_cover_present=cover_present,
        live_inline_present=inline_present,
        live_image_issue=normalized_issues,
        source_fragment=fragment_html or "",
        raw_image_count=parser.raw_image_count,
        empty_figure_count=parser.empty_figure_count,
        raw_figure_count=parser.raw_figure_count,
        renderable_image_urls=tuple(unique_urls),
    )


def audit_blogger_post_live_html(
    page_html: str,
    *,
    page_url: str,
    probe_images: bool = False,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
    image_probe: Callable[[str], bool] | None = None,
) -> BloggerLiveImageAuditResult:
    fragment = extract_primary_article_fragment(page_html)
    return audit_blogger_article_fragment(
        fragment,
        page_url=page_url,
        probe_images=probe_images,
        client=client,
        timeout=timeout,
        image_probe=image_probe,
    )


def fetch_and_audit_blogger_post(
    page_url: str | None,
    *,
    timeout: float = 15.0,
    probe_images: bool = True,
    client: httpx.Client | None = None,
) -> BloggerLiveImageAuditResult:
    normalized_url = _normalize_space(page_url)
    if not normalized_url:
        return BloggerLiveImageAuditResult(
            live_image_count=None,
            live_cover_present=None,
            live_inline_present=None,
            live_image_issue=ISSUE_MISSING_PUBLIC_URL,
            source_fragment="",
            raw_image_count=0,
            empty_figure_count=0,
            raw_figure_count=0,
            renderable_image_urls=(),
        )

    owns_client = client is None
    resolved_client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        response = resolved_client.get(normalized_url, timeout=timeout)
        response.raise_for_status()
        return audit_blogger_post_live_html(
            response.text,
            page_url=normalized_url,
            probe_images=probe_images,
            client=resolved_client,
            timeout=timeout,
        )
    except Exception:
        return BloggerLiveImageAuditResult(
            live_image_count=None,
            live_cover_present=None,
            live_inline_present=None,
            live_image_issue=ISSUE_AUDIT_FAILED,
            source_fragment="",
            raw_image_count=0,
            empty_figure_count=0,
            raw_figure_count=0,
            renderable_image_urls=(),
        )
    finally:
        if owns_client:
            resolved_client.close()
