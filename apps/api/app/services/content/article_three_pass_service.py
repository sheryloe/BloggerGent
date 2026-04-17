from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from app.schemas.ai import ArticleGenerationOutput

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"\s+")
_TOTAL_MIN_KO = 3000
_TOTAL_MAX_KO = 4000
_TRAVEL_TOTAL_MIN_KO = 3200
_TRAVEL_TOTAL_MAX_KO = 3600
_RATIO_TOLERANCE = 0.08


@dataclass(frozen=True, slots=True)
class _PassSpec:
    index: int
    key: str
    label: str
    ratio: float
    target_min_ko: int
    target_max_ko: int

    @property
    def target_mid_ko(self) -> int:
        return int((self.target_min_ko + self.target_max_ko) / 2)


_PASS_SPECS: tuple[_PassSpec, ...] = (
    _PassSpec(index=1, key="introduction", label="Introduction", ratio=0.2, target_min_ko=600, target_max_ko=800),
    _PassSpec(index=2, key="body", label="Body", ratio=0.6, target_min_ko=1800, target_max_ko=2400),
    _PassSpec(index=3, key="conclusion", label="Conclusion", ratio=0.2, target_min_ko=600, target_max_ko=800),
)
_PASS_SPEC_BY_KEY = {item.key: item for item in _PASS_SPECS}

_TRAVEL_BEATS: tuple[dict[str, str], ...] = (
    {"key": "gi", "label": "기", "english_label": "Setup"},
    {"key": "seung", "label": "승", "english_label": "Build"},
    {"key": "jeon", "label": "전", "english_label": "Turn"},
    {"key": "gyeol", "label": "결", "english_label": "Close"},
)
_TRAVEL_BEAT_RATIOS: dict[str, float] = {
    "gi": 0.2,
    "seung": 0.3,
    "jeon": 0.3,
    "gyeol": 0.2,
}
_TRAVEL_BEAT_TARGETS: dict[str, tuple[int, int]] = {
    "gi": (640, 720),
    "seung": (960, 1080),
    "jeon": (960, 1080),
    "gyeol": (640, 720),
}

ArticlePassGenerator = Callable[[str], tuple[ArticleGenerationOutput, dict]]
StructuredJsonGenerator = Callable[[str], tuple[dict[str, Any], dict]]


def _plain_text_length(html: str) -> int:
    text = _HTML_TAG_RE.sub(" ", str(html or " "))
    text = _MULTISPACE_RE.sub("", text)
    return len(text)


def _is_korean_language(language: str | None) -> bool:
    normalized = str(language or "").strip().lower()
    return normalized.startswith("ko")


def _pick_non_empty_text(primary: str | None, fallback: str | None) -> str:
    primary_text = str(primary or "").strip()
    if primary_text:
        return primary_text
    return str(fallback or "").strip()


def _normalize_faq_items(items) -> list[dict]:
    normalized: list[dict] = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump())
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _section_html(output: ArticleGenerationOutput) -> str:
    return str(getattr(output, "html_article", "") or "").strip()


def _build_pass_prompt(
    *,
    base_prompt: str,
    spec: _PassSpec,
    is_korean: bool,
    retry_reason: str | None = None,
) -> str:
    lines = [
        str(base_prompt or "").strip(),
        "",
        "[3-Step Article Assembly Runtime]",
        f"- Current pass: {spec.index}/3 ({spec.label}).",
        "- Return valid JSON using the existing output schema.",
        f"- In this pass, `html_article` must contain only the {spec.label} section content.",
        "- Do not include content for the other two major sections in this pass.",
    ]
    if spec.index == 1:
        lines.append("- Title/meta_description/labels/slug/excerpt in this pass are the canonical final values.")
    elif spec.index == 3:
        lines.append("- faq_section/image_collage_prompt/inline_collage_prompt in this pass are the canonical final values.")
    else:
        lines.append("- Keep title/meta_description/labels/slug/excerpt consistent with pass 1.")
    if is_korean:
        lines.append(
            f"- Korean plain-text target for this pass (`html_article` only): {spec.target_min_ko}~{spec.target_max_ko} chars."
        )
        lines.append("- For all 3 passes combined, target 3000~4000 Korean chars with 20/60/20 composition.")
    if retry_reason:
        lines.append(f"- Retry fix required for this pass: {retry_reason}")
        lines.append("- Rewrite this pass once with stronger structure contrast and better section fit.")
    return "\n".join(lines).strip()


def _evaluate_ko_lengths(pass_lengths: dict[str, int]) -> dict[str, object]:
    total = sum(pass_lengths.values())
    ratios = {key: (pass_lengths[key] / total if total > 0 else 0.0) for key in pass_lengths}
    failing: set[str] = set()

    for spec in _PASS_SPECS:
        length = pass_lengths.get(spec.key, 0)
        if length < spec.target_min_ko or length > spec.target_max_ko:
            failing.add(spec.key)
        if total > 0 and abs(ratios.get(spec.key, 0.0) - spec.ratio) > _RATIO_TOLERANCE:
            failing.add(spec.key)

    if total < _TOTAL_MIN_KO:
        under = [key for key, length in pass_lengths.items() if length < _PASS_SPEC_BY_KEY[key].target_mid_ko]
        if under:
            failing.update(under)
    elif total > _TOTAL_MAX_KO:
        over = [key for key, length in pass_lengths.items() if length > _PASS_SPEC_BY_KEY[key].target_mid_ko]
        if over:
            failing.update(over)

    if (_TOTAL_MIN_KO <= total <= _TOTAL_MAX_KO) is False and not failing:
        dominant = max(pass_lengths.keys(), key=lambda key: abs(pass_lengths[key] - _PASS_SPEC_BY_KEY[key].target_mid_ko))
        failing.add(dominant)

    return {
        "total_plain_text_length": total,
        "ratios": ratios,
        "pass_lengths": dict(pass_lengths),
        "target_total_min": _TOTAL_MIN_KO,
        "target_total_max": _TOTAL_MAX_KO,
        "target_total_ok": _TOTAL_MIN_KO <= total <= _TOTAL_MAX_KO,
        "failing_passes": sorted(failing),
    }


def _evaluate_travel_ko_lengths(pass_lengths: dict[str, int]) -> dict[str, object]:
    total = sum(pass_lengths.values())
    ratios = {key: (pass_lengths[key] / total if total > 0 else 0.0) for key in pass_lengths}
    failing: set[str] = set()

    for beat_key, length in pass_lengths.items():
        target_min, target_max = _TRAVEL_BEAT_TARGETS.get(beat_key, (0, 999999))
        if length < target_min or length > target_max:
            failing.add(beat_key)
        expected_ratio = _TRAVEL_BEAT_RATIOS.get(beat_key)
        if expected_ratio is not None and total > 0 and abs(ratios.get(beat_key, 0.0) - expected_ratio) > _RATIO_TOLERANCE:
            failing.add(beat_key)

    if total < _TRAVEL_TOTAL_MIN_KO:
        for beat_key, (target_min, target_max) in _TRAVEL_BEAT_TARGETS.items():
            if pass_lengths.get(beat_key, 0) < int((target_min + target_max) / 2):
                failing.add(beat_key)
    elif total > _TRAVEL_TOTAL_MAX_KO:
        for beat_key, (target_min, target_max) in _TRAVEL_BEAT_TARGETS.items():
            if pass_lengths.get(beat_key, 0) > int((target_min + target_max) / 2):
                failing.add(beat_key)

    return {
        "total_plain_text_length": total,
        "ratios": ratios,
        "pass_lengths": dict(pass_lengths),
        "target_total_min": _TRAVEL_TOTAL_MIN_KO,
        "target_total_max": _TRAVEL_TOTAL_MAX_KO,
        "target_total_ok": _TRAVEL_TOTAL_MIN_KO <= total <= _TRAVEL_TOTAL_MAX_KO,
        "failing_passes": sorted(failing),
    }


def _assemble_output(
    *,
    pass_one: ArticleGenerationOutput,
    pass_two: ArticleGenerationOutput,
    pass_three: ArticleGenerationOutput,
) -> ArticleGenerationOutput:
    final_html = "\n\n".join(
        section for section in (_section_html(pass_one), _section_html(pass_two), _section_html(pass_three)) if section
    ).strip()
    payload = pass_one.model_dump()
    payload["html_article"] = final_html
    payload["faq_section"] = (
        _normalize_faq_items(pass_three.faq_section)
        if _normalize_faq_items(pass_three.faq_section)
        else _normalize_faq_items(pass_one.faq_section)
    )
    payload["image_collage_prompt"] = _pick_non_empty_text(pass_three.image_collage_prompt, pass_one.image_collage_prompt)
    payload["inline_collage_prompt"] = _pick_non_empty_text(pass_three.inline_collage_prompt, pass_one.inline_collage_prompt)
    return ArticleGenerationOutput.model_validate(payload)


def generate_three_step_article(
    *,
    base_prompt: str,
    language: str | None,
    generate_pass: ArticlePassGenerator,
) -> tuple[ArticleGenerationOutput, dict]:
    is_korean = _is_korean_language(language)
    pass_outputs: dict[str, ArticleGenerationOutput] = {}
    pass_raw: dict[str, dict] = {}
    pass_lengths: dict[str, int] = {}
    retries: list[dict[str, object]] = []

    for spec in _PASS_SPECS:
        pass_prompt = _build_pass_prompt(base_prompt=base_prompt, spec=spec, is_korean=is_korean)
        output, raw = generate_pass(pass_prompt)
        pass_outputs[spec.key] = output
        pass_raw[spec.key] = raw
        pass_lengths[spec.key] = _plain_text_length(output.html_article)

    validation = _evaluate_ko_lengths(pass_lengths) if is_korean else {
        "total_plain_text_length": sum(pass_lengths.values()),
        "ratios": {key: 0.0 for key in pass_lengths},
        "pass_lengths": dict(pass_lengths),
        "failing_passes": [],
        "target_total_ok": True,
    }

    for failed_key in list(validation.get("failing_passes", [])):
        spec = _PASS_SPEC_BY_KEY[failed_key]
        retry_prompt = _build_pass_prompt(
            base_prompt=base_prompt,
            spec=spec,
            is_korean=is_korean,
            retry_reason=f"plain_text_length={pass_lengths.get(failed_key, 0)}",
        )
        retry_output, retry_raw = generate_pass(retry_prompt)
        pass_outputs[failed_key] = retry_output
        pass_raw[failed_key] = retry_raw
        pass_lengths[failed_key] = _plain_text_length(retry_output.html_article)
        retries.append(
            {
                "pass": failed_key,
                "attempt": 2,
                "plain_text_length": pass_lengths[failed_key],
            }
        )

    pass_one = pass_outputs["introduction"]
    pass_two = pass_outputs["body"]
    pass_three = pass_outputs["conclusion"]
    final_output = _assemble_output(pass_one=pass_one, pass_two=pass_two, pass_three=pass_three)
    final_validation = _evaluate_ko_lengths(pass_lengths) if is_korean else {
        "total_plain_text_length": _plain_text_length(final_output.html_article),
        "ratios": {key: 0.0 for key in pass_lengths},
        "pass_lengths": dict(pass_lengths),
        "failing_passes": [],
        "target_total_ok": True,
    }

    metadata = {
        "three_step_article_assembly": True,
        "language": str(language or "").strip() or None,
        "passes": [
            {
                "index": spec.index,
                "pass": spec.key,
                "label": spec.label,
                "plain_text_length": pass_lengths.get(spec.key, 0),
                "raw": pass_raw.get(spec.key),
            }
            for spec in _PASS_SPECS
        ],
        "retries": retries,
        "validation": final_validation,
    }
    return final_output, metadata


def _normalize_travel_planner_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    beats = []
    raw_beats = data.get("beats")
    raw_items = raw_beats if isinstance(raw_beats, list) else []
    for index, template in enumerate(_TRAVEL_BEATS):
        item = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        beats.append(
            {
                "key": template["key"],
                "label": str(item.get("label") or template["label"]).strip() or template["label"],
                "goal": str(item.get("goal") or "").strip() or f"{template['english_label']} the article clearly.",
                "must_include": [
                    str(value).strip()
                    for value in (item.get("must_include") or [])
                    if str(value).strip()
                ],
                "avoid": [
                    str(value).strip()
                    for value in (item.get("avoid") or [])
                    if str(value).strip()
                ],
            }
        )
    labels = [str(value).strip() for value in (data.get("labels") or []) if str(value).strip()]
    return {
        "title_direction": str(data.get("title_direction") or "").strip(),
        "meta_description_direction": str(data.get("meta_description_direction") or "").strip(),
        "slug_basis": str(data.get("slug_basis") or "").strip(),
        "labels": labels[:6],
        "faq_intent": str(data.get("faq_intent") or "").strip(),
        "image_seed": str(data.get("image_seed") or "").strip(),
        "route_place_key_cues": [
            str(value).strip()
            for value in (data.get("route_place_key_cues") or [])
            if str(value).strip()
        ][:8],
        "beats": beats,
    }


def _build_travel_planner_prompt(*, base_prompt: str) -> str:
    return "\n".join(
        [
            str(base_prompt or "").strip(),
            "",
            "[Travel 4-Beat Planner Runtime]",
            "- Plan the article before writing body sections.",
            "- Return JSON only.",
            "- Design one four-beat structure using 기/승/전/결.",
            "- Keep the article practical and route-led.",
            "- Output exactly these top-level keys:",
            '  "title_direction", "meta_description_direction", "slug_basis", "labels", "faq_intent", "image_seed", "route_place_key_cues", "beats".',
            '- "labels" must be 5 to 6 short strings.',
            '- "route_place_key_cues" must be 3 to 8 practical scene cues.',
            '- "beats" must be an array of exactly 4 objects in order: 기 승 전 결.',
            '- Each beat object must include "label", "goal", "must_include", and "avoid".',
            "- Do not write the article body in this step.",
        ]
    ).strip()


def _format_travel_planner_summary(planner: dict[str, Any]) -> str:
    lines = [
        f"Title direction: {planner.get('title_direction') or 'Keep the route promise immediate.'}",
        f"Meta direction: {planner.get('meta_description_direction') or 'Make the planning value explicit.'}",
    ]
    labels = [str(value).strip() for value in (planner.get("labels") or []) if str(value).strip()]
    if labels:
        lines.append(f"Labels: {', '.join(labels)}")
    cues = [str(value).strip() for value in (planner.get("route_place_key_cues") or []) if str(value).strip()]
    if cues:
        lines.append(f"Route cues: {', '.join(cues)}")
    for beat in planner.get("beats") or []:
        if not isinstance(beat, dict):
            continue
        label = str(beat.get("label") or beat.get("key") or "").strip()
        goal = str(beat.get("goal") or "").strip()
        if label and goal:
            lines.append(f"{label}: {goal}")
    return "\n".join(lines).strip()


def _build_travel_pass_prompt(
    *,
    base_prompt: str,
    planner: dict[str, Any],
    beat: dict[str, Any],
    beat_index: int,
    is_korean: bool,
    retry_reason: str | None = None,
) -> str:
    must_include = ", ".join(str(value).strip() for value in (beat.get("must_include") or []) if str(value).strip())
    avoid = ", ".join(str(value).strip() for value in (beat.get("avoid") or []) if str(value).strip())
    lines = [
        str(base_prompt or "").strip(),
        "",
        "[Travel 4-Beat Article Runtime]",
        f"- Current beat: {beat_index}/4 ({beat.get('label') or beat.get('key')}).",
        "- Return valid JSON using the existing article output schema.",
        "- In this pass, `html_article` must contain only the current beat content.",
        "- Do not write the other three major beats in this pass.",
        f"- Planner title direction: {planner.get('title_direction') or ''}",
        f"- Planner meta direction: {planner.get('meta_description_direction') or ''}",
        f"- Planner FAQ intent: {planner.get('faq_intent') or ''}",
        f"- Planner image seed: {planner.get('image_seed') or ''}",
        f"- Beat goal: {beat.get('goal') or ''}",
    ]
    if must_include:
        lines.append(f"- Must include: {must_include}")
    if avoid:
        lines.append(f"- Avoid overlap with: {avoid}")
    if beat_index == 1:
        lines.append("- Title/meta_description/labels/slug/excerpt in this pass are the canonical final values.")
    elif beat_index == 4:
        lines.append("- faq_section and image_collage_prompt in this pass are the canonical final values.")
        lines.append("- inline_collage_prompt must be null or empty.")
    else:
        lines.append("- Keep title/meta_description/labels/slug/excerpt aligned with beat 1.")
    if is_korean:
        beat_key = str(beat.get("key") or "").strip()
        target_min, target_max = _TRAVEL_BEAT_TARGETS.get(beat_key, (800, 1000))
        lines.append(f"- Korean plain-text target for this beat (`html_article` only): {target_min}~{target_max} chars.")
        lines.append("- For all 4 beats combined, target 3200~3600 Korean chars with 20/30/30/20 composition.")
    if retry_reason:
        lines.append(f"- Retry fix required for this beat: {retry_reason}")
        lines.append("- Rewrite this beat once with tighter scope and stronger section ownership.")
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _assemble_travel_four_beat_output(
    *,
    planner: dict[str, Any],
    pass_outputs: list[ArticleGenerationOutput],
) -> ArticleGenerationOutput:
    first = pass_outputs[0]
    last = pass_outputs[-1]
    payload = first.model_dump()
    payload["html_article"] = "\n\n".join(_section_html(item) for item in pass_outputs if _section_html(item)).strip()
    payload["faq_section"] = (
        _normalize_faq_items(last.faq_section)
        if _normalize_faq_items(last.faq_section)
        else _normalize_faq_items(first.faq_section)
    )
    payload["image_collage_prompt"] = _pick_non_empty_text(last.image_collage_prompt, first.image_collage_prompt)
    payload["inline_collage_prompt"] = None
    if planner.get("labels"):
        payload["labels"] = list(planner["labels"])
    return ArticleGenerationOutput.model_validate(payload)


def generate_travel_four_beat_article(
    *,
    base_prompt: str,
    language: str | None,
    generate_planner: StructuredJsonGenerator,
    generate_pass: ArticlePassGenerator,
) -> tuple[ArticleGenerationOutput, dict]:
    is_korean = _is_korean_language(language)
    planner_prompt = _build_travel_planner_prompt(base_prompt=base_prompt)
    planner_payload, planner_raw = generate_planner(planner_prompt)
    planner = _normalize_travel_planner_payload(planner_payload)

    pass_outputs: list[ArticleGenerationOutput] = []
    pass_raw: list[dict[str, Any]] = []
    pass_lengths: dict[str, int] = {}
    for index, beat in enumerate(planner["beats"], start=1):
        pass_prompt = _build_travel_pass_prompt(
            base_prompt=base_prompt,
            planner=planner,
            beat=beat,
            beat_index=index,
            is_korean=is_korean,
        )
        output, raw = generate_pass(pass_prompt)
        pass_outputs.append(output)
        beat_key = str(beat.get("key") or index).strip()
        pass_lengths[beat_key] = _plain_text_length(output.html_article)
        pass_raw.append(
            {
                "index": index,
                "beat": beat.get("key"),
                "label": beat.get("label"),
                "raw": raw,
                "plain_text_length": pass_lengths[beat_key],
            }
        )

    validation = _evaluate_travel_ko_lengths(pass_lengths) if is_korean else {
        "total_plain_text_length": sum(pass_lengths.values()),
        "ratios": {key: 0.0 for key in pass_lengths},
        "pass_lengths": dict(pass_lengths),
        "failing_passes": [],
        "target_total_ok": True,
    }
    retries: list[dict[str, object]] = []
    beat_index_by_key = {str(beat.get("key") or "").strip(): index for index, beat in enumerate(planner["beats"], start=1)}
    for failed_key in list(validation.get("failing_passes", [])):
        beat_position = beat_index_by_key.get(failed_key)
        if beat_position is None:
            continue
        beat = planner["beats"][beat_position - 1]
        retry_prompt = _build_travel_pass_prompt(
            base_prompt=base_prompt,
            planner=planner,
            beat=beat,
            beat_index=beat_position,
            is_korean=is_korean,
            retry_reason=f"plain_text_length={pass_lengths.get(failed_key, 0)}",
        )
        retry_output, retry_raw = generate_pass(retry_prompt)
        pass_outputs[beat_position - 1] = retry_output
        pass_lengths[failed_key] = _plain_text_length(retry_output.html_article)
        pass_raw[beat_position - 1] = {
            "index": beat_position,
            "beat": beat.get("key"),
            "label": beat.get("label"),
            "raw": retry_raw,
            "plain_text_length": pass_lengths[failed_key],
        }
        retries.append(
            {
                "pass": failed_key,
                "attempt": 2,
                "plain_text_length": pass_lengths[failed_key],
            }
        )

    final_output = _assemble_travel_four_beat_output(planner=planner, pass_outputs=pass_outputs)
    final_validation = _evaluate_travel_ko_lengths(pass_lengths) if is_korean else {
        "total_plain_text_length": _plain_text_length(final_output.html_article),
        "ratios": {key: 0.0 for key in pass_lengths},
        "pass_lengths": dict(pass_lengths),
        "failing_passes": [],
        "target_total_ok": True,
    }
    metadata = {
        "travel_four_beat_article_assembly": True,
        "language": str(language or "").strip() or None,
        "planner": planner,
        "planner_prompt": planner_prompt,
        "planner_raw": planner_raw,
        "planner_summary": _format_travel_planner_summary(planner),
        "passes": pass_raw,
        "retries": retries,
        "validation": final_validation,
    }
    return final_output, metadata


_MYSTERY_PARTS: tuple[dict[str, str], ...] = (
    {"key": "setup", "label": "Setup"},
    {"key": "record", "label": "Records & Timeline"},
    {"key": "analysis", "label": "Evidence & Interpretation"},
    {"key": "status", "label": "Current Status & Open Questions"},
)
_MYSTERY_TOTAL_MIN = 3200
_MYSTERY_TOTAL_MAX = 3600


def _normalize_mystery_planner_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    labels = [str(value).strip() for value in (data.get("labels") or []) if str(value).strip()]
    beats = []
    raw_beats = data.get("beats")
    raw_items = raw_beats if isinstance(raw_beats, list) else []
    for index, part in enumerate(_MYSTERY_PARTS):
        item = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        beats.append(
            {
                "key": part["key"],
                "label": str(item.get("label") or part["label"]).strip() or part["label"],
                "goal": str(item.get("goal") or "").strip() or f"Deliver a strong {part['label']} section.",
                "must_include": [
                    str(value).strip()
                    for value in (item.get("must_include") or [])
                    if str(value).strip()
                ],
                "avoid": [
                    str(value).strip()
                    for value in (item.get("avoid") or [])
                    if str(value).strip()
                ],
            }
        )
    return {
        "title_direction": str(data.get("title_direction") or "").strip(),
        "meta_description_direction": str(data.get("meta_description_direction") or "").strip(),
        "slug_basis": str(data.get("slug_basis") or "").strip(),
        "labels": labels[:6],
        "faq_intent": str(data.get("faq_intent") or "").strip(),
        "image_seed": str(data.get("image_seed") or "").strip(),
        "fact_vs_claim_policy": str(data.get("fact_vs_claim_policy") or "").strip(),
        "beats": beats,
    }


def _build_mystery_planner_prompt(*, base_prompt: str) -> str:
    return "\n".join(
        [
            str(base_prompt or "").strip(),
            "",
            "[Mystery Planner Runtime]",
            "- Plan one publish-ready mystery article before writing section bodies.",
            "- Return JSON only with no markdown or commentary.",
            "- Design exactly 4 sections in this fixed order: Setup, Records & Timeline, Evidence & Interpretation, Current Status & Open Questions.",
            '- Output exactly these top-level keys: "title_direction", "meta_description_direction", "slug_basis", "labels", "faq_intent", "image_seed", "fact_vs_claim_policy", "beats".',
            '- "labels" must contain 5 to 6 short strings.',
            '- "beats" must contain exactly 4 objects in order; each object must include "label", "goal", "must_include", and "avoid".',
            "- Keep the final assembled article in roughly 3200~3600 plain-text characters.",
            "- Do not write article body HTML in this step.",
        ]
    ).strip()


def _format_mystery_planner_summary(planner: dict[str, Any]) -> str:
    lines = [
        f"Title direction: {planner.get('title_direction') or 'Documentary headline with clear case anchor.'}",
        f"Meta direction: {planner.get('meta_description_direction') or 'Summarize case value and unresolved angle.'}",
    ]
    fact_claim_policy = str(planner.get("fact_vs_claim_policy") or "").strip()
    if fact_claim_policy:
        lines.append(f"Fact/claim policy: {fact_claim_policy}")
    labels = [str(value).strip() for value in (planner.get("labels") or []) if str(value).strip()]
    if labels:
        lines.append(f"Labels: {', '.join(labels)}")
    for beat in planner.get("beats") or []:
        if not isinstance(beat, dict):
            continue
        label = str(beat.get("label") or beat.get("key") or "").strip()
        goal = str(beat.get("goal") or "").strip()
        if label and goal:
            lines.append(f"{label}: {goal}")
    return "\n".join(lines).strip()


def _build_mystery_pass_prompt(
    *,
    base_prompt: str,
    planner: dict[str, Any],
    beat: dict[str, Any],
    beat_index: int,
) -> str:
    must_include = ", ".join(str(value).strip() for value in (beat.get("must_include") or []) if str(value).strip())
    avoid = ", ".join(str(value).strip() for value in (beat.get("avoid") or []) if str(value).strip())
    lines = [
        str(base_prompt or "").strip(),
        "",
        "[Mystery 4-Part Runtime]",
        f"- Current part: {beat_index}/4 ({beat.get('label') or beat.get('key')}).",
        "- Return valid JSON using the existing article output schema.",
        "- In this pass, `html_article` must contain only the current part content.",
        "- Do not write content for the other three parts in this pass.",
        "- Keep this pass in roughly 700~1000 plain-text characters to land near 3200~3600 after assembly.",
        f"- Planner title direction: {planner.get('title_direction') or ''}",
        f"- Planner meta direction: {planner.get('meta_description_direction') or ''}",
        f"- Planner FAQ intent: {planner.get('faq_intent') or ''}",
        f"- Planner image seed: {planner.get('image_seed') or ''}",
        f"- Fact/claim policy: {planner.get('fact_vs_claim_policy') or ''}",
        f"- Part goal: {beat.get('goal') or ''}",
    ]
    if must_include:
        lines.append(f"- Must include: {must_include}")
    if avoid:
        lines.append(f"- Avoid overlap with: {avoid}")
    if beat_index == 1:
        lines.append("- title/meta_description/labels/slug/excerpt in this pass are the canonical final values.")
    elif beat_index == 4:
        lines.append("- faq_section and image_collage_prompt in this pass are the canonical final values.")
        lines.append("- inline_collage_prompt must be null or empty.")
    else:
        lines.append("- Keep title/meta_description/labels/slug/excerpt aligned with part 1.")
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _assemble_mystery_four_part_output(
    *,
    planner: dict[str, Any],
    pass_outputs: list[ArticleGenerationOutput],
) -> ArticleGenerationOutput:
    first = pass_outputs[0]
    last = pass_outputs[-1]
    payload = first.model_dump()
    payload["html_article"] = "\n\n".join(_section_html(item) for item in pass_outputs if _section_html(item)).strip()
    payload["faq_section"] = (
        _normalize_faq_items(last.faq_section)
        if _normalize_faq_items(last.faq_section)
        else _normalize_faq_items(first.faq_section)
    )
    payload["image_collage_prompt"] = _pick_non_empty_text(last.image_collage_prompt, first.image_collage_prompt)
    payload["inline_collage_prompt"] = None
    if planner.get("labels"):
        payload["labels"] = list(planner["labels"])
    return ArticleGenerationOutput.model_validate(payload)


def generate_mystery_four_part_article(
    *,
    base_prompt: str,
    language: str | None,
    generate_planner: StructuredJsonGenerator,
    generate_pass: ArticlePassGenerator,
) -> tuple[ArticleGenerationOutput, dict]:
    planner_prompt = _build_mystery_planner_prompt(base_prompt=base_prompt)
    planner_payload, planner_raw = generate_planner(planner_prompt)
    planner = _normalize_mystery_planner_payload(planner_payload)

    pass_outputs: list[ArticleGenerationOutput] = []
    pass_raw: list[dict[str, Any]] = []
    for index, beat in enumerate(planner["beats"], start=1):
        pass_prompt = _build_mystery_pass_prompt(
            base_prompt=base_prompt,
            planner=planner,
            beat=beat,
            beat_index=index,
        )
        output, raw = generate_pass(pass_prompt)
        pass_outputs.append(output)
        pass_raw.append(
            {
                "index": index,
                "part": beat.get("key"),
                "label": beat.get("label"),
                "raw": raw,
                "plain_text_length": _plain_text_length(output.html_article),
            }
        )

    final_output = _assemble_mystery_four_part_output(planner=planner, pass_outputs=pass_outputs)
    total_plain_text_length = _plain_text_length(final_output.html_article)
    pass_slots: dict[str, dict[str, Any]] = {}
    for index in range(1, 5):
        pass_slots[f"pass{index}"] = {}
    for entry in pass_raw:
        if not isinstance(entry, dict):
            continue
        index = int(entry.get("index") or 0)
        if 1 <= index <= 4:
            pass_slots[f"pass{index}"] = dict(entry)
    metadata = {
        "mystery_four_part_article_assembly": True,
        "language": str(language or "").strip() or None,
        "planner": planner,
        "planner_prompt": planner_prompt,
        "planner_raw": planner_raw,
        "planner_summary": _format_mystery_planner_summary(planner),
        "passes": pass_raw,
        **pass_slots,
        "validation": {
            "target_total_min": _MYSTERY_TOTAL_MIN,
            "target_total_max": _MYSTERY_TOTAL_MAX,
            "total_plain_text_length": total_plain_text_length,
            "target_total_ok": _MYSTERY_TOTAL_MIN <= total_plain_text_length <= _MYSTERY_TOTAL_MAX,
        },
    }
    return final_output, metadata
