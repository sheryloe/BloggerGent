from app.services.html_assembler import _strip_mystery_inline_artifacts


def test_strip_mystery_inline_artifacts_removes_collage_markers_and_figures() -> None:
    source = """
<h2>Case</h2>
<p>4-panel investigation collage</p>
<figure><img src="https://example.com/a.png" /></figure>
<p>AI-generated editorial collage</p>
<p>Evidence timeline remains.</p>
""".strip()

    cleaned = _strip_mystery_inline_artifacts(source)

    assert "4-panel investigation collage" not in cleaned
    assert "AI-generated editorial collage" not in cleaned
    assert "<figure" not in cleaned.lower()
    assert "<img" not in cleaned.lower()
    assert "Evidence timeline remains." in cleaned
