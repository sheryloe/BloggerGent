from __future__ import annotations

from app.schemas.ai import ArticleGenerationOutput
from app.services.content.article_three_pass_service import (
    generate_mystery_four_part_article,
    generate_three_step_article,
    generate_travel_four_beat_article,
)


def _build_output(
    *,
    title_tag: str,
    body_char: str,
    body_len: int,
    faq_items: list[dict] | None = None,
    image_prompt: str | None = None,
    inline_prompt: str | None = None,
) -> ArticleGenerationOutput:
    body_text = body_char * max(body_len, 200)
    return ArticleGenerationOutput(
        title=f"{title_tag} article title sample",
        meta_description=f"{title_tag} meta description for structured testing and deterministic output verification.",
        labels=["PrimaryLabel", "SecondaryLabel"],
        slug=f"{title_tag.lower()}-slug-sample",
        excerpt=f"{title_tag} excerpt line one for tests. {title_tag} excerpt line two for tests.",
        html_article=f"<h2>{title_tag}</h2><p>{body_text}</p>",
        faq_section=faq_items or [],
        image_collage_prompt=image_prompt
        or "Editorial collage prompt with clear panel separation and no text overlays for testing.",
        inline_collage_prompt=inline_prompt,
    )


def test_generate_three_step_article_assembles_outputs_with_pass_ownership() -> None:
    pass_outputs = [
        _build_output(
            title_tag="Intro",
            body_char="A",
            body_len=260,
            faq_items=[
                {
                    "question": "What should I check first for this setup?",
                    "answer": "Check scope, constraints, and expected outcomes before implementation.",
                }
            ],
            image_prompt="Intro image prompt should not win final image prompt because pass3 has priority.",
            inline_prompt="Intro inline prompt should be used when pass3 inline prompt is empty.",
        ),
        _build_output(
            title_tag="Body",
            body_char="B",
            body_len=300,
            faq_items=[
                {
                    "question": "How should I execute the core workflow?",
                    "answer": "Execute in ordered steps and validate at each checkpoint.",
                }
            ],
            image_prompt="Body image prompt with clear collage framing and realistic workflow context.",
            inline_prompt="Body inline prompt",
        ),
        _build_output(
            title_tag="Conclusion",
            body_char="C",
            body_len=280,
            faq_items=[],
            image_prompt="Conclusion image prompt should win final image prompt due pass3 priority.",
            inline_prompt=None,
        ),
    ]

    prompts: list[str] = []
    index = {"value": 0}

    def _generate_pass(prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        prompts.append(prompt)
        current = pass_outputs[index["value"]]
        index["value"] += 1
        return current, {"mock_call_index": index["value"]}

    output, metadata = generate_three_step_article(
        base_prompt="Base article prompt",
        language="en",
        generate_pass=_generate_pass,
    )

    assert len(prompts) == 3
    assert output.title == pass_outputs[0].title
    assert output.meta_description == pass_outputs[0].meta_description
    assert output.labels == pass_outputs[0].labels
    assert output.slug == pass_outputs[0].slug
    assert output.excerpt == pass_outputs[0].excerpt
    assert output.image_collage_prompt == pass_outputs[2].image_collage_prompt
    assert output.inline_collage_prompt == pass_outputs[0].inline_collage_prompt
    assert len(output.faq_section) == 1
    assert output.faq_section[0].question.startswith("What should I check first")
    assert output.html_article.find("<h2>Intro</h2>") < output.html_article.find("<h2>Body</h2>")
    assert output.html_article.find("<h2>Body</h2>") < output.html_article.find("<h2>Conclusion</h2>")
    assert metadata["three_step_article_assembly"] is True
    assert metadata["retries"] == []
    assert len(metadata["passes"]) == 3


def test_generate_three_step_article_retries_only_failing_korean_pass_once() -> None:
    call_count = {"total": 0, "intro": 0}

    def _generate_pass(prompt: str) -> tuple[ArticleGenerationOutput, dict]:
        call_count["total"] += 1
        if "Current pass: 1/3" in prompt:
            call_count["intro"] += 1
            intro_len = 320 if call_count["intro"] == 1 else 650
            return (
                _build_output(
                    title_tag=f"Intro{call_count['intro']}",
                    body_char="가",
                    body_len=intro_len,
                    faq_items=[
                        {
                            "question": "도입부에서 먼저 확인해야 할 핵심은 무엇인가요?",
                            "answer": "범위와 기대 결과를 먼저 정리하면 이후 구조가 안정됩니다.",
                        }
                    ],
                    image_prompt="Korean intro image prompt for deterministic retry behavior in tests.",
                    inline_prompt="Korean intro inline prompt retained as fallback for conclusion pass.",
                ),
                {"pass": "introduction", "attempt": call_count["intro"]},
            )
        if "Current pass: 2/3" in prompt:
            return (
                _build_output(
                    title_tag="Body",
                    body_char="나",
                    body_len=2000,
                    faq_items=[
                        {
                            "question": "본문에서는 어떤 순서로 실행해야 하나요?",
                            "answer": "문제 정의, 실행 단계, 검증 기준 순서로 진행하면 재현성이 높아집니다.",
                        }
                    ],
                    image_prompt="Body image prompt for Korean assembly policy validation and stable panel framing.",
                    inline_prompt="Body inline prompt",
                ),
                {"pass": "body", "attempt": 1},
            )
        return (
            _build_output(
                title_tag="Conclusion",
                body_char="다",
                body_len=700,
                faq_items=[],
                image_prompt="Conclusion image prompt should remain final for Korean assembly and validation.",
                inline_prompt=None,
            ),
            {"pass": "conclusion", "attempt": 1},
        )

    output, metadata = generate_three_step_article(
        base_prompt="Korean base prompt",
        language="ko",
        generate_pass=_generate_pass,
    )

    assert call_count["total"] == 4
    assert call_count["intro"] == 2
    assert len(metadata["retries"]) == 1
    assert metadata["retries"][0]["pass"] == "introduction"
    assert metadata["validation"]["target_total_ok"] is True
    assert metadata["validation"]["failing_passes"] == []
    assert metadata["validation"]["pass_lengths"]["introduction"] >= 600
    assert output.title.startswith("Intro2")
    assert output.image_collage_prompt.startswith("Conclusion image prompt")


def test_generate_travel_four_beat_article_assembles_planner_and_passes() -> None:
    planner = {
        "title_direction": "Route-first Seoul planning article",
        "meta_description_direction": "Immediate planning value",
        "labels": ["Travel", "Seoul", "Route", "Guide", "Local"],
        "faq_intent": "What readers should check before going.",
        "image_seed": "single flattened 5x4 travel collage with 20 visible panels and thin white gutters.",
        "route_place_key_cues": ["station", "cafe", "street", "night view"],
        "beats": [
            {"label": "기", "goal": "Open with the route promise.", "must_include": ["hook"], "avoid": ["padding"]},
            {"label": "승", "goal": "Explain movement and timing.", "must_include": ["transit"], "avoid": ["repetition"]},
            {"label": "전", "goal": "Add local insight and comparison.", "must_include": ["local angle"], "avoid": ["generic tips"]},
            {"label": "결", "goal": "Close with checklist and FAQ bridge.", "must_include": ["summary"], "avoid": ["new topics"]},
        ],
    }
    pass_outputs = [
        _build_output(
            title_tag="Beat1",
            body_char="A",
            body_len=760,
            image_prompt="Beat1 image prompt with a single flattened 5x4 travel collage and no text overlays.",
        ),
        _build_output(
            title_tag="Beat2",
            body_char="B",
            body_len=780,
            image_prompt="Beat2 image prompt with route cues, realistic panels, and thin white gutters.",
        ),
        _build_output(
            title_tag="Beat3",
            body_char="C",
            body_len=760,
            image_prompt="Beat3 image prompt with local scene contrast, realistic movement, and panel separation.",
        ),
        _build_output(
            title_tag="Beat4",
            body_char="D",
            body_len=760,
            faq_items=[
                {
                    "question": "What should I confirm before leaving?",
                    "answer": "Confirm timing, transit, and the stop sequence before leaving.",
                }
            ],
            image_prompt="Beat4 image prompt should win final image prompt with single-image 5x4 route collage framing.",
            inline_prompt=None,
        ),
    ]
    planner_prompts: list[str] = []
    pass_prompts: list[str] = []
    index = {"value": 0}

    def _generate_planner(prompt: str):
        planner_prompts.append(prompt)
        return planner, {"mock_planner": True}

    def _generate_pass(prompt: str):
        pass_prompts.append(prompt)
        current = pass_outputs[index["value"]]
        index["value"] += 1
        return current, {"mock_call_index": index["value"]}

    output, metadata = generate_travel_four_beat_article(
        base_prompt="Base travel article prompt",
        language="en",
        generate_planner=_generate_planner,
        generate_pass=_generate_pass,
    )

    assert len(planner_prompts) == 1
    assert len(pass_prompts) == 4
    assert output.title == pass_outputs[0].title
    assert output.image_collage_prompt == pass_outputs[3].image_collage_prompt
    assert output.inline_collage_prompt is None
    assert output.labels == planner["labels"]
    assert metadata["travel_four_beat_article_assembly"] is True
    assert metadata["planner"]["title_direction"] == planner["title_direction"]
    assert len(metadata["passes"]) == 4
    assert metadata["validation"]["target_total_ok"] is True
    assert metadata["validation"]["recommended_total_ok"] is False


def test_generate_travel_four_beat_article_retries_korean_beats_to_3200_3600() -> None:
    planner = {
        "title_direction": "서울 봄 야간 산책 루트",
        "meta_description_direction": "실전 동선",
        "labels": ["Travel", "Seoul", "Night", "Route", "Guide"],
        "faq_intent": "출발 전에 무엇을 확인해야 하는가",
        "image_seed": "single flattened 5x4 editorial travel collage, 1024x1024, twenty visible panels, thin white gutters",
        "route_place_key_cues": ["station", "cafe", "night view"],
        "beats": [
            {"label": "기", "goal": "도입", "must_include": ["hook"], "avoid": ["padding"]},
            {"label": "승", "goal": "전개", "must_include": ["route"], "avoid": ["repetition"]},
            {"label": "전", "goal": "전환", "must_include": ["contrast"], "avoid": ["generic"]},
            {"label": "결", "goal": "정리", "must_include": ["checklist"], "avoid": ["new topics"]},
        ],
    }
    counts = {"gi": 0, "seung": 0, "jeon": 0, "gyeol": 0}

    def _generate_planner(_prompt: str):
        return planner, {"mock_planner": True}

    def _generate_pass(prompt: str):
        if "Current beat: 1/4" in prompt:
            counts["gi"] += 1
            size = 500 if counts["gi"] == 1 else 680
            return _build_output(title_tag="Gi", body_char="가", body_len=size), {"beat": "gi", "attempt": counts["gi"]}
        if "Current beat: 2/4" in prompt:
            counts["seung"] += 1
            size = 800 if counts["seung"] == 1 else 1000
            return _build_output(title_tag="Seung", body_char="나", body_len=size), {"beat": "seung", "attempt": counts["seung"]}
        if "Current beat: 3/4" in prompt:
            counts["jeon"] += 1
            size = 820 if counts["jeon"] == 1 else 1000
            return _build_output(title_tag="Jeon", body_char="다", body_len=size), {"beat": "jeon", "attempt": counts["jeon"]}
        counts["gyeol"] += 1
        size = 500 if counts["gyeol"] == 1 else 680
        return _build_output(
            title_tag="Gyeol",
            body_char="라",
            body_len=size,
            faq_items=[{"question": "무엇을 먼저 확인하나요?", "answer": "교통과 혼잡도를 먼저 확인합니다."}],
        ), {"beat": "gyeol", "attempt": counts["gyeol"]}

    output, metadata = generate_travel_four_beat_article(
        base_prompt="한국어 여행 프롬프트",
        language="ko",
        generate_planner=_generate_planner,
        generate_pass=_generate_pass,
    )

    assert metadata["validation"]["target_total_ok"] is True
    assert metadata["validation"]["target_total_min"] == 3200
    assert metadata["validation"]["target_total_max"] == 3600
    assert metadata["validation"]["failing_passes"] == []
    assert len(metadata["retries"]) == 4
    assert 640 <= metadata["validation"]["pass_lengths"]["gi"] <= 720
    assert 960 <= metadata["validation"]["pass_lengths"]["seung"] <= 1080
    assert 960 <= metadata["validation"]["pass_lengths"]["jeon"] <= 1080
    assert 640 <= metadata["validation"]["pass_lengths"]["gyeol"] <= 720
    assert output.inline_collage_prompt is None


def test_generate_travel_four_beat_article_flags_short_non_korean_output() -> None:
    planner = {
        "title_direction": "Short route article",
        "meta_description_direction": "Short value",
        "labels": ["Travel", "Busan", "Route", "Guide", "Local"],
        "faq_intent": "What to check first.",
        "image_seed": "single flattened 5x4 travel collage with 20 visible panels.",
        "route_place_key_cues": ["station", "market", "viewpoint"],
        "beats": [
            {"key": "gi", "label": "기", "goal": "Open", "must_include": ["hook"], "avoid": ["padding"]},
            {"key": "seung", "label": "승", "goal": "Build", "must_include": ["route"], "avoid": ["repetition"]},
            {"key": "jeon", "label": "전", "goal": "Turn", "must_include": ["contrast"], "avoid": ["generic"]},
            {"key": "gyeol", "label": "결", "goal": "Close", "must_include": ["summary"], "avoid": ["new topics"]},
        ],
    }

    def _generate_planner(_prompt: str):
        return planner, {"mock_planner": True}

    def _generate_pass(_prompt: str):
        return _build_output(title_tag="Short", body_char="A", body_len=420), {"mock": True}

    _output, metadata = generate_travel_four_beat_article(
        base_prompt="English travel prompt",
        language="en",
        generate_planner=_generate_planner,
        generate_pass=_generate_pass,
    )

    assert metadata["validation"]["target_total_ok"] is False
    assert metadata["validation"]["total_plain_text_length"] < 3000
    assert metadata["validation"]["failing_passes"] != []


def test_generate_mystery_four_part_article_assembles_planner_and_passes() -> None:
    planner = {
        "title_direction": "Lead with the case and unresolved evidence gap.",
        "meta_description_direction": "Summarize record timeline and present-day uncertainty.",
        "labels": ["Case Files", "Cold Case", "Evidence", "Timeline", "Mystery"],
        "faq_intent": "Clarify what remains unknown.",
        "image_seed": "documentary collage with archive and location clues",
        "fact_vs_claim_policy": "Explicitly separate confirmed records from speculation.",
        "beats": [
            {"label": "Setup", "goal": "Introduce the case scope.", "must_include": ["who", "where"], "avoid": ["padding"]},
            {"label": "Records", "goal": "Build timeline.", "must_include": ["chronology"], "avoid": ["rumor"]},
            {"label": "Analysis", "goal": "Compare evidence theories.", "must_include": ["evidence"], "avoid": ["final verdict"]},
            {"label": "Status", "goal": "Show current state.", "must_include": ["open questions"], "avoid": ["new case"]},
        ],
    }
    pass_outputs = [
        _build_output(title_tag="Part1", body_char="A", body_len=820),
        _build_output(title_tag="Part2", body_char="B", body_len=860),
        _build_output(title_tag="Part3", body_char="C", body_len=860),
        _build_output(
            title_tag="Part4",
            body_char="D",
            body_len=830,
            faq_items=[{"question": "What remains unknown?", "answer": "Evidence gaps and source conflicts remain unresolved."}],
            image_prompt="Final hero image prompt should win from part 4.",
            inline_prompt="must-be-cleared",
        ),
    ]
    call_index = {"value": 0}

    def _generate_planner(_prompt: str):
        return planner, {"planner": "ok"}

    def _generate_pass(_prompt: str):
        item = pass_outputs[call_index["value"]]
        call_index["value"] += 1
        return item, {"pass": call_index["value"]}

    output, metadata = generate_mystery_four_part_article(
        base_prompt="Mystery base prompt",
        language="en",
        generate_planner=_generate_planner,
        generate_pass=_generate_pass,
    )

    assert output.title == pass_outputs[0].title
    assert output.image_collage_prompt == pass_outputs[3].image_collage_prompt
    assert output.inline_collage_prompt is None
    assert output.labels == planner["labels"]
    assert metadata["mystery_four_part_article_assembly"] is True
    assert metadata["planner"]["title_direction"] == planner["title_direction"]
    assert len(metadata["passes"]) == 4
