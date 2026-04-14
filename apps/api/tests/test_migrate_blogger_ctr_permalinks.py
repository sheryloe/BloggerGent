from __future__ import annotations

from scripts.migrate_blogger_ctr_permalinks import is_generic_blogger_permalink


def test_is_generic_blogger_permalink_matches_blog_post_patterns() -> None:
    assert is_generic_blogger_permalink("http://donggri-kankoku.blogspot.com/2026/04/blog-post.html")
    assert is_generic_blogger_permalink("http://donggri-kankoku.blogspot.com/2026/04/blog-post_12.html")
    assert is_generic_blogger_permalink("https://donggri-kankoku.blogspot.com/2026/04/blog-post_abc.html")


def test_is_generic_blogger_permalink_rejects_non_generic_urls() -> None:
    assert not is_generic_blogger_permalink("http://donggri-kankoku.blogspot.com/2026/04/seoul-walk-guide.html")
    assert not is_generic_blogger_permalink("http://donggri-kankoku.blogspot.com/2026/04/2026_01826020817.html")
    assert not is_generic_blogger_permalink("http://donggri-kankoku.blogspot.com/")
