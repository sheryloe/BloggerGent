from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.services.content.blogger_live_publish_validation_service import validate_blogger_live_publish


class _FakeResponse:
    def __init__(self, *, status_code: int, text: str, url: str) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


def test_validate_blogger_live_publish_passes_when_title_hero_and_body_are_present(monkeypatch) -> None:
    body_text = (
        "Start at Seoul Forest Station and walk through the quieter edge first before the café stretch fills up. "
        "The route stays practical and scene-aware for real travelers. "
    ) * 8

    def _fake_get(url: str, timeout: float, follow_redirects: bool, headers=None):
        assert follow_redirects is True
        assert headers
        return _FakeResponse(
            status_code=200,
            url=url,
            text=(
                "<html><head><title>Practical Seoul Forest Spring Route</title></head>"
                "<body>"
                f"<article data-bloggent-article=\"canonical\"><h1>Practical Seoul Forest Spring Route</h1><figure><img src=\"https://api.dongriarchive.com/assets/travel-blogger/travel/seoul-forest.webp\" /></figure><p>{body_text}</p></article>"
                "</body></html>"
            ),
        )

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = validate_blogger_live_publish(
        published_url="https://example.com/post",
        expected_title="Practical Seoul Forest Spring Route",
        expected_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/seoul-forest.webp",
        assembled_html=f"<article data-bloggent-article=\"canonical\"><h1>Practical Seoul Forest Spring Route</h1><p>{body_text}</p></article>",
    )

    assert result["status"] == "ok"
    assert result["title_present"] is True
    assert result["hero_present"] is True
    assert result["live_content_present"] is True
    assert result["article_h1_count"] == 1


def test_validate_blogger_live_publish_fails_for_title_only_page(monkeypatch) -> None:
    def _fake_get(url: str, timeout: float, follow_redirects: bool, headers=None):
        return _FakeResponse(
            status_code=200,
            url=url,
            text="<html><head><title>Busan Night Route</title></head><body><h1>Busan Night Route</h1></body></html>",
        )

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = validate_blogger_live_publish(
        published_url="https://example.com/post",
        expected_title="Busan Night Route",
        expected_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night.webp",
        assembled_html="<article data-bloggent-article=\"canonical\"><h1>Busan Night Route</h1><p>This route should include enough real article text to be validated on the live page.</p></article>",
    )

    assert result["status"] == "failed"
    assert "missing_live_hero" in result["failure_reasons"]
    assert "missing_live_body" in result["failure_reasons"]
    assert "article_body_snippet_mismatch" in result["diagnostic_warnings"]


def test_validate_blogger_live_publish_fails_on_http_error(monkeypatch) -> None:
    def _fake_get(url: str, timeout: float, follow_redirects: bool, headers=None):
        return _FakeResponse(status_code=404, url=url, text="not found")

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = validate_blogger_live_publish(
        published_url="https://example.com/post",
        expected_title="Test title",
        expected_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/test.webp",
        assembled_html="<article><p>Test body content that should never be reached on a 404 response.</p></article>",
    )

    assert result["status"] == "failed"
    assert result["failure_reasons"][0].startswith("http_error:")


def test_validate_blogger_live_publish_uses_article_scoped_fragment_when_document_has_duplicates(monkeypatch) -> None:
    body_text = ("Bucheon azalea timing, route flow, and local stop planning for spring visitors. " * 20).strip()

    def _fake_get(url: str, timeout: float, follow_redirects: bool, headers=None):
        return _FakeResponse(
            status_code=200,
            url=url,
            text=(
                "<html><head><title>Ignore shell</title></head><body>"
                "<article><h1>Wrong copy</h1><img src=\"https://api.dongriarchive.com/assets/travel-blogger/travel/other.webp\" />"
                "<p>noise block</p></article>"
                "<article data-bloggent-article=\"canonical\"><h1>Bucheon Wonmisan Azalea Festival 2026</h1>"
                "<figure><img src=\"https://api.dongriarchive.com/assets/travel-blogger/travel/bucheon.webp\" /></figure>"
                f"<p>{body_text}</p></article>"
                "</body></html>"
            ),
        )

    monkeypatch.setattr(httpx, "get", _fake_get)

    result = validate_blogger_live_publish(
        published_url="https://example.com/post",
        expected_title="Bucheon Wonmisan Azalea Festival 2026",
        expected_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/bucheon.webp",
        assembled_html=f"<article data-bloggent-article=\"canonical\"><h1>Bucheon Wonmisan Azalea Festival 2026</h1><p>{body_text}</p></article>",
    )

    assert result["status"] == "ok"
    assert result["document_h1_count"] == 2
    assert result["article_h1_count"] == 1
    assert result["article_hero_occurrence_count"] == 1
