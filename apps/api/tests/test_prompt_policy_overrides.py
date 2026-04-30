from types import SimpleNamespace

from app.schemas.ai import ArticleGenerationOutput
from app.services import article_pattern_service, blog_service, cloudflare_channel_service
from app.services.content.travel_blog_policy import TRAVEL_ALLOWED_PATTERN_IDS
from app.services.ops.model_policy_service import CODEX_TEXT_RUNTIME_KIND, CODEX_TEXT_RUNTIME_MODEL


def test_select_blogger_article_pattern_uses_current_travel_policy_patterns(monkeypatch) -> None:
    monkeypatch.setattr(
        article_pattern_service,
        "_recent_blogger_pattern_ids",
        lambda db, blog_id, editorial_category_key, limit=3: (
            "travel-01-hidden-path-route",
            "travel-02-cultural-insider",
        ),
    )

    selection = article_pattern_service.select_blogger_article_pattern(
        object(),
        blog_id=1,
        profile_key="korea_travel",
        editorial_category_key="travel",
    )

    assert selection.pattern_id in TRAVEL_ALLOWED_PATTERN_IDS
    assert set(selection.allowed_pattern_ids) == TRAVEL_ALLOWED_PATTERN_IDS


def test_render_agent_prompt_injects_pattern_block(monkeypatch) -> None:
    selection = article_pattern_service.ArticlePatternSelection(
        pattern_id="travel-03-local-flavor-guide",
        pattern_version=1,
        label="Local Flavor Guide",
        summary="문제에서 해결로 가는 구조",
        html_hint="section.callout",
        allowed_pattern_ids=tuple(sorted(TRAVEL_ALLOWED_PATTERN_IDS)),
        recent_pattern_ids=("travel-02-cultural-insider",),
    )
    monkeypatch.setattr(blog_service, "select_blogger_article_pattern", lambda *args, **kwargs: selection)

    blog = SimpleNamespace(
        id=1,
        name="Test Blog",
        slug="test-blog",
        description="",
        content_category="travel",
        primary_language="en",
        target_audience="traveler",
        content_brief="travel blog",
        blogger_url="",
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
        profile_key="korea_travel",
    )
    agent = SimpleNamespace(
        prompt_template="Base prompt for {blog_name}",
        stage_type=blog_service.WorkflowStageType.ARTICLE_GENERATION,
    )

    rendered = blog_service.render_agent_prompt(
        object(),
        blog,
        agent,
        editorial_category_key="travel",
        editorial_category_label="Travel",
        editorial_category_guidance="route-first",
    )

    assert "[Article pattern registry]" in rendered
    assert "travel-03-local-flavor-guide" in rendered
    assert "[HTML structure policy]" in rendered


def test_cloudflare_life_category_mapping_matches_latest_policy() -> None:
    useful_guidance = cloudflare_channel_service._category_topic_guidance("삶을-유용하게", "삶을 유용하게", "")
    oil_guidance = cloudflare_channel_service._category_topic_guidance("삶의-기름칠", "삶의 기름칠", "")
    useful_brief = cloudflare_channel_service._cloudflare_content_brief("삶을-유용하게", "삶을 유용하게", "")
    oil_brief = cloudflare_channel_service._cloudflare_content_brief("삶의-기름칠", "삶의 기름칠", "")

    assert "건강" in useful_guidance
    assert "정책" in oil_guidance
    assert "건강" in useful_brief
    assert "지원금" in oil_brief


def test_article_generation_output_allows_empty_faq_section() -> None:
    payload = ArticleGenerationOutput(
        title="테스트 제목은 충분히 길어야 합니다",
        meta_description="이 메타 설명은 충분히 길어서 스키마의 최소 길이 요구사항을 충족합니다. 독자가 글의 핵심을 빠르게 이해할 수 있게 작성합니다.",
        labels=["테스트", "샘플"],
        slug="test-slug",
        excerpt="첫 문장으로 글의 방향을 설명합니다. 두 번째 문장으로 독자가 얻을 이익을 분명하게 정리합니다.",
        html_article="<section><h2>테스트</h2><p>본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다. 본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다. 본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다. 본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다. 본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다. 본문 길이를 충분히 맞추기 위해 문장을 여러 번 반복합니다.</p></section>",
        faq_section=[],
        image_collage_prompt="realistic editorial collage with nine distinct panels and a dominant center panel, visible white gutters, no text, no logo",
        inline_collage_prompt="realistic editorial supporting collage with six distinct panels, visible white gutters, no text, no logo",
    )

    assert payload.faq_section == []


def test_enforce_text_runtime_policy_keeps_standard_runtime_settings(monkeypatch) -> None:
    class _FakeExecuteResult:
        def __init__(self, blogs):
            self._blogs = blogs

        def scalars(self):
            return self

        def unique(self):
            return self

        def all(self):
            return self._blogs

    class _FakeDb:
        def __init__(self, blogs):
            self.blogs = blogs
            self.added = []
            self.commit_count = 0

        def execute(self, *_args, **_kwargs):
            return _FakeExecuteResult(self.blogs)

        def add(self, item):
            self.added.append(item)

        def commit(self):
            self.commit_count += 1

    topic_step = SimpleNamespace(
        stage_type=blog_service.WorkflowStageType.TOPIC_DISCOVERY,
        provider_hint="gemini",
        provider_model="gemini-2.5-flash",
    )
    refactor_step = SimpleNamespace(
        stage_type=blog_service.WorkflowStageType.SEO_REWRITE,
        provider_hint="openai",
        provider_model="gpt-4.1-2025-04-14",
    )
    blog = SimpleNamespace(
        id=1,
        profile_key="korea_travel",
        agent_configs=[topic_step, refactor_step],
    )
    db = _FakeDb([blog])
    captured_updates = {}

    monkeypatch.setattr(
        blog_service,
        "get_settings_map",
        lambda _db: {
            "text_runtime_kind": "gemini_cli",
            "topic_discovery_provider": "gemini",
            "image_runtime_kind": "openai_image",
            "openai_usage_hard_cap_enabled": "false",
        },
    )
    monkeypatch.setattr(
        blog_service,
        "upsert_settings",
        lambda _db, values: captured_updates.update(values),
    )
    monkeypatch.setattr(blog_service, "add_log", lambda *args, **kwargs: None)

    result = blog_service.enforce_text_runtime_policy(db)

    assert captured_updates == {"openai_usage_hard_cap_enabled": "true"}
    assert result["settings_updates"] == {"openai_usage_hard_cap_enabled": "true"}
    assert topic_step.provider_hint != CODEX_TEXT_RUNTIME_KIND
    assert topic_step.provider_model != CODEX_TEXT_RUNTIME_MODEL
    assert refactor_step.provider_hint == CODEX_TEXT_RUNTIME_KIND
    assert refactor_step.provider_model == CODEX_TEXT_RUNTIME_MODEL
