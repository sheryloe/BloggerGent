from __future__ import annotations

from app.services.content.related_posts import render_related_cards_html


def test_render_related_cards_html_omits_onerror_attribute() -> None:
    html = render_related_cards_html(
        [
            {
                "title": "Bell Island",
                "excerpt": "Mystery recap",
                "link": "https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
                "thumbnail": "https://api.dongriarchive.com/assets/media/google-blogger/the-midnight-archives/mystery/2026/03/bell-island/cover-aaaaaaaaaaaa.webp",
            }
        ]
    )

    assert "onerror=" not in html.lower()
    assert "cover-aaaaaaaaaaaa.webp" in html
