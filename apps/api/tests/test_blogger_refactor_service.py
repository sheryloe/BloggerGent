from types import SimpleNamespace

from app.services import blogger_refactor_service


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeDB:
    def __init__(self, synced_posts):
        self._synced_posts = synced_posts
        self.commits = 0
        self.rollbacks = 0

    def execute(self, _query):
        return _ScalarResult(self._synced_posts)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def add(self, _row):
        return None


def _blog():
    return SimpleNamespace(
        id=1,
        name="Travel Blog",
        blogger_blog_id="blog-1",
        content_category="travel",
        profile_key="korea_travel",
        primary_language="ko",
    )


def _agent():
    return SimpleNamespace(prompt_template="rewrite")


def _synced_post():
    return SimpleNamespace(
        id=101,
        blog_id=1,
        remote_post_id="remote-101",
        title="Old Seoul Walk Guide",
        url="https://blog.example.com/old-seoul-walk",
        status="published",
        published_at=None,
        content_html=(
            '<article><figure><img src="https://img.example.com/cover.jpg" /></figure>'
            '<p>old body</p><figure><img src="https://img.example.com/inline.jpg" /></figure></article>'
        ),
        excerpt_text="old excerpt",
        labels=["Travel"],
        thumbnail_url="https://img.example.com/cover.jpg",
    )


def test_refactor_blogger_low_score_posts_dry_run_filters_candidates(monkeypatch):
    post = _synced_post()
    db = _FakeDB([post])

    monkeypatch.setattr(blogger_refactor_service, "get_blog", lambda _db, _blog_id: _blog())
    monkeypatch.setattr(blogger_refactor_service, "ensure_blog_workflow_steps", lambda _db, blog: blog)
    monkeypatch.setattr(blogger_refactor_service, "get_workflow_step", lambda _blog, _stage: _agent())
    monkeypatch.setattr(blogger_refactor_service, "sync_blogger_posts_for_blog", lambda _db, _blog: {"status": "ok"})
    monkeypatch.setattr(blogger_refactor_service, "canonicalize_editorial_labels", lambda **_kwargs: ("travel", "Travel", ["Travel"]))
    monkeypatch.setattr(blogger_refactor_service, "render_agent_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(
        blogger_refactor_service,
        "get_blog_monthly_articles",
        lambda *_args, **_kwargs: SimpleNamespace(
            items=[
                SimpleNamespace(
                    id=1,
                    synced_post_id=101,
                    status="published",
                    seo_score=79.0,
                    geo_score=91.0,
                    ctr=1.2,
                    ctr_score=82.0,
                    lighthouse_score=88.0,
                    published_at="2026-04-10T10:00:00+09:00",
                )
            ],
            total=1,
        ),
    )

    result = blogger_refactor_service.refactor_blogger_low_score_posts(
        db,
        blog_id=1,
        execute=False,
        threshold=80.0,
        month="2026-04",
        sync_before=True,
    )

    assert result["status"] == "ok"
    assert result["total_candidates"] == 1
    assert result["processed_count"] == 1
    assert result["items"][0]["remote_post_id"] == "remote-101"
    assert result["items"][0]["action"] == "dry_run"


def test_refactor_blogger_low_score_posts_execute_reuses_existing_images(monkeypatch):
    post = _synced_post()
    db = _FakeDB([post])
    updated_payload = {}

    class _Provider:
        def update_post(self, *, post_id, title, content, labels, meta_description):
            updated_payload["post_id"] = post_id
            updated_payload["title"] = title
            updated_payload["content"] = content
            updated_payload["labels"] = labels
            updated_payload["meta_description"] = meta_description
            return {"id": post_id, "url": "https://blog.example.com/old-seoul-walk"}, {"status": "ok"}

    monkeypatch.setattr(blogger_refactor_service, "get_blog", lambda _db, _blog_id: _blog())
    monkeypatch.setattr(blogger_refactor_service, "ensure_blog_workflow_steps", lambda _db, blog: blog)
    monkeypatch.setattr(blogger_refactor_service, "get_workflow_step", lambda _blog, _stage: _agent())
    monkeypatch.setattr(blogger_refactor_service, "sync_blogger_posts_for_blog", lambda _db, _blog: {"status": "ok"})
    monkeypatch.setattr(blogger_refactor_service, "canonicalize_editorial_labels", lambda **_kwargs: ("travel", "Travel", ["Travel", "Seoul"]))
    monkeypatch.setattr(blogger_refactor_service, "render_agent_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(blogger_refactor_service, "get_runtime_config", lambda _db: SimpleNamespace())
    monkeypatch.setattr(blogger_refactor_service, "get_blogger_provider", lambda _db, _blog: _Provider())
    monkeypatch.setattr(
        blogger_refactor_service,
        "_generate_one",
        lambda candidate, **_kwargs: {
            "candidate": candidate,
            "output": SimpleNamespace(
                title="New Seoul Walk Guide",
                meta_description="A rewritten Seoul walk guide with clearer route logic and practical local tips.",
                labels=["Travel", "Seoul"],
                excerpt="A rewritten Seoul walk guide with route logic and practical tips.",
                html_article="<h2>Route</h2><p>new body</p><!--RELATED_POSTS-->",
                faq_section=[],
                article_pattern_id="travel-route",
                article_pattern_version=2,
            ),
            "predicted_scores": {"seo_score": 88.0, "geo_score": 86.0, "ctr_score": 84.0},
            "quality_attempts": [{"attempt": 1, "passed": True}],
        },
    )
    monkeypatch.setattr(
        blogger_refactor_service,
        "get_blog_monthly_articles",
        lambda *_args, **_kwargs: SimpleNamespace(
            items=[
                SimpleNamespace(
                    id=1,
                    synced_post_id=101,
                    status="published",
                    seo_score=79.0,
                    geo_score=76.0,
                    ctr=1.2,
                    ctr_score=71.0,
                    lighthouse_score=69.0,
                    published_at="2026-04-10T10:00:00+09:00",
                )
            ],
            total=1,
        ),
    )
    monkeypatch.setattr(
        blogger_refactor_service,
        "sync_blogger_post_search_description",
        lambda *_args, **_kwargs: SimpleNamespace(status="ok", message="synced", editor_url="editor"),
    )
    monkeypatch.setattr(
        blogger_refactor_service,
        "run_lighthouse_audit",
        lambda _url: {
            "scores": {
                "lighthouse_score": 85.0,
                "accessibility_score": 90.0,
                "best_practices_score": 88.0,
                "seo_score": 92.0,
            }
        },
    )
    monkeypatch.setattr(
        blogger_refactor_service,
        "send_telegram_post_notification",
        lambda *_args, **_kwargs: {"delivery_status": "sent"},
    )
    monkeypatch.setattr(blogger_refactor_service, "_update_synced_fact", lambda *_args, **_kwargs: "2026-04")
    monkeypatch.setattr(blogger_refactor_service, "rebuild_blog_month_rollup", lambda *_args, **_kwargs: None)

    result = blogger_refactor_service.refactor_blogger_low_score_posts(
        db,
        blog_id=1,
        execute=True,
        threshold=80.0,
        month="2026-04",
        sync_before=True,
    )

    assert result["updated_count"] == 1
    assert updated_payload["post_id"] == "remote-101"
    assert "https://img.example.com/cover.jpg" in updated_payload["content"]
    assert "https://img.example.com/inline.jpg" in updated_payload["content"]
    assert result["items"][0]["predicted_seo_score"] == 88.0
    assert result["items"][0]["lighthouse_after"]["status"] == "ok"
