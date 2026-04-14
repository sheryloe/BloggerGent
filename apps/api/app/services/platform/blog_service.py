from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import Blog, BlogAgentConfig, BloggerPost, Job, JobStatus, PostStatus, PublishMode, Topic, WorkflowStageType
from app.services.content.article_pattern_service import (
    build_article_pattern_prompt_block,
    select_blogger_article_pattern,
)
from app.services.ops.audit_service import add_log
from app.services.ops.model_policy_service import CODEX_TEXT_RUNTIME_KIND, CODEX_TEXT_RUNTIME_MODEL
from app.services.content.prompt_service import render_prompt_template
from app.services.integrations.settings_service import get_settings_map, upsert_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkflowStageDefinition:
    stage_type: WorkflowStageType
    label: str
    prompt_enabled: bool
    is_required: bool
    removable: bool
    provider_hint: str | None
    provider_model: str | None
    default_name: str
    default_role_name: str
    default_objective: str


@dataclass(frozen=True, slots=True)
class WorkflowStepBlueprint:
    stage_type: WorkflowStageType
    name: str
    role_name: str
    objective: str
    prompt_file: str | None
    provider_hint: str | None
    provider_model: str | None
    is_enabled: bool
    sort_order: int


@dataclass(frozen=True, slots=True)
class BlogProfile:
    key: str
    label: str
    description: str
    content_category: str
    primary_language: str
    target_audience: str
    content_brief: str
    publish_mode: PublishMode
    workflow_steps: tuple[WorkflowStepBlueprint, ...]


@dataclass(frozen=True, slots=True)
class DemoBlogBlueprint:
    slug: str
    name: str
    description: str
    profile_key: str
    is_active: bool = True


@dataclass(slots=True)
class BlogSummaryMetrics:
    job_count: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    published_posts: int = 0
    latest_topic_keywords: list[str] = field(default_factory=list)
    latest_published_url: str | None = None


CANONICAL_STAGE_ORDER: tuple[WorkflowStageType, ...] = (
    WorkflowStageType.TOPIC_DISCOVERY,
    WorkflowStageType.ARTICLE_GENERATION,
    WorkflowStageType.IMAGE_PROMPT_GENERATION,
    WorkflowStageType.RELATED_POSTS,
    WorkflowStageType.IMAGE_GENERATION,
    WorkflowStageType.HTML_ASSEMBLY,
    WorkflowStageType.PUBLISHING,
)

WORKFLOW_DEPENDENCIES: tuple[tuple[WorkflowStageType, WorkflowStageType], ...] = (
    (WorkflowStageType.TOPIC_DISCOVERY, WorkflowStageType.ARTICLE_GENERATION),
    (WorkflowStageType.ARTICLE_GENERATION, WorkflowStageType.IMAGE_PROMPT_GENERATION),
    (WorkflowStageType.ARTICLE_GENERATION, WorkflowStageType.RELATED_POSTS),
    (WorkflowStageType.ARTICLE_GENERATION, WorkflowStageType.IMAGE_GENERATION),
    (WorkflowStageType.IMAGE_PROMPT_GENERATION, WorkflowStageType.IMAGE_GENERATION),
    (WorkflowStageType.RELATED_POSTS, WorkflowStageType.HTML_ASSEMBLY),
    (WorkflowStageType.IMAGE_GENERATION, WorkflowStageType.HTML_ASSEMBLY),
    (WorkflowStageType.HTML_ASSEMBLY, WorkflowStageType.PUBLISHING),
)

USER_VISIBLE_STAGE_ORDER: tuple[WorkflowStageType, ...] = (
    WorkflowStageType.TOPIC_DISCOVERY,
    WorkflowStageType.ARTICLE_GENERATION,
    WorkflowStageType.IMAGE_PROMPT_GENERATION,
)

SYSTEM_STAGE_ORDER: tuple[WorkflowStageType, ...] = (
    WorkflowStageType.IMAGE_GENERATION,
    WorkflowStageType.HTML_ASSEMBLY,
    WorkflowStageType.PUBLISHING,
)

STAGE_DEFINITIONS: dict[WorkflowStageType, WorkflowStageDefinition] = {
    WorkflowStageType.TOPIC_DISCOVERY: WorkflowStageDefinition(
        stage_type=WorkflowStageType.TOPIC_DISCOVERY,
        label="주제 발굴",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint=None,
        provider_model=None,
        default_name="주제 발굴 에이전트",
        default_role_name="Trend Discovery Agent",
        default_objective="국가와 독자층에 맞는 검색 수요 주제를 찾아 작업 대기열을 채웁니다.",
    ),
    WorkflowStageType.ARTICLE_GENERATION: WorkflowStageDefinition(
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        label="글쓰기 패키지",
        prompt_enabled=True,
        is_required=True,
        removable=False,
        provider_hint=None,
        provider_model=None,
        default_name="글쓰기 패키지 에이전트",
        default_role_name="SEO Writing Package Agent",
        default_objective="제목, 검색 설명, 라벨, 슬러그, 본문, FAQ, 기본 이미지 프롬프트를 한 번에 생성합니다.",
    ),
    WorkflowStageType.IMAGE_PROMPT_GENERATION: WorkflowStageDefinition(
        stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
        label="이미지 프롬프트 정교화",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint=None,
        provider_model=None,
        default_name="이미지 프롬프트 정교화 에이전트",
        default_role_name="Image Prompt Refinement Agent",
        default_objective="글쓰기 패키지 결과에 포함된 기본 이미지 프롬프트를 더 세밀한 장면 지시로 다듬습니다.",
    ),
    WorkflowStageType.RELATED_POSTS: WorkflowStageDefinition(
        stage_type=WorkflowStageType.RELATED_POSTS,
        label="관련 글 구성",
        prompt_enabled=False,
        is_required=False,
        removable=False,
        provider_hint=None,
        provider_model=None,
        default_name="관련 글 시스템 단계",
        default_role_name="System Related Posts Step",
        default_objective="관련 글 후보를 찾아 HTML 조립 단계에 연결합니다.",
    ),
    WorkflowStageType.IMAGE_GENERATION: WorkflowStageDefinition(
        stage_type=WorkflowStageType.IMAGE_GENERATION,
        label="이미지 생성",
        prompt_enabled=False,
        is_required=True,
        removable=False,
        provider_hint="openai_image",
        provider_model="gpt-image-1",
        default_name="이미지 생성 시스템 단계",
        default_role_name="System Image Generation Step",
        default_objective="이미지 프롬프트를 기반으로 대표 이미지를 생성합니다.",
    ),
    WorkflowStageType.HTML_ASSEMBLY: WorkflowStageDefinition(
        stage_type=WorkflowStageType.HTML_ASSEMBLY,
        label="HTML 조립",
        prompt_enabled=False,
        is_required=True,
        removable=False,
        provider_hint=None,
        provider_model=None,
        default_name="HTML 조립 시스템 단계",
        default_role_name="System HTML Assembly Step",
        default_objective="대표 이미지, 본문, FAQ, 관련 글을 조합해 최종 HTML을 완성합니다.",
    ),
    WorkflowStageType.PUBLISHING: WorkflowStageDefinition(
        stage_type=WorkflowStageType.PUBLISHING,
        label="게시 대기",
        prompt_enabled=False,
        is_required=True,
        removable=False,
        provider_hint="blogger",
        provider_model="blogger-v3",
        default_name="게시 대기 시스템 단계",
        default_role_name="System Publishing Step",
        default_objective="최종 HTML을 게시 가능한 상태로 준비하고, 실제 공개 게시 입력을 기다립니다.",
    ),
    WorkflowStageType.VIDEO_METADATA_GENERATION: WorkflowStageDefinition(
        stage_type=WorkflowStageType.VIDEO_METADATA_GENERATION,
        label="영상 메타데이터",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint="claude_cli",
        provider_model="claude-sonnet",
        default_name="영상 메타데이터 에이전트",
        default_role_name="Video Metadata Agent",
        default_objective="영상 제목, 설명, 태그, 챕터 초안을 생성합니다.",
    ),
    WorkflowStageType.THUMBNAIL_GENERATION: WorkflowStageDefinition(
        stage_type=WorkflowStageType.THUMBNAIL_GENERATION,
        label="썸네일 전략",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint="gemini_cli",
        provider_model="gemini-2.5-flash",
        default_name="썸네일 전략 에이전트",
        default_role_name="Thumbnail Strategy Agent",
        default_objective="플랫폼별 썸네일 또는 커버 전략을 생성합니다.",
    ),
    WorkflowStageType.REEL_PACKAGING: WorkflowStageDefinition(
        stage_type=WorkflowStageType.REEL_PACKAGING,
        label="릴스 패키징",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint="codex_cli",
        provider_model="gpt-5",
        default_name="릴스 패키징 에이전트",
        default_role_name="Reel Packaging Agent",
        default_objective="릴스 자막, 후킹 카피, 미디어 패키지 지시를 정리합니다.",
    ),
    WorkflowStageType.PLATFORM_PUBLISH: WorkflowStageDefinition(
        stage_type=WorkflowStageType.PLATFORM_PUBLISH,
        label="플랫폼 게시",
        prompt_enabled=False,
        is_required=False,
        removable=True,
        provider_hint="codex_cli",
        provider_model="gpt-5",
        default_name="플랫폼 게시 에이전트",
        default_role_name="Platform Publish Agent",
        default_objective="플랫폼별 업로드와 게시 전환 단계를 준비합니다.",
    ),
    WorkflowStageType.PERFORMANCE_REVIEW: WorkflowStageDefinition(
        stage_type=WorkflowStageType.PERFORMANCE_REVIEW,
        label="성과 분석",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint=CODEX_TEXT_RUNTIME_KIND,
        provider_model=CODEX_TEXT_RUNTIME_MODEL,
        default_name="성과 분석 에이전트",
        default_role_name="Performance Review Agent",
        default_objective="CTR, 시청 유지율, 참여율 기반 피드백을 생성합니다.",
    ),
    WorkflowStageType.SEO_REWRITE: WorkflowStageDefinition(
        stage_type=WorkflowStageType.SEO_REWRITE,
        label="SEO 재작성",
        prompt_enabled=True,
        is_required=False,
        removable=True,
        provider_hint=CODEX_TEXT_RUNTIME_KIND,
        provider_model=CODEX_TEXT_RUNTIME_MODEL,
        default_name="SEO 재작성 에이전트",
        default_role_name="SEO Rewrite Agent",
        default_objective="검색 성과와 피드백을 바탕으로 제목과 본문을 재작성합니다.",
    ),
    WorkflowStageType.INDEXING_CHECK: WorkflowStageDefinition(
        stage_type=WorkflowStageType.INDEXING_CHECK,
        label="색인 점검",
        prompt_enabled=False,
        is_required=False,
        removable=True,
        provider_hint="google_search_console",
        provider_model="search-console-v1",
        default_name="색인 점검 시스템 단계",
        default_role_name="Indexing Check Step",
        default_objective="사이트맵 제출, 검사, 재시도 큐 연결을 위한 색인 상태를 확인합니다.",
    ),
}


def _prompt_roots() -> tuple[Path, ...]:
    resolved = Path(__file__).resolve()
    candidates: list[Path] = []
    seed_candidates = [
        Path(settings.prompt_root),
        Path.cwd() / "prompts",
    ]
    seed_candidates.extend(parent / "prompts" for parent in resolved.parents)
    for candidate in seed_candidates:
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


@lru_cache(maxsize=1)
def _blogger_prompt_folder_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for root in _prompt_roots():
        blogger_root = root / "channels" / "blogger"
        if not blogger_root.exists():
            continue
        for channel_file in blogger_root.glob("*/channel.json"):
            try:
                payload = json.loads(channel_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            channel_id = str(payload.get("channel_id") or "").strip()
            folder_name = channel_file.parent.name
            if channel_id.startswith("blogger:") and channel_id not in mapping:
                mapping[channel_id] = folder_name
    return mapping


def _blogger_prompt_folder_candidates(blog: Blog | None) -> tuple[str, ...]:
    if blog is None:
        return ()
    candidates: list[str] = []
    channel_id = f"blogger:{getattr(blog, 'id', '')}".strip()
    mapped_folder = _blogger_prompt_folder_map().get(channel_id)
    if mapped_folder:
        candidates.append(mapped_folder)
    for raw in (
        getattr(blog, "name", None),
        getattr(blog, "slug", None),
        getattr(blog, "profile_key", None),
    ):
        normalized = slugify(str(raw or "").strip(), separator="-")
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return tuple(candidates)


def _prompt_path(file_name: str, *, blog: Blog | None = None) -> Path:
    normalized = str(file_name or "").strip()
    roots = _prompt_roots()
    for root in roots:
        direct = root / normalized
        if direct.exists():
            return direct
        if blog is not None:
            for folder_name in _blogger_prompt_folder_candidates(blog):
                nested = root / "channels" / "blogger" / folder_name / normalized
                if nested.exists():
                    return nested
    return roots[0] / normalized


def _load_prompt_file(file_name: str | None, *, blog: Blog | None = None) -> str:
    if not file_name:
        return ""
    return _prompt_path(file_name, blog=blog).read_text(encoding="utf-8").strip() + "\n"


PROFILE_DEFINITIONS: dict[str, BlogProfile] = {
    "korea_travel": BlogProfile(
        key="korea_travel",
        label="Korea Travel",
        description="외국인을 위한 한국 여행, 행사, 문화, 맛집 블로그",
        content_category="travel",
        primary_language="en",
        target_audience="First-time international visitors planning a Korea trip",
        content_brief=(
            "한국을 처음 방문하는 외국인이 바로 사용할 수 있는 실전형 여행/행사 가이드를 운영합니다. "
            "교통, 예산, 일정, 문화 예절, 맛집, K-culture, 행사 정보를 현지인 시선으로 안내합니다."
        ),
        publish_mode=PublishMode.DRAFT,
        workflow_steps=(
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.TOPIC_DISCOVERY,
                name="여행 트렌드 발굴 에이전트",
                role_name="Korea Travel Trend Scout",
                objective="외국인에게 인기 있는 한국 여행 검색 수요 주제를 찾습니다.",
                prompt_file="travel_topic_discovery.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=10,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.ARTICLE_GENERATION,
                name="SEO 글쓰기 패키지 에이전트",
                role_name="Donggri, a local Korea travel insider",
                objective="여행/축제/행사형 제목, 검색 설명, 태그, 본문, FAQ, 이미지 프롬프트를 한 번에 생성합니다.",
                prompt_file="travel_article_generation.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=20,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
                name="여행 이미지 프롬프트 정교화 에이전트",
                role_name="Korea Travel Visual Director",
                objective="여행 주제에 맞는 3x3 패널 hero 대표 이미지 프롬프트를 더 정교하게 다듬습니다.",
                prompt_file="travel_collage_prompt.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=30,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.RELATED_POSTS,
                name="관련 글 시스템 단계",
                role_name="System Related Posts Step",
                objective="유사한 여행 글을 연결합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=40,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_GENERATION,
                name="이미지 생성 시스템 단계",
                role_name="System Image Generation Step",
                objective="여행 대표 이미지를 생성합니다.",
                prompt_file=None,
                provider_hint="openai_image",
                provider_model="gpt-image-1",
                is_enabled=True,
                sort_order=50,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.HTML_ASSEMBLY,
                name="HTML 조립 시스템 단계",
                role_name="System HTML Assembly Step",
                objective="본문과 대표 이미지를 최종 게시 형식으로 조립합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=60,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.PUBLISHING,
                name="게시 대기 시스템 단계",
                role_name="System Publishing Step",
                objective="최종 글을 게시 가능한 상태로 준비하고, 공개 게시 버튼 입력을 기다립니다.",
                prompt_file=None,
                provider_hint="blogger",
                provider_model="blogger-v3",
                is_enabled=True,
                sort_order=70,
            ),
        ),
    ),
    "world_mystery": BlogProfile(
        key="world_mystery",
        label="World Mystery",
        description="세계 미스터리, 다큐, 전설, 히스테리 중심 블로그",
        content_category="mystery",
        primary_language="en",
        target_audience="Global readers interested in mysteries, documentaries, legends, and unsolved cases",
        content_brief=(
            "세계 미스터리, 실화, 전설, 다큐멘터리형 스토리를 근거 중심으로 다룹니다. "
            "팩트, 가설, 반론, 최신 재해석을 균형 있게 정리해 체류 시간을 높이는 글을 만듭니다."
        ),
        publish_mode=PublishMode.DRAFT,
        workflow_steps=(
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.TOPIC_DISCOVERY,
                name="미스터리 트렌드 발굴 에이전트",
                role_name="Global Mystery Research Scout",
                objective="글로벌 검색 수요가 높은 세계 미스터리 주제를 찾습니다.",
                prompt_file="mystery_topic_discovery.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=10,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.ARTICLE_GENERATION,
                name="미스터리 글쓰기 패키지 에이전트",
                role_name="Investigative documentary storyteller",
                objective="제목, 검색 설명, 태그, 본문, FAQ, 이미지 프롬프트까지 포함한 미스터리 글쓰기 패키지를 생성합니다.",
                prompt_file="mystery_article_generation.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=20,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
                name="미스터리 이미지 프롬프트 정교화 에이전트",
                role_name="Documentary cover prompt designer",
                objective="사건 분위기에 맞는 3x3 다큐 스타일 hero 이미지 프롬프트를 더 정교하게 다듬습니다.",
                prompt_file="mystery_collage_prompt.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=30,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.RELATED_POSTS,
                name="관련 글 시스템 단계",
                role_name="System Related Posts Step",
                objective="연관 미스터리 글을 연결합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=40,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_GENERATION,
                name="이미지 생성 시스템 단계",
                role_name="System Image Generation Step",
                objective="대표 이미지를 생성합니다.",
                prompt_file=None,
                provider_hint="openai_image",
                provider_model="gpt-image-1",
                is_enabled=True,
                sort_order=50,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.HTML_ASSEMBLY,
                name="HTML 조립 시스템 단계",
                role_name="System HTML Assembly Step",
                objective="본문과 대표 이미지를 최종 게시 형식으로 조립합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=60,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.PUBLISHING,
                name="게시 대기 시스템 단계",
                role_name="System Publishing Step",
                objective="최종 글을 게시 가능한 상태로 준비하고, 공개 게시 버튼 입력을 기다립니다.",
                prompt_file=None,
                provider_hint="blogger",
                provider_model="blogger-v3",
                is_enabled=True,
                sort_order=70,
            ),
        ),
    ),
    "custom": BlogProfile(
        key="custom",
        label="Custom",
        description="직접 커스터마이즈하는 일반 블로그",
        content_category="custom",
        primary_language="en",
        target_audience="General global blog readers",
        content_brief="가져온 Blogger 블로그를 운영 방향에 맞게 직접 커스터마이즈합니다.",
        publish_mode=PublishMode.DRAFT,
        workflow_steps=(
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.TOPIC_DISCOVERY,
                name="기본 주제 발굴 에이전트",
                role_name="General Topic Discovery Agent",
                objective="블로그 주제에 맞는 검색 수요 키워드를 발굴합니다.",
                prompt_file="topic_discovery.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=10,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.ARTICLE_GENERATION,
                name="기본 글쓰기 패키지 에이전트",
                role_name="General SEO Article Agent",
                objective="선택한 블로그 주제에 맞는 제목, 검색 설명, 본문, FAQ, 이미지 프롬프트를 생성합니다.",
                prompt_file="article_generation.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=20,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
                name="기본 이미지 프롬프트 정교화 에이전트",
                role_name="General Image Prompt Agent",
                objective="본문 기반 대표 이미지 프롬프트를 추가로 정교화합니다.",
                prompt_file="collage_prompt.md",
                provider_hint=None,
                provider_model=None,
                is_enabled=False,
                sort_order=30,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.RELATED_POSTS,
                name="관련 글 시스템 단계",
                role_name="System Related Posts Step",
                objective="관련 글을 연결합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=40,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.IMAGE_GENERATION,
                name="이미지 생성 시스템 단계",
                role_name="System Image Generation Step",
                objective="대표 이미지를 생성합니다.",
                prompt_file=None,
                provider_hint="openai_image",
                provider_model="gpt-image-1",
                is_enabled=True,
                sort_order=50,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.HTML_ASSEMBLY,
                name="HTML 조립 시스템 단계",
                role_name="System HTML Assembly Step",
                objective="최종 HTML을 조립합니다.",
                prompt_file=None,
                provider_hint=None,
                provider_model=None,
                is_enabled=True,
                sort_order=60,
            ),
            WorkflowStepBlueprint(
                stage_type=WorkflowStageType.PUBLISHING,
                name="게시 대기 시스템 단계",
                role_name="System Publishing Step",
                objective="최종 글을 게시 가능한 상태로 준비하고, 공개 게시 버튼 입력을 기다립니다.",
                prompt_file=None,
                provider_hint="blogger",
                provider_model="blogger-v3",
                is_enabled=True,
                sort_order=70,
            ),
        ),
    ),
}

DEMO_BLOG_BLUEPRINTS: tuple[DemoBlogBlueprint, ...] = (
    DemoBlogBlueprint(
        slug="korea-travel-and-events",
        name="Korea Travel & Events",
        description="외국인을 위한 한국 여행 및 행사 정보 블로그",
        profile_key="korea_travel",
    ),
    DemoBlogBlueprint(
        slug="world-mystery-documentary",
        name="World Mystery Documentary",
        description="세계 미스터리와 다큐멘터리형 스토리를 다루는 블로그",
        profile_key="world_mystery",
    ),
)


def _demo_blog_slugs() -> tuple[str, ...]:
    return tuple(blueprint.slug for blueprint in DEMO_BLOG_BLUEPRINTS)


def _resolve_provider_mode(db: Session, provider_mode: str | None = None) -> str:
    if provider_mode:
        return provider_mode.lower()
    return get_settings_map(db).get("provider_mode", settings.provider_mode).lower()


def _apply_visible_blog_filter(statement, *, provider_mode: str) -> object:
    if provider_mode != "live":
        return statement
    return statement.where(~((Blog.slug.in_(_demo_blog_slugs())) & Blog.blogger_blog_id.is_(None)))


def is_legacy_demo_blog(blog: Blog) -> bool:
    return blog.slug in _demo_blog_slugs() and not (blog.blogger_blog_id or "").strip()


def get_stage_definition(stage_type: WorkflowStageType) -> WorkflowStageDefinition:
    return STAGE_DEFINITIONS[stage_type]


def get_profile_definition(profile_key: str) -> BlogProfile:
    return PROFILE_DEFINITIONS.get(profile_key, PROFILE_DEFINITIONS["custom"])


def list_blog_profiles() -> list[dict]:
    return [
        {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "content_category": profile.content_category,
            "primary_language": profile.primary_language,
            "target_audience": profile.target_audience,
        }
        for profile in PROFILE_DEFINITIONS.values()
    ]


def stage_supports_prompt(stage_type: WorkflowStageType) -> bool:
    return STAGE_DEFINITIONS[stage_type].prompt_enabled


def stage_is_required(stage_type: WorkflowStageType) -> bool:
    return STAGE_DEFINITIONS[stage_type].is_required


def stage_is_removable(stage_type: WorkflowStageType) -> bool:
    return STAGE_DEFINITIONS[stage_type].removable


def stage_label(stage_type: WorkflowStageType) -> str:
    return STAGE_DEFINITIONS[stage_type].label


def user_visible_stage_types() -> tuple[WorkflowStageType, ...]:
    return USER_VISIBLE_STAGE_ORDER


def system_stage_types() -> tuple[WorkflowStageType, ...]:
    return SYSTEM_STAGE_ORDER


def list_user_visible_steps(blog: Blog) -> list[BlogAgentConfig]:
    visible_types = set(USER_VISIBLE_STAGE_ORDER)
    return [step for step in list_workflow_steps(blog) if step.stage_type in visible_types]


def list_system_steps(blog: Blog) -> list[BlogAgentConfig]:
    system_types = set(SYSTEM_STAGE_ORDER)
    return [step for step in list_workflow_steps(blog) if step.stage_type in system_types]


def _get_enabled_step_state(blog: Blog, stage_type: WorkflowStageType) -> bool:
    step = get_workflow_step(blog, stage_type)
    return bool(step and step.is_enabled)


def get_execution_path_labels(blog: Blog) -> list[str]:
    steps = list_workflow_steps(blog)
    labels: list[str] = []
    if get_workflow_step(blog, WorkflowStageType.TOPIC_DISCOVERY) and _get_enabled_step_state(blog, WorkflowStageType.TOPIC_DISCOVERY):
        labels.append("1. 주제 발굴")
        offset = 2
    else:
        offset = 1

    labels.append(f"{offset}. 글쓰기 패키지")
    next_index = offset + 1

    if get_workflow_step(blog, WorkflowStageType.IMAGE_PROMPT_GENERATION) and _get_enabled_step_state(
        blog, WorkflowStageType.IMAGE_PROMPT_GENERATION
    ):
        labels.append(f"{next_index}. 이미지 프롬프트 정교화")
        next_index += 1

    labels.extend(
        [
            f"{next_index}. 이미지 생성",
            f"{next_index + 1}. HTML 조립",
            f"{next_index + 2}. 게시 대기",
        ]
    )
    return labels


def _stage_rank(stage_type: WorkflowStageType) -> int:
    return CANONICAL_STAGE_ORDER.index(stage_type)


def _resolve_profile_key(blog: Blog) -> str:
    if (blog.profile_key or "").strip():
        return blog.profile_key
    if blog.content_category == "travel":
        return "korea_travel"
    if blog.content_category == "mystery":
        return "world_mystery"
    return "custom"


def _workflow_blueprint_map(profile_key: str) -> dict[WorkflowStageType, WorkflowStepBlueprint]:
    return {step.stage_type: step for step in get_profile_definition(profile_key).workflow_steps}


def _build_step_defaults(profile_key: str, stage_type: WorkflowStageType, *, blog: Blog | None = None) -> dict:
    definition = get_stage_definition(stage_type)
    blueprint = _workflow_blueprint_map(profile_key).get(stage_type)
    if blueprint:
        return {
            "agent_key": stage_type.value,
            "stage_type": stage_type,
            "name": blueprint.name,
            "role_name": blueprint.role_name,
            "objective": blueprint.objective,
            "prompt_template": _load_prompt_file(blueprint.prompt_file, blog=blog),
            "provider_hint": blueprint.provider_hint,
            "provider_model": blueprint.provider_model,
            "is_enabled": blueprint.is_enabled,
            "is_required": definition.is_required,
            "sort_order": blueprint.sort_order,
        }

    return {
        "agent_key": stage_type.value,
        "stage_type": stage_type,
        "name": definition.default_name,
        "role_name": definition.default_role_name,
        "objective": definition.default_objective,
        "prompt_template": "",
        "provider_hint": definition.provider_hint,
        "provider_model": definition.provider_model,
        "is_enabled": definition.is_required,
        "is_required": definition.is_required,
        "sort_order": (_stage_rank(stage_type) + 1) * 10,
    }


def _normalize_workflow_sort_order(steps: list[BlogAgentConfig]) -> None:
    for index, step in enumerate(sorted(steps, key=lambda item: (item.sort_order, item.id or 0)), start=1):
        step.sort_order = index * 10


def validate_workflow_steps(steps: list[BlogAgentConfig]) -> None:
    enabled_steps = [step for step in sorted(steps, key=lambda item: (item.sort_order, item.id or 0)) if step.is_enabled]
    enabled_stage_index = {step.stage_type: idx for idx, step in enumerate(enabled_steps)}

    for stage_type in CANONICAL_STAGE_ORDER:
        definition = get_stage_definition(stage_type)
        current = next((step for step in steps if step.stage_type == stage_type), None)
        if definition.is_required:
            if not current:
                raise ValueError(f"필수 단계 '{definition.label}'가 없습니다.")
            if not current.is_enabled:
                raise ValueError(f"필수 단계 '{definition.label}'는 비활성화할 수 없습니다.")

    for step in enabled_steps:
        if stage_supports_prompt(step.stage_type) and len(step.prompt_template.strip()) < 20:
            raise ValueError(f"'{stage_label(step.stage_type)}' 단계의 프롬프트가 너무 짧습니다.")

    for before_stage, after_stage in WORKFLOW_DEPENDENCIES:
        if before_stage not in enabled_stage_index or after_stage not in enabled_stage_index:
            continue
        if enabled_stage_index[before_stage] > enabled_stage_index[after_stage]:
            raise ValueError(
                f"'{stage_label(before_stage)}' 단계는 '{stage_label(after_stage)}' 단계보다 앞에 있어야 합니다."
            )


def _workflow_options() -> list:
    return [selectinload(Blog.agent_configs)]


def list_blogs(db: Session, *, provider_mode: str | None = None) -> list[Blog]:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    query = select(Blog).options(*_workflow_options()).order_by(Blog.created_at.asc(), Blog.id.asc())
    query = _apply_visible_blog_filter(query, provider_mode=resolved_provider_mode)
    return db.execute(query).scalars().unique().all()


def list_active_blogs(db: Session, *, provider_mode: str | None = None) -> list[Blog]:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    query = (
        select(Blog)
        .where(Blog.is_active.is_(True))
        .options(selectinload(Blog.agent_configs))
        .order_by(Blog.created_at.asc(), Blog.id.asc())
    )
    query = _apply_visible_blog_filter(query, provider_mode=resolved_provider_mode)
    return db.execute(query).scalars().unique().all()


def list_connected_blogs(db: Session, *, provider_mode: str | None = None) -> list[Blog]:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    query = (
        select(Blog)
        .where(Blog.is_active.is_(True))
        .where(Blog.blogger_blog_id.is_not(None))
        .where(Blog.blogger_blog_id != "")
        .options(selectinload(Blog.agent_configs))
        .order_by(Blog.created_at.asc(), Blog.id.asc())
    )
    query = _apply_visible_blog_filter(query, provider_mode=resolved_provider_mode)
    return db.execute(query).scalars().unique().all()


def list_visible_blog_ids(db: Session, *, provider_mode: str | None = None) -> list[int]:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    query = select(Blog.id).order_by(Blog.created_at.asc(), Blog.id.asc())
    query = _apply_visible_blog_filter(query, provider_mode=resolved_provider_mode)
    return [int(blog_id) for blog_id in db.execute(query).scalars().all()]


def get_blog(db: Session, blog_id: int, *, provider_mode: str | None = None) -> Blog | None:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    query = select(Blog).where(Blog.id == blog_id).options(*_workflow_options())
    query = _apply_visible_blog_filter(query, provider_mode=resolved_provider_mode)
    return db.execute(query).scalar_one_or_none()


def get_blog_by_slug(db: Session, slug: str) -> Blog | None:
    query = select(Blog).where(Blog.slug == slug).options(selectinload(Blog.agent_configs))
    return db.execute(query).scalar_one_or_none()


def get_blog_by_remote_id(db: Session, blogger_blog_id: str) -> Blog | None:
    query = select(Blog).where(Blog.blogger_blog_id == blogger_blog_id).options(selectinload(Blog.agent_configs))
    return db.execute(query).scalar_one_or_none()


def get_workflow_step(blog: Blog, stage_type: WorkflowStageType) -> BlogAgentConfig | None:
    return next((step for step in blog.agent_configs if step.stage_type == stage_type), None)


def get_agent_config(blog: Blog, agent_key: str) -> BlogAgentConfig | None:
    return next(
        (
            step
            for step in blog.agent_configs
            if step.agent_key == agent_key or step.stage_type.value == agent_key
        ),
        None,
    )


def require_agent_config(blog: Blog, agent_key: str) -> BlogAgentConfig:
    step = get_agent_config(blog, agent_key)
    if not step:
        raise KeyError(agent_key)
    return step


def list_workflow_steps(blog: Blog, *, enabled_only: bool = False) -> list[BlogAgentConfig]:
    steps = sorted(blog.agent_configs, key=lambda item: (item.sort_order, item.id or 0))
    if enabled_only:
        return [step for step in steps if step.is_enabled]
    return steps


def get_missing_optional_stage_types(blog: Blog) -> list[WorkflowStageType]:
    existing = {step.stage_type for step in blog.agent_configs}
    return [
        stage_type
        for stage_type in CANONICAL_STAGE_ORDER
        if stage_type not in existing and stage_is_removable(stage_type)
    ]


def _blogger_topic_prompt_policy(blog: Blog, *, editorial_category_label: str, editorial_category_guidance: str) -> str:
    profile_key = _resolve_profile_key(blog)
    lines = [
        "[Topic selection policy]",
        "- Treat the first candidate as the single best publishable topic for this run.",
        "- Make CTR intent obvious in the title seed without sounding spammy.",
        "- Keep the topic aligned with the current editorial category and target audience.",
        f"- Editorial category: {editorial_category_label or 'default'}.",
    ]
    if editorial_category_guidance:
        lines.append(f"- Category guidance: {editorial_category_guidance}")
    if profile_key == "korea_travel":
        lines.extend(
            [
                "- Prefer route flow, place choice, timing, crowd control, queue avoidance, and nearby combination logic.",
                "- Make the topic feel like a real travel blog entry, not a planning memo or audit note.",
            ]
        )
    elif profile_key == "world_mystery":
        lines.extend(
            [
                "- Prefer documentary-grade mystery subjects with concrete people, places, archives, institutions, or years.",
                "- Avoid vague fear-bait keywords with no identifiable subject.",
            ]
        )
    return "\n".join(lines) + "\n"


def _blogger_html_prompt_policy() -> str:
    return (
        "[HTML structure policy]\n"
        "- html_article must use only these tags: <section>, <article>, <div>, <aside>, <blockquote>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <span>, <br>, <hr>.\n"
        "- Allowed class presets only: callout, timeline, card-grid, fact-box, caution-box, quote-box, chat-thread, comparison-table, route-steps, event-checklist, policy-summary.\n"
        "- Do not output inline styles, scripts, forms, or iframe markup.\n"
        "- Do not output image tags in html_article. The system injects visuals later.\n"
        "- FAQ belongs only at the end appendix and may appear once at most.\n"
        "- Return article_pattern_id and article_pattern_version in the JSON output.\n"
    )


def _blogger_article_prompt_policy(
    blog: Blog,
    *,
    editorial_category_label: str,
    editorial_category_guidance: str,
) -> str:
    profile_key = _resolve_profile_key(blog)
    lines = [
        "[Article editorial policy]",
        f"- Editorial category: {editorial_category_label or 'default'}.",
        "- Write a publish-ready blog post, not a score report, compliance memo, or operations checklist.",
        "- Keep meta_description out of visible body content.",
        "- Make headings feel natural and reader-facing.",
    ]
    if editorial_category_guidance:
        lines.append(f"- Category guidance: {editorial_category_guidance}")
    if profile_key == "korea_travel":
        lines.extend(
            [
                "- Use an experience-led travel blog tone with route logic, place context, and practical movement flow.",
                "- Make the article substantial enough for a full blog read, roughly equivalent to a 4000+ Korean-character post in density.",
                "- Prefer concrete district names, station areas, markets, museums, festivals, and nearby pairing ideas.",
            ]
        )
    elif profile_key == "world_mystery":
        lines.extend(
            [
                "- Use documentary-style narrative flow with setup, escalation, turning point, and present-day reading of the case.",
                "- Separate records, claims, and interpretation clearly.",
                "- Make the article substantial enough for a full blog read, roughly equivalent to a 4000+ Korean-character post in density.",
            ]
        )
    else:
        lines.append("- Keep the article substantial, readable, and specific enough to feel like a real blog post.")
    return "\n".join(lines) + "\n"


def _blogger_image_prompt_policy(blog: Blog) -> str:
    profile_key = _resolve_profile_key(blog)
    lines = [
        "[Image prompt policy]",
        "- Keep the hero image realistic and grounded in a real usage scene.",
        "- The hero prompt must describe one 3x3 collage with 9 distinct panels, visible white gutters, and a dominant center panel.",
        "- The supporting inline prompt must describe one 3x2 collage with 6 distinct panels.",
        "- No text, no logo, no infographic styling.",
    ]
    if profile_key == "korea_travel":
        lines.append("- Travel visuals must feel like a real place visit and avoid generic stock-photo mood.")
    elif profile_key == "world_mystery":
        lines.append("- Mystery visuals must feel documentary-like, with archive, place, and evidence atmosphere rather than fantasy poster styling.")
    return "\n".join(lines) + "\n"


def render_agent_prompt(db: Session | None, blog: Blog, agent: BlogAgentConfig, **replacements: str) -> str:
    local_now = datetime.now(ZoneInfo(settings.schedule_timezone))
    base_context = {
        "blog_name": blog.name,
        "blog_slug": blog.slug,
        "blog_description": blog.description or "",
        "content_category": blog.content_category,
        "primary_language": blog.primary_language,
        "target_audience": blog.target_audience or "",
        "content_brief": blog.content_brief or "",
        "planner_brief": "",
        "blogger_url": blog.blogger_url or "",
        "current_date": f"{local_now:%B} {local_now.day}, {local_now:%Y} ({settings.schedule_timezone})",
        "target_reading_time_min_minutes": str(blog.target_reading_time_min_minutes),
        "target_reading_time_max_minutes": str(blog.target_reading_time_max_minutes),
    }
    base_context.update(replacements)
    rendered = render_prompt_template(agent.prompt_template, **base_context)
    editorial_category_key = str(base_context.get("editorial_category_key") or "").strip()
    editorial_category_label = str(base_context.get("editorial_category_label") or "").strip()
    editorial_category_guidance = str(base_context.get("editorial_category_guidance") or "").strip()
    if agent.stage_type == WorkflowStageType.TOPIC_DISCOVERY:
        rendered = f"{rendered.rstrip()}\n\n{_blogger_topic_prompt_policy(blog, editorial_category_label=editorial_category_label, editorial_category_guidance=editorial_category_guidance)}"
    if agent.stage_type == WorkflowStageType.ARTICLE_GENERATION:
        if db is not None:
            selection = select_blogger_article_pattern(
                db,
                blog_id=blog.id,
                profile_key=_resolve_profile_key(blog),
                editorial_category_key=editorial_category_key,
            )
            rendered = (
                f"{rendered.rstrip()}\n\n"
                f"{build_article_pattern_prompt_block(selection)}\n"
                f"{_blogger_article_prompt_policy(blog, editorial_category_label=editorial_category_label, editorial_category_guidance=editorial_category_guidance)}\n"
                f"{_blogger_html_prompt_policy()}\n"
            )
        else:
            rendered = (
                f"{rendered.rstrip()}\n\n"
                f"{_blogger_article_prompt_policy(blog, editorial_category_label=editorial_category_label, editorial_category_guidance=editorial_category_guidance)}\n"
                f"{_blogger_html_prompt_policy()}\n"
            )
        rendered = (
            f"{rendered.rstrip()}\n\n"
            "[Reading Time Target]\n"
            f"- Aim for about {blog.target_reading_time_min_minutes} to {blog.target_reading_time_max_minutes} minutes of reading time.\n"
            "- Keep the article detailed enough to sustain engagement without padding.\n"
        )
    if agent.stage_type == WorkflowStageType.IMAGE_PROMPT_GENERATION:
        rendered = f"{rendered.rstrip()}\n\n{_blogger_image_prompt_policy(blog)}"
    return rendered


def ensure_blog_workflow_steps(db: Session, blog: Blog) -> Blog:
    changed = False
    profile_key = _resolve_profile_key(blog)
    if blog.profile_key != profile_key:
        blog.profile_key = profile_key
        changed = True

    steps_by_stage = {step.stage_type: step for step in blog.agent_configs}
    for stage_type in CANONICAL_STAGE_ORDER:
        defaults = _build_step_defaults(profile_key, stage_type, blog=blog)
        step = steps_by_stage.get(stage_type)
        if not step:
            step = BlogAgentConfig(blog=blog, **defaults)
            db.add(step)
            steps_by_stage[stage_type] = step
            changed = True
            continue

        if step.agent_key != stage_type.value:
            step.agent_key = stage_type.value
            changed = True
        if step.is_required != stage_is_required(stage_type):
            step.is_required = stage_is_required(stage_type)
            changed = True
        if not (step.name or "").strip():
            step.name = defaults["name"]
            changed = True
        if not (step.role_name or "").strip():
            step.role_name = defaults["role_name"]
            changed = True
        if not (step.objective or "").strip():
            step.objective = defaults["objective"]
            changed = True
        if stage_supports_prompt(stage_type) and not (step.prompt_template or "").strip():
            step.prompt_template = defaults["prompt_template"]
            changed = True
        if not (step.provider_hint or "").strip() and defaults["provider_hint"]:
            step.provider_hint = defaults["provider_hint"]
            changed = True
        if (
            stage_type == WorkflowStageType.TOPIC_DISCOVERY
            and (step.provider_hint or "").strip().lower() == "gemini"
            and (step.provider_model or "").strip().lower() == "gemini-2.5-flash"
        ):
            step.provider_hint = defaults["provider_hint"]
            step.provider_model = defaults["provider_model"]
            changed = True
        if not (step.provider_model or "").strip() and defaults["provider_model"]:
            step.provider_model = defaults["provider_model"]
            changed = True
        if step.sort_order == 0:
            step.sort_order = defaults["sort_order"]
            changed = True
        if step.is_required and not step.is_enabled:
            step.is_enabled = True
            changed = True

    db.flush()
    steps = list(blog.agent_configs)
    before_orders = [step.sort_order for step in steps]
    _normalize_workflow_sort_order(steps)
    if [step.sort_order for step in steps] != before_orders:
        changed = True
    validate_workflow_steps(steps)
    if changed:
        db.add(blog)
        db.commit()
        db.refresh(blog)
    return blog


def ensure_all_blog_workflows(db: Session) -> None:
    blogs = db.execute(select(Blog).options(selectinload(Blog.agent_configs))).scalars().unique().all()
    for blog in blogs:
        if not blog.is_active and not str(blog.blogger_blog_id or "").strip():
            continue
        try:
            ensure_blog_workflow_steps(db, blog)
        except FileNotFoundError as exc:
            logger.warning("Skipping workflow auto-ensure for blog %s due to missing prompt file: %s", blog.id, exc)


def enforce_text_runtime_policy(db: Session) -> dict[str, object]:
    settings_map = get_settings_map(db)
    desired_settings = {
        "image_runtime_kind": "openai_image",
        "openai_usage_hard_cap_enabled": "true",
    }
    settings_updates = {
        key: value
        for key, value in desired_settings.items()
        if str(settings_map.get(key) or "").strip() != value
    }
    if settings_updates:
        upsert_settings(db, settings_updates)

    blogs = db.execute(select(Blog).options(selectinload(Blog.agent_configs))).scalars().unique().all()
    workflow_updates: list[dict[str, object]] = []
    standard_text_stage_types = {
        WorkflowStageType.TOPIC_DISCOVERY,
        WorkflowStageType.ARTICLE_GENERATION,
        WorkflowStageType.IMAGE_PROMPT_GENERATION,
    }
    refactor_stage_types = {
        WorkflowStageType.PERFORMANCE_REVIEW,
        WorkflowStageType.SEO_REWRITE,
    }
    for blog in blogs:
        profile = get_profile_definition(blog.profile_key)
        blueprint_by_stage = {item.stage_type: item for item in profile.workflow_steps}
        for step in blog.agent_configs:
            if step.stage_type not in standard_text_stage_types and step.stage_type not in refactor_stage_types:
                continue

            if step.stage_type in standard_text_stage_types:
                blueprint = blueprint_by_stage.get(step.stage_type)
                expected_hint = blueprint.provider_hint if blueprint else STAGE_DEFINITIONS[step.stage_type].provider_hint
                expected_model = blueprint.provider_model if blueprint else STAGE_DEFINITIONS[step.stage_type].provider_model
            else:
                expected_hint = CODEX_TEXT_RUNTIME_KIND
                expected_model = CODEX_TEXT_RUNTIME_MODEL
            current_hint = str(step.provider_hint or "").strip()
            current_model = str(step.provider_model or "").strip()
            normalized_expected_hint = str(expected_hint or "").strip()
            normalized_expected_model = str(expected_model or "").strip()
            if current_hint == normalized_expected_hint and current_model == normalized_expected_model:
                continue

            previous_model = current_model
            previous_hint = current_hint
            step.provider_hint = expected_hint
            step.provider_model = expected_model
            db.add(step)
            workflow_updates.append(
                {
                    "blog_id": blog.id,
                    "stage_type": step.stage_type.value,
                    "previous_hint": previous_hint,
                    "updated_hint": expected_hint,
                    "previous_model": previous_model,
                    "updated_model": expected_model,
                }
            )

    if workflow_updates:
        db.commit()

    if settings_updates or workflow_updates:
        add_log(
            db,
            job=None,
            stage="text_runtime_policy_sync",
            message="Synchronized standard text runtime settings and refactor-specific Codex workflow stages.",
            payload={
                "settings_updates": settings_updates,
                "workflow_updates": workflow_updates,
                "standard_text_runtime_kind": str(get_settings_map(db).get("text_runtime_kind") or "").strip() or None,
                "refactor_text_runtime_kind": CODEX_TEXT_RUNTIME_KIND,
                "refactor_text_runtime_model": CODEX_TEXT_RUNTIME_MODEL,
            },
        )
    return {
        "settings_updates": settings_updates,
        "workflow_updates": workflow_updates,
    }


def sync_stage_prompts_from_profile_files(
    db: Session,
    *,
    blog: Blog,
    stage_types: tuple[WorkflowStageType, ...] = (
        WorkflowStageType.ARTICLE_GENERATION,
        WorkflowStageType.IMAGE_PROMPT_GENERATION,
    ),
) -> list[dict[str, str]]:
    profile_key = _resolve_profile_key(blog)
    blueprint_map = _workflow_blueprint_map(profile_key)
    updates: list[dict[str, str]] = []

    for stage_type in stage_types:
        step = get_workflow_step(blog, stage_type)
        blueprint = blueprint_map.get(stage_type)
        if not step or not blueprint or not blueprint.prompt_file:
            continue
        prompt_from_file = _load_prompt_file(blueprint.prompt_file, blog=blog)
        if (step.prompt_template or "").strip() == prompt_from_file.strip():
            continue

        step.prompt_template = prompt_from_file
        db.add(step)
        updates.append(
            {
                "stage_type": stage_type.value,
                "agent_key": step.agent_key,
                "prompt_file": blueprint.prompt_file,
            }
        )

    if updates:
        db.commit()
        refreshed = get_blog(db, blog.id) or blog
        add_log(
            db,
            job=None,
            stage="workflow_prompt_sync",
            message=f"Synchronized workflow prompts from files for blog '{refreshed.name}'.",
            payload={"blog_id": refreshed.id, "profile_key": profile_key, "updates": updates},
        )
        return updates
    return []


def ensure_unique_blog_slug(db: Session, name: str, current_blog_id: int | None = None) -> str:
    slug = slugify(name) or "blog"
    candidate = slug
    counter = 2
    while True:
        existing = db.execute(select(Blog).where(Blog.slug == candidate)).scalar_one_or_none()
        if not existing or existing.id == current_blog_id:
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1


def _create_demo_blog(db: Session, blueprint: DemoBlogBlueprint) -> Blog:
    profile = get_profile_definition(blueprint.profile_key)
    blog = Blog(
        name=blueprint.name,
        slug=blueprint.slug,
        description=blueprint.description,
        content_category=profile.content_category,
        primary_language=profile.primary_language,
        profile_key=profile.key,
        target_audience=profile.target_audience,
        content_brief=profile.content_brief,
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
        publish_mode=profile.publish_mode,
        is_active=blueprint.is_active,
    )
    db.add(blog)
    db.flush()
    for stage_type in CANONICAL_STAGE_ORDER:
        db.add(BlogAgentConfig(blog_id=blog.id, **_build_step_defaults(profile.key, stage_type)))
    db.commit()
    db.refresh(blog)
    return blog


def ensure_default_blogs(db: Session, *, enable_demo: bool = True) -> None:
    if not enable_demo:
        return

    existing = {blog.slug: blog for blog in db.execute(select(Blog)).scalars().all()}
    for blueprint in DEMO_BLOG_BLUEPRINTS:
        if blueprint.slug in existing:
            continue
        _create_demo_blog(db, blueprint)


def disable_legacy_demo_blogs_for_live(db: Session) -> None:
    demo_blogs = db.execute(
        select(Blog).where(Blog.slug.in_(_demo_blog_slugs()), Blog.blogger_blog_id.is_(None), Blog.is_active.is_(True))
    ).scalars().all()
    if not demo_blogs:
        return
    for blog in demo_blogs:
        blog.is_active = False
        db.add(blog)
    db.commit()


def purge_legacy_demo_blogs(db: Session, *, provider_mode: str | None = None) -> None:
    resolved_provider_mode = _resolve_provider_mode(db, provider_mode)
    if resolved_provider_mode == "demo":
        ensure_default_blogs(db, enable_demo=True)
        return
    disable_legacy_demo_blogs_for_live(db)


def get_blog_summary_map(db: Session, blog_ids: list[int]) -> dict[int, BlogSummaryMetrics]:
    unique_ids = list(dict.fromkeys(blog_ids))
    summary_map = {blog_id: BlogSummaryMetrics() for blog_id in unique_ids}
    if not unique_ids:
        return summary_map

    job_rows = db.execute(
        select(Job.blog_id, Job.status, func.count(Job.id))
        .where(Job.blog_id.in_(unique_ids))
        .group_by(Job.blog_id, Job.status)
    ).all()
    for blog_id, status, count in job_rows:
        summary = summary_map[blog_id]
        summary.job_count += int(count)
        if status == JobStatus.COMPLETED:
            summary.completed_jobs += int(count)
        elif status == JobStatus.FAILED:
            summary.failed_jobs += int(count)

    post_count_rows = db.execute(
        select(BloggerPost.blog_id, func.count(BloggerPost.id))
        .where(BloggerPost.blog_id.in_(unique_ids), BloggerPost.post_status == PostStatus.PUBLISHED)
        .group_by(BloggerPost.blog_id)
    ).all()
    for blog_id, count in post_count_rows:
        summary_map[blog_id].published_posts = int(count)

    topic_rank = func.row_number().over(partition_by=Topic.blog_id, order_by=Topic.created_at.desc()).label("topic_rank")
    topic_subquery = (
        select(
            Topic.blog_id.label("blog_id"),
            Topic.keyword.label("keyword"),
            topic_rank,
        )
        .where(Topic.blog_id.in_(unique_ids))
        .subquery()
    )
    topic_rows = db.execute(
        select(topic_subquery.c.blog_id, topic_subquery.c.keyword)
        .where(topic_subquery.c.topic_rank <= 3)
        .order_by(topic_subquery.c.blog_id.asc(), topic_subquery.c.topic_rank.asc())
    ).all()
    for blog_id, keyword in topic_rows:
        summary_map[blog_id].latest_topic_keywords.append(keyword)

    post_rank = func.row_number().over(
        partition_by=BloggerPost.blog_id,
        order_by=[BloggerPost.published_at.desc().nullslast(), BloggerPost.created_at.desc()],
    ).label("post_rank")
    latest_post_subquery = (
        select(
            BloggerPost.blog_id.label("blog_id"),
            BloggerPost.published_url.label("published_url"),
            post_rank,
        )
        .where(BloggerPost.blog_id.in_(unique_ids), BloggerPost.post_status == PostStatus.PUBLISHED)
        .subquery()
    )
    latest_post_rows = db.execute(
        select(latest_post_subquery.c.blog_id, latest_post_subquery.c.published_url)
        .where(latest_post_subquery.c.post_rank == 1)
    ).all()
    for blog_id, published_url in latest_post_rows:
        summary_map[blog_id].latest_published_url = published_url

    return summary_map


def import_blog_from_remote(db: Session, remote_blog: dict, profile_key: str) -> Blog:
    remote_id = str(remote_blog.get("id", "")).strip()
    if not remote_id:
        raise ValueError("가져올 Blogger 블로그 ID가 없습니다.")
    if get_blog_by_remote_id(db, remote_id):
        raise ValueError("이미 가져온 Blogger 블로그입니다.")

    profile = get_profile_definition(profile_key)
    remote_name = (remote_blog.get("name") or "").strip() or "Imported Blogger Blog"
    blog = Blog(
        name=remote_name,
        slug=ensure_unique_blog_slug(db, remote_name),
        description=(remote_blog.get("description") or "").strip() or profile.description,
        content_category=profile.content_category,
        primary_language=profile.primary_language,
        profile_key=profile.key,
        target_audience=profile.target_audience,
        content_brief=profile.content_brief,
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
        blogger_blog_id=remote_id,
        blogger_url=(remote_blog.get("url") or "").strip() or None,
        publish_mode=profile.publish_mode,
        is_active=True,
    )
    db.add(blog)
    db.flush()

    for stage_type in CANONICAL_STAGE_ORDER:
        db.add(BlogAgentConfig(blog_id=blog.id, **_build_step_defaults(profile.key, stage_type)))

    db.commit()
    db.refresh(blog)
    return get_blog(db, blog.id) or blog


def update_blog(
    db: Session,
    blog: Blog,
    *,
    name: str,
    description: str | None,
    content_category: str,
    primary_language: str,
    target_audience: str | None,
    content_brief: str | None,
    target_reading_time_min_minutes: int,
    target_reading_time_max_minutes: int,
    publish_mode: PublishMode,
    is_active: bool,
) -> Blog:
    blog.name = name
    blog.slug = ensure_unique_blog_slug(db, name, current_blog_id=blog.id)
    blog.description = description
    blog.content_category = content_category
    blog.primary_language = primary_language
    blog.target_audience = target_audience
    blog.content_brief = content_brief
    blog.target_reading_time_min_minutes = target_reading_time_min_minutes
    blog.target_reading_time_max_minutes = max(target_reading_time_min_minutes, target_reading_time_max_minutes)
    blog.publish_mode = publish_mode
    blog.is_active = is_active
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def update_blog_connections(
    db: Session,
    blog: Blog,
    *,
    search_console_site_url: str | None,
    ga4_property_id: str | None,
) -> Blog:
    blog.search_console_site_url = search_console_site_url or None
    blog.ga4_property_id = ga4_property_id or None
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def update_blog_agent(
    db: Session,
    agent: BlogAgentConfig,
    *,
    name: str,
    role_name: str,
    objective: str | None,
    prompt_template: str,
    provider_hint: str | None,
    provider_model: str | None,
    is_enabled: bool,
) -> BlogAgentConfig:
    if agent.is_required and not is_enabled:
        raise ValueError(f"필수 단계 '{stage_label(agent.stage_type)}'는 비활성화할 수 없습니다.")

    agent.name = name
    agent.role_name = role_name
    agent.objective = objective
    agent.prompt_template = prompt_template.strip() + ("\n" if prompt_template.strip() else "")
    agent.provider_hint = provider_hint
    agent.provider_model = (provider_model or "").strip() or None
    agent.is_enabled = is_enabled if not agent.is_required else True
    validate_workflow_steps(list(agent.blog.agent_configs))
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def update_blog_seo_meta(
    db: Session,
    blog: Blog,
    *,
    seo_theme_patch_installed: bool,
) -> Blog:
    blog.seo_theme_patch_installed = seo_theme_patch_installed
    if not seo_theme_patch_installed:
        blog.seo_theme_patch_verified_at = None
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def mark_blog_seo_meta_verified(db: Session, blog: Blog, *, verified_at) -> Blog:
    blog.seo_theme_patch_verified_at = verified_at
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def clear_blog_seo_meta_verified(db: Session, blog: Blog) -> Blog:
    blog.seo_theme_patch_verified_at = None
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def apply_profile_preset(
    db: Session,
    blog: Blog,
    *,
    overwrite_prompts: bool,
) -> list[BlogAgentConfig]:
    profile_key = _resolve_profile_key(blog)
    blueprint_map = _workflow_blueprint_map(profile_key)

    for step in blog.agent_configs:
        definition = get_stage_definition(step.stage_type)
        blueprint = blueprint_map.get(step.stage_type)
        step.name = blueprint.name if blueprint else definition.default_name
        step.role_name = blueprint.role_name if blueprint else definition.default_role_name
        step.objective = blueprint.objective if blueprint else definition.default_objective
        step.provider_hint = blueprint.provider_hint if blueprint else definition.provider_hint
        step.provider_model = blueprint.provider_model if blueprint else definition.provider_model
        step.is_enabled = blueprint.is_enabled if blueprint else definition.is_required
        step.is_required = definition.is_required
        if overwrite_prompts and blueprint:
            step.prompt_template = _load_prompt_file(blueprint.prompt_file, blog=blog)
        db.add(step)

    _normalize_workflow_sort_order(list(blog.agent_configs))
    validate_workflow_steps(list(blog.agent_configs))
    db.commit()
    refreshed = get_blog(db, blog.id) or blog
    return list_workflow_steps(refreshed)


def create_workflow_step(db: Session, blog: Blog, stage_type: WorkflowStageType) -> BlogAgentConfig:
    if get_workflow_step(blog, stage_type):
        raise ValueError("이미 존재하는 단계입니다.")
    if not stage_is_removable(stage_type):
        raise ValueError("이 단계는 수동으로 추가할 수 없습니다.")

    payload = _build_step_defaults(_resolve_profile_key(blog), stage_type, blog=blog)
    step = BlogAgentConfig(blog_id=blog.id, **payload)
    db.add(step)
    db.flush()
    ordered = sorted(list(blog.agent_configs), key=lambda item: (_stage_rank(item.stage_type), item.id or 0))
    _normalize_workflow_sort_order(ordered)
    validate_workflow_steps(ordered)
    db.commit()
    db.refresh(step)
    return step


def delete_workflow_step(db: Session, blog: Blog, step: BlogAgentConfig) -> None:
    if step.is_required or not stage_is_removable(step.stage_type):
        raise ValueError("이 단계는 제거할 수 없습니다.")
    db.delete(step)
    db.flush()
    remaining = list(blog.agent_configs)
    _normalize_workflow_sort_order(remaining)
    validate_workflow_steps(remaining)
    db.commit()


def reorder_workflow_steps(db: Session, blog: Blog, ordered_ids: list[int]) -> list[BlogAgentConfig]:
    steps = list(blog.agent_configs)
    if {step.id for step in steps} != set(ordered_ids):
        raise ValueError("전달된 단계 목록이 현재 블로그의 단계와 일치하지 않습니다.")

    steps_by_id = {step.id: step for step in steps}
    ordered_steps = [steps_by_id[step_id] for step_id in ordered_ids]
    _normalize_workflow_sort_order(ordered_steps)
    validate_workflow_steps(ordered_steps)
    for step in ordered_steps:
        db.add(step)
    db.commit()
    refreshed = get_blog(db, blog.id) or blog
    return list_workflow_steps(refreshed)
