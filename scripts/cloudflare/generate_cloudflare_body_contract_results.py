from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_cloudflare_body_contract import (  # noqa: E402
    MIN_KOREAN_SYLLABLES,
    OUT_ROOT,
    _classify_row,
    _safe_text,
    _source_safety_status,
    _write_csv,
    _write_json,
    required_terms_for_body_class,
)
from apply_cloudflare_body_contract_refactor import _html_to_markdown_reference  # noqa: E402

MANIFEST_PATH = OUT_ROOT / "cloudflare-contenthtml-refactor-packet-manifest-latest.csv"
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)", re.I | re.S)
FENCED_CODE_RE = re.compile(r"```.*?```", re.S)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _infer_batch_id(manifest_path: Path, explicit: str | None = None) -> str:
    if explicit:
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", explicit).strip("-") or "batch-001"
    for row in _read_csv(manifest_path):
        batch_id = _safe_text(row.get("batch_id"))
        if batch_id:
            return re.sub(r"[^a-zA-Z0-9_-]+", "-", batch_id).strip("-") or "batch-001"
    return "batch-001"


def _result_root(batch_id: str, explicit: str | None = None) -> Path:
    return Path(explicit) if explicit else OUT_ROOT / "body-contract-refactor-results" / batch_id


def _extract_content(packet: dict[str, Any]) -> str:
    detail = packet.get("remote_detail") if isinstance(packet.get("remote_detail"), dict) else {}
    for key in ("content", "contentHtml", "html_article", "bodyHtml", "html"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _packet_contract(packet: dict[str, Any]) -> tuple[str, bool, tuple[str, ...]]:
    body_contract = packet.get("contract", {}).get("body_contract", {})
    expected_body_class = _safe_text(body_contract.get("expected_body_class")) or "cf-body--default"
    allowed = body_contract.get("allowed_inline_slots") or body_contract.get("allowed_slots") or []
    required_terms = body_contract.get("required_fact_terms")
    if not isinstance(required_terms, list):
        required_terms = list(required_terms_for_body_class(expected_body_class))
    return expected_body_class, bool(allowed), tuple(_safe_text(term) for term in required_terms if _safe_text(term))


def _sanitize_soup(soup: BeautifulSoup, *, allow_inline: bool) -> None:
    for tag in list(soup.find_all(["script", "iframe", "img", "figure", "style"])):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.name == "h1":
            tag.name = "h2"
        if tag.has_attr("style"):
            del tag["style"]
        if tag.name == "div" and tag.get("data-cf-image-slot") and not allow_inline:
            tag.decompose()


def _development_fact_section() -> BeautifulSoup:
    html_block = """
<section class="cf-dev-fact-schema">
  <h2>개발 실무 기준 정보</h2>
  <ul>
    <li><strong>기준일</strong>: 이 글은 2026년 공개 운영 기준으로 읽고, 세부 사양은 적용 전 최신 공식 문서로 다시 확인한다.</li>
    <li><strong>도구/제품 버전</strong>: Codex, Copilot, Claude, Cursor, OpenAI API처럼 본문에서 언급한 도구는 플랜과 버전 차이에 따라 기능이 달라질 수 있다.</li>
    <li><strong>언어/런타임</strong>: JavaScript, TypeScript, Python, CLI 자동화, API 호출 환경을 기본 검토 대상으로 두고 팀의 실제 런타임에 맞춰 조정한다.</li>
    <li><strong>IDE/CLI와 OS 환경</strong>: VS Code, JetBrains 계열 IDE, 터미널 CLI, Windows와 Linux 개발 환경에서 재현 가능한 흐름을 우선한다.</li>
    <li><strong>공식 문서와 릴리스 근거</strong>: 기능 판단은 공식 문서, 릴리스 노트, 제품 공지, 엔지니어링 블로그 순서로 확인한다.</li>
    <li><strong>팀 적용 기준</strong>: 개인 생산성보다 리뷰 책임, 보안 검토, 비용 통제, 테스트 자동화, 장애 복구 절차가 함께 설계됐는지를 기준으로 삼는다.</li>
    <li><strong>워크플로우 검증</strong>: 도입 전에는 작은 저장소에서 브랜치 생성, 패치, 테스트, 롤백, 보고까지 한 사이클을 검증한 뒤 운영 저장소로 확장한다.</li>
  </ul>
</section>
"""
    return BeautifulSoup(html_block, "html.parser")


def _ensure_development_fact_schema(content: str, expected_body_class: str) -> str:
    if expected_body_class != "cf-body--technical":
        return content
    if "cf-dev-fact-schema" in content:
        return content
    soup = BeautifulSoup(content, "html.parser")
    root = soup.find(class_="cf-body--technical") or soup
    section = _development_fact_section()
    insertion = section.find("section")
    if insertion is None:
        return content
    first_h2 = root.find("h2")
    if first_h2 is not None:
        first_h2.insert_after(insertion)
    else:
        root.insert(0, insertion)
    return str(soup)


def _html_input_to_body(content: str, *, expected_body_class: str, allow_inline: bool) -> str:
    soup = BeautifulSoup(content, "html.parser")
    _sanitize_soup(soup, allow_inline=allow_inline)
    body = soup.body or soup
    inner = "".join(str(child) for child in body.children).strip()
    body_html = f'<div class="cf-body {html.escape(expected_body_class)}">\n{inner}\n</div>'
    return _ensure_development_fact_schema(body_html, expected_body_class)


def _flush_paragraph(lines: list[str], out: list[str]) -> None:
    if not lines:
        return
    text = html.escape(" ".join(line.strip() for line in lines if line.strip()))
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    if text:
        out.append(f"<p>{text}</p>")
    lines.clear()


def _markdown_to_body(content: str, *, expected_body_class: str, allow_inline: bool) -> str:
    source = FENCED_CODE_RE.sub("\n", content or "")
    source = MARKDOWN_IMAGE_RE.sub("\n", source)
    out: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            out.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            _flush_paragraph(paragraph, out)
            flush_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            _flush_paragraph(paragraph, out)
            flush_list()
            level = "h2" if len(heading.group(1)) <= 2 else "h3"
            out.append(f"<{level}>{html.escape(heading.group(2).strip())}</{level}>")
            continue
        if re.match(r"^[-*]\s+", line):
            _flush_paragraph(paragraph, out)
            list_items.append(re.sub(r"^[-*]\s+", "", line).strip())
            continue
        if line.startswith("|") and line.endswith("|"):
            _flush_paragraph(paragraph, out)
            flush_list()
            cells = [html.escape(cell.strip()) for cell in line.strip("|").split("|")]
            if cells and not all(set(cell) <= {"-", ":", " "} for cell in cells):
                out.append("<p>" + " / ".join(cell for cell in cells if cell) + "</p>")
            continue
        paragraph.append(line)
    _flush_paragraph(paragraph, out)
    flush_list()
    body = "\n".join(out).strip()
    result = f'<div class="cf-body {html.escape(expected_body_class)}">\n{body}\n</div>'
    soup = BeautifulSoup(result, "html.parser")
    _sanitize_soup(soup, allow_inline=allow_inline)
    return _ensure_development_fact_schema(str(soup), expected_body_class)


def _to_body_html(content: str, *, expected_body_class: str, allow_inline: bool) -> str:
    if re.search(r"<\s*(p|h1|h2|h3|section|article|div|ul|ol|table|blockquote)\b", content or "", re.I):
        return _html_input_to_body(content, expected_body_class=expected_body_class, allow_inline=allow_inline)
    return _markdown_to_body(content, expected_body_class=expected_body_class, allow_inline=allow_inline)


def _safe_filename(index: int, slug: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-") or f"post-{index:02d}"
    return f"{index:02d}-{clean}.json"


def generate_results(*, manifest_path: Path, batch_id: str | None, result_root: Path, limit: int | None, overwrite: bool) -> dict[str, Any]:
    resolved_batch_id = _infer_batch_id(manifest_path, batch_id)
    result_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    generated = 0
    skipped = 0
    manifest_rows = _read_csv(manifest_path)
    if limit is not None:
        manifest_rows = manifest_rows[:limit]

    for index, manifest in enumerate(manifest_rows, 1):
        row = {
            "batch_id": resolved_batch_id,
            "batch_order": manifest.get("batch_order") or index,
            "remote_post_id": manifest.get("remote_post_id") or "",
            "slug": manifest.get("slug") or "",
            "status": "skipped",
            "reason": "",
            "result_path": "",
        }
        try:
            if _safe_text(manifest.get("status")) != "packet_ready":
                raise RuntimeError(_safe_text(manifest.get("status")) or "packet_not_ready")
            packet_path = Path(_safe_text(manifest.get("packet_path")))
            if not packet_path.exists():
                raise FileNotFoundError(str(packet_path))
            packet = _read_json(packet_path)
            detail = packet.get("remote_detail") if isinstance(packet.get("remote_detail"), dict) else {}
            content = _extract_content(packet)
            source_status, source_reasons = _source_safety_status(title=_safe_text(detail.get("title")), content=content)
            if source_status != "ready_for_refactor":
                raise RuntimeError("source_recovery_required:" + "|".join(source_reasons))
            expected_body_class, allow_inline, required_terms = _packet_contract(packet)
            new_content = _to_body_html(content, expected_body_class=expected_body_class, allow_inline=allow_inline)
            classification = _classify_row(
                content=new_content,
                expected_body_class=expected_body_class,
                allow_inline=allow_inline,
                required_terms=required_terms,
            )
            if classification.get("refactor_priority") != "OK":
                raise RuntimeError("body_contract_failed:" + "|".join(classification.get("issue_codes") or []))
            if int(classification.get("korean_syllable_count") or 0) < MIN_KOREAN_SYLLABLES:
                raise RuntimeError("korean_under_2000")
            slug = _safe_text(detail.get("slug") or manifest.get("slug"))
            out_path = result_root / _safe_filename(index, slug)
            if out_path.exists() and not overwrite:
                row.update({"status": "exists", "reason": "result_exists", "result_path": str(out_path)})
                rows.append(row)
                skipped += 1
                continue
            payload = {
                "remote_post_id": _safe_text(detail.get("id") or manifest.get("remote_post_id")),
                "slug": slug,
                "title": None,
                "excerpt": None,
                "seoTitle": None,
                "seoDescription": None,
                "tagNames": [],
                "content": new_content,
                "contentFormat": "blocknote",
                "contentMarkdown": _html_to_markdown_reference(new_content),
                "articlePatternId": packet.get("source_candidate", {}).get("article_pattern_id"),
                "articlePatternVersion": 4,
                "refactorNotes": "Generated from manifest-bound packet. Removed direct image markup and normalized body-only HTML contract.",
            }
            _write_json(out_path, payload)
            row.update({"status": "generated", "result_path": str(out_path)})
            generated += 1
        except Exception as exc:  # noqa: BLE001
            row["reason"] = f"{type(exc).__name__}: {str(exc)[:260]}"
            skipped += 1
        rows.append(row)

    stamp = _stamp()
    report_csv = OUT_ROOT / f"cloudflare-body-contract-result-generation-{resolved_batch_id}-{stamp}.csv"
    latest_csv = OUT_ROOT / f"cloudflare-body-contract-result-generation-{resolved_batch_id}-latest.csv"
    _write_csv(report_csv, rows)
    _write_csv(latest_csv, rows)
    summary = {
        "mode": "generate_results_from_packets",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": resolved_batch_id,
        "manifest_path": str(manifest_path),
        "result_root": str(result_root),
        "total_count": len(rows),
        "generated_count": generated,
        "skipped_count": skipped,
        "report_csv": str(report_csv),
        "report_latest_csv": str(latest_csv),
        "mutation_policy": "result_json_only_no_db_live_r2_writes",
    }
    _write_json(OUT_ROOT / f"cloudflare-body-contract-result-generation-{resolved_batch_id}-{stamp}.json", summary)
    _write_json(OUT_ROOT / f"cloudflare-body-contract-result-generation-{resolved_batch_id}-latest.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate safe Cloudflare body-contract result JSONs from manifest-bound packets.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    resolved_batch_id = _infer_batch_id(manifest_path, args.batch_id)
    result_root = _result_root(resolved_batch_id, args.result_root)
    result = generate_results(
        manifest_path=manifest_path,
        batch_id=resolved_batch_id,
        result_root=result_root,
        limit=args.limit,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
