from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, Job, JobStatus, Topic
from app.schemas.ai import TopicDiscoveryItem
from app.services.content.topic_guard_service import build_topic_memory_exclusion_prompt


class DuplicateContentError(ValueError):
    pass


@dataclass(slots=True)
class DuplicateMatch:
    source_type: str
    source_id: int | None
    value: str
    reason: str


def _normalize(value: str | None) -> str:
    normalized = slugify(value or "", separator=" ")
    return " ".join(normalized.split()).strip()


def _is_similar(candidate: str, existing: str) -> bool:
    candidate_norm = _normalize(candidate)
    existing_norm = _normalize(existing)
    if not candidate_norm or not existing_norm:
        return False
    if candidate_norm == existing_norm:
        return True

    candidate_compact = candidate_norm.replace(" ", "")
    existing_compact = existing_norm.replace(" ", "")
    if len(candidate_compact) >= 14 and (
        candidate_compact in existing_compact or existing_compact in candidate_compact
    ):
        return True

    ratio = SequenceMatcher(None, candidate_norm, existing_norm).ratio()
    return ratio >= 0.9


def _iter_existing_job_candidates(db: Session, blog_id: int):
    rows = db.execute(
        select(Job, Article.id)
        .outerjoin(Article, Article.job_id == Job.id)
        .where(Job.blog_id == blog_id)
    ).all()
    for job, article_id in rows:
        if article_id is not None:
            continue
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED}:
            continue
        yield DuplicateMatch("job", job.id, job.keyword_snapshot, "이미 진행 중인 작업 키워드와 겹칩니다.")


def _iter_existing_candidates(db: Session, blog_id: int, *, include_topics: bool = True):
    if include_topics:
        topics = db.execute(select(Topic).where(Topic.blog_id == blog_id)).scalars().all()
        for topic in topics:
            yield DuplicateMatch("topic", topic.id, topic.keyword, "이미 저장한 주제 후보와 겹칩니다.")

    articles = db.execute(select(Article).where(Article.blog_id == blog_id)).scalars().all()
    for article in articles:
        yield DuplicateMatch("article_title", article.id, article.title, "이미 생성된 글 제목과 겹칩니다.")
        yield DuplicateMatch("article_slug", article.id, article.slug, "이미 생성된 글 슬러그와 겹칩니다.")

    yield from _iter_existing_job_candidates(db, blog_id)


def _iter_existing_article_candidates(db: Session, blog_id: int):
    articles = db.execute(select(Article).where(Article.blog_id == blog_id)).scalars().all()
    for article in articles:
        yield DuplicateMatch("article_title", article.id, article.title, "이미 생성된 글 제목과 겹칩니다.")
        yield DuplicateMatch("article_slug", article.id, article.slug, "이미 생성된 글 슬러그와 겹칩니다.")


def find_duplicate_match(
    db: Session,
    *,
    blog_id: int,
    candidate: str,
    include_topics: bool = True,
    exclude_topic_id: int | None = None,
    exclude_job_id: int | None = None,
    exclude_article_id: int | None = None,
) -> DuplicateMatch | None:
    for item in _iter_existing_candidates(db, blog_id, include_topics=include_topics):
        if item.source_type == "topic" and item.source_id == exclude_topic_id:
            continue
        if item.source_type == "job" and item.source_id == exclude_job_id:
            continue
        if item.source_type.startswith("article_") and item.source_id == exclude_article_id:
            continue
        if _is_similar(candidate, item.value):
            return item
    return None


def filter_duplicate_topic_items(
    db: Session,
    *,
    blog_id: int,
    items: list[TopicDiscoveryItem],
    metadata_by_keyword: dict[str, dict[str, str]] | None = None,
) -> tuple[list[TopicDiscoveryItem], list[dict[str, str]]]:
    kept: list[TopicDiscoveryItem] = []
    skipped: list[dict[str, str]] = []
    accepted_keywords: list[str] = []
    accepted_cluster_angles: set[tuple[str, str]] = set()
    metadata_by_keyword = metadata_by_keyword or {}

    for item in items:
        intra_match = next((keyword for keyword in accepted_keywords if _is_similar(item.keyword, keyword)), None)
        if intra_match:
            skipped.append(
                {
                    "keyword": item.keyword,
                    "reason": f"같은 배치 안에서 이미 선택된 '{intra_match}'와 너무 비슷합니다.",
                }
            )
            continue

        metadata = metadata_by_keyword.get(item.keyword, {})
        cluster_key = _normalize(metadata.get("topic_cluster_key") or metadata.get("topic_cluster_label"))
        angle_key = _normalize(metadata.get("topic_angle_key") or metadata.get("topic_angle_label"))
        cluster_angle_pair = (cluster_key, angle_key)
        if cluster_key and angle_key and cluster_angle_pair in accepted_cluster_angles:
            skipped.append(
                {
                    "keyword": item.keyword,
                    "reason": (
                        "Another topic with the same main cluster and angle is already accepted in this batch. "
                        "Keep materially different angles only."
                    ),
                }
            )
            continue

        existing_match = find_duplicate_match(
            db,
            blog_id=blog_id,
            candidate=item.keyword,
            include_topics=False,
        )
        if existing_match:
            skipped.append(
                {
                    "keyword": item.keyword,
                    "reason": f"{existing_match.reason} 기준값: {existing_match.value}",
                }
            )
            continue

        kept.append(item)
        accepted_keywords.append(item.keyword)
        if cluster_key and angle_key:
            accepted_cluster_angles.add(cluster_angle_pair)

    return kept, skipped


def build_duplicate_exclusion_prompt(db: Session, *, blog_id: int, limit: int = 12) -> str:
    seen: list[str] = []
    for item in _iter_existing_candidates(db, blog_id):
        value = item.value.strip()
        if not value:
            continue
        if any(_is_similar(value, existing) for existing in seen):
            continue
        seen.append(value)
        if len(seen) >= limit:
            break

    sections: list[str] = []
    if seen:
        bullet_list = "\n".join(f"- {value}" for value in seen)
        sections.append(
            "\n\nAvoid duplicating or lightly rephrasing topics already covered in this blog.\n"
            "Do not return topics that substantially overlap with the following existing coverage:\n"
            f"{bullet_list}"
        )

    memory_prompt = build_topic_memory_exclusion_prompt(db, blog_id=blog_id, limit=limit)
    if memory_prompt:
        sections.append(memory_prompt)

    return "".join(sections)


def assert_article_not_duplicate(
    db: Session,
    *,
    blog_id: int,
    title: str,
    slug: str,
    exclude_article_id: int | None = None,
) -> None:
    title_match = next(
        (
            item
            for item in _iter_existing_article_candidates(db, blog_id)
            if item.source_id != exclude_article_id and _is_similar(title, item.value)
        ),
        None,
    )
    if title_match:
        raise DuplicateContentError(f"중복 글로 판단되어 저장을 중단했습니다. 기준값: {title_match.value}")

    slug_match = next(
        (
            item
            for item in _iter_existing_article_candidates(db, blog_id)
            if item.source_id != exclude_article_id and _is_similar(slug, item.value)
        ),
        None,
    )
    if slug_match:
        raise DuplicateContentError(f"중복 슬러그로 판단되어 저장을 중단했습니다. 기준값: {slug_match.value}")
