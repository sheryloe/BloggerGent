from app.services.blogger.blogger_live_audit_service import (
    ISSUE_BROKEN_IMAGE,
    ISSUE_EMPTY_FIGURE,
    ISSUE_MISSING_COVER,
    ISSUE_MISSING_INLINE,
    ISSUE_MISSING_PUBLIC_URL,
    audit_blogger_article_fragment,
    audit_blogger_post_live_html,
    fetch_and_audit_blogger_post,
)


def test_audit_detects_empty_figure_and_missing_slots() -> None:
    fragment = """
    <article data-bloggent-meta-description="sample">
      <figure style="margin:0 0 32px;"></figure>
      <p>Bell Island mystery article body.</p>
    </article>
    """

    result = audit_blogger_article_fragment(fragment, page_url="https://example.com/post")

    assert result.live_image_count == 0
    assert result.live_unique_image_count == 0
    assert result.live_duplicate_image_count == 0
    assert result.live_cover_present is False
    assert result.live_inline_present is False
    assert result.raw_figure_count == 1
    assert result.empty_figure_count == 1
    assert result.live_image_issue is not None
    issue_codes = set(result.live_image_issue.split(","))
    assert {ISSUE_EMPTY_FIGURE, ISSUE_MISSING_COVER, ISSUE_MISSING_INLINE}.issubset(issue_codes)


def test_audit_detects_cover_and_inline_slots() -> None:
    fragment = """
    <article data-bloggent-meta-description="sample">
      <figure data-bloggent-normalize-slot="cover"><img src="/cover.webp" alt=""></figure>
      <p>Body</p>
      <figure data-bloggent-normalize-slot="inline"><img src="/inline.webp" alt=""></figure>
    </article>
    """

    result = audit_blogger_article_fragment(fragment, page_url="https://example.com/post")

    assert result.live_image_count == 1
    assert result.live_unique_image_count == 1
    assert result.live_duplicate_image_count == 0
    assert result.live_cover_present is True
    assert result.live_inline_present is True
    assert result.live_image_issue is None
    assert result.renderable_image_urls == (
        "https://example.com/cover.webp",
        "https://example.com/inline.webp",
    )


def test_audit_ignores_related_posts_images_when_cover_is_missing() -> None:
    fragment = """
    <article data-bloggent-meta-description="sample">
      <header><h1>Bell Island</h1></header>
      <div id="bloggent-seo-meta"></div>
      <figure></figure>
      <section><p>Body</p></section>
      <section class="related-posts">
        <img src="/related.webp" alt="">
      </section>
    </article>
    """

    result = audit_blogger_article_fragment(fragment, page_url="https://example.com/post")

    assert result.live_cover_present is False
    assert result.live_inline_present is False
    assert result.renderable_image_urls == ()
    assert result.live_image_issue is not None
    issue_codes = set(result.live_image_issue.split(","))
    assert ISSUE_EMPTY_FIGURE in issue_codes
    assert ISSUE_MISSING_COVER in issue_codes


def test_audit_uses_first_figure_near_title_as_cover() -> None:
    fragment = """
    <article data-bloggent-meta-description="sample">
      <header><h1>Wow Signal</h1></header>
      <div id="bloggent-seo-meta"></div>
      <figure><img src="/cover.webp" alt=""></figure>
      <section><p>Body</p></section>
      <section class="related-posts">
        <img src="/related.webp" alt="">
      </section>
    </article>
    """

    result = audit_blogger_article_fragment(fragment, page_url="https://example.com/post")

    assert result.live_cover_present is True
    assert result.live_inline_present is False
    assert result.live_image_count == 0
    assert result.renderable_image_urls == ("https://example.com/cover.webp",)


def test_audit_detects_duplicate_and_broken_images() -> None:
    fragment = """
    <article data-bloggent-meta-description="sample">
      <figure data-bloggent-normalize-slot="cover"><img src="/shared.webp" alt=""></figure>
      <figure data-bloggent-normalize-slot="inline"><img src="/shared.webp" alt=""></figure>
    </article>
    """

    result = audit_blogger_article_fragment(
        fragment,
        page_url="https://example.com/post",
        probe_images=True,
        image_probe=lambda _url: False,
    )

    assert result.live_image_count == 1
    assert result.live_unique_image_count == 1
    assert result.live_duplicate_image_count == 0
    assert result.live_image_issue is not None
    issue_codes = set(result.live_image_issue.split(","))
    assert ISSUE_BROKEN_IMAGE in issue_codes


def test_audit_prefers_nested_bloggent_article_fragment() -> None:
    page_html = """
    <html><body>
      <article class="outer-shell">
        <p>Theme shell</p>
        <article data-bloggent-meta-description="nested">
          <figure data-bloggent-normalize-slot="cover"><img src="/cover.webp" alt=""></figure>
          <figure data-bloggent-normalize-slot="inline"><img src="/inline.webp" alt=""></figure>
        </article>
      </article>
    </body></html>
    """

    result = audit_blogger_post_live_html(page_html, page_url="https://example.com/post")

    assert result.live_image_count == 1
    assert result.live_unique_image_count == 1
    assert result.live_cover_present is True
    assert result.live_inline_present is True


def test_audit_ignores_script_embedded_article_template_strings() -> None:
    page_html = """
    <html><body>
      <script>
        const card = '<article class="theme-card"><img src="/fake.webp" alt=""></article>';
      </script>
      <article data-bloggent-meta-description="real-content">
        <img src="/cover.webp" alt="">
        <img src="/inline.webp" alt="">
      </article>
    </body></html>
    """

    result = audit_blogger_post_live_html(page_html, page_url="https://example.com/post")

    assert result.live_cover_present is True
    assert result.live_inline_present is True
    assert result.renderable_image_urls == (
        "https://example.com/cover.webp",
        "https://example.com/inline.webp",
    )


def test_fetch_and_audit_missing_public_url_returns_explicit_issue() -> None:
    result = fetch_and_audit_blogger_post("")

    assert result.live_image_count is None
    assert result.live_unique_image_count is None
    assert result.live_duplicate_image_count is None
    assert result.live_image_issue == ISSUE_MISSING_PUBLIC_URL
