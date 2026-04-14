from __future__ import annotations


def fetch_wikimedia_media(keyword: str, count: int = 3) -> list[dict]:
    # Keep mystery pipeline stable even when Wikimedia integration is unavailable.
    # Returning an empty list allows the job to continue without crashing.
    _ = keyword
    _ = count
    return []
