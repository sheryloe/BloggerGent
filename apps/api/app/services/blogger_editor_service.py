from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.models.entities import Article
from app.services.settings_service import get_settings_map

KOREAN_SEARCH_DESCRIPTION = "\uac80\uc0c9 \uc124\uba85"
KOREAN_POST_SETTINGS = "\uac8c\uc2dc\ubb3c \uc124\uc815"
KOREAN_SETTINGS = "\uc124\uc815"
KOREAN_UPDATE = "\uc5c5\ub370\uc774\ud2b8"
KOREAN_PUBLISH = "\uac8c\uc2dc"
KOREAN_SAVE = "\uc800\uc7a5"
KOREAN_DONE = "\uc644\ub8cc"


class BloggerEditorAutomationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class SearchDescriptionSyncResult:
    article_id: int
    blogger_post_id: str
    editor_url: str
    cdp_url: str
    description: str
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_editor_url(blogger_blog_id: str, blogger_post_id: str, account_index: int) -> str:
    return f"https://www.blogger.com/u/{account_index}/blog/post/edit/{blogger_blog_id}/{blogger_post_id}"


def is_blogger_playwright_enabled(db: Session) -> bool:
    values = get_settings_map(db)
    return _is_true(values.get("blogger_playwright_enabled"), default=False)


def is_blogger_playwright_auto_sync_enabled(db: Session) -> bool:
    values = get_settings_map(db)
    return _is_true(values.get("blogger_playwright_auto_sync"), default=True)


def _get_playwright_settings(db: Session) -> tuple[str, int]:
    values = get_settings_map(db)
    cdp_url = values.get("blogger_playwright_cdp_url", "").strip()
    if not cdp_url:
        raise BloggerEditorAutomationError(
            "Playwright CDP URL is empty. Set blogger_playwright_cdp_url first.",
            status_code=400,
        )

    account_index_raw = values.get("blogger_playwright_account_index", "0").strip() or "0"
    try:
        account_index = int(account_index_raw)
    except ValueError as exc:
        raise BloggerEditorAutomationError(
            "blogger_playwright_account_index must be a number.",
            status_code=400,
        ) from exc

    return cdp_url, account_index


def _click_first_text(page: Page, patterns: list[str]) -> bool:
    regex = re.compile("|".join(re.escape(pattern) for pattern in patterns), re.I)
    for role in ("button", "link", "menuitem", "tab"):
        try:
            locator = page.get_by_role(role, name=regex).first
            if locator.count() > 0:
                locator.click(timeout=2500)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue

    for pattern in patterns:
        try:
            locator = page.get_by_text(pattern, exact=False).first
            if locator.count() > 0:
                locator.click(timeout=2500)
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue

    return False


def _field_locator_candidates(page: Page):
    search_label_regex = re.compile(r"(search description|meta description)", re.I)
    korean_label_regex = re.compile(f"({re.escape(KOREAN_SEARCH_DESCRIPTION)})", re.I)

    return [
        page.get_by_label(search_label_regex).first,
        page.get_by_label(korean_label_regex).first,
        page.get_by_placeholder(search_label_regex).first,
        page.get_by_placeholder(korean_label_regex).first,
        page.locator("textarea[aria-label*='Search description']").first,
        page.locator("textarea[aria-label*='search description']").first,
        page.locator("textarea[aria-label*='meta description']").first,
        page.locator("textarea[aria-label*='검색 설명']").first,
        page.locator("input[aria-label*='Search description']").first,
        page.locator("input[aria-label*='meta description']").first,
        page.locator("input[aria-label*='검색 설명']").first,
        page.locator("textarea[name*='description' i]").first,
        page.locator("input[name*='description' i]").first,
        page.locator("textarea[id*='description' i]").first,
        page.locator("input[id*='description' i]").first,
    ]


def _find_description_field(page: Page):
    for locator in _field_locator_candidates(page):
        try:
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue

    return None


def _open_search_description(page: Page) -> None:
    if _find_description_field(page) is not None:
        return

    _click_first_text(page, ["Post settings", KOREAN_POST_SETTINGS, "Settings", KOREAN_SETTINGS])
    if _find_description_field(page) is not None:
        return

    _click_first_text(page, ["Search description", "Meta description", KOREAN_SEARCH_DESCRIPTION])
    if _find_description_field(page) is not None:
        return

    try:
        page.locator("button[aria-label*='settings' i], button[title*='settings' i]").first.click(timeout=2000)
        page.wait_for_timeout(500)
    except Exception:
        pass

    if _find_description_field(page) is not None:
        return

    raise BloggerEditorAutomationError(
        "Could not find the Blogger search description field in the editor.",
        status_code=502,
    )


def _fill_description(page: Page, description: str) -> None:
    field = _find_description_field(page)
    if field is None:
        raise BloggerEditorAutomationError(
            "Search description field is not available.",
            status_code=502,
        )

    field.scroll_into_view_if_needed(timeout=2000)
    field.click(timeout=3000)
    try:
        field.fill(description, timeout=3000)
    except Exception:
        page.keyboard.press("Control+A")
        page.keyboard.type(description)
    page.wait_for_timeout(300)


def _save_editor(page: Page) -> None:
    button_patterns = [
        "Update",
        "Publish",
        "Save",
        "Done",
        KOREAN_UPDATE,
        KOREAN_PUBLISH,
        KOREAN_SAVE,
        KOREAN_DONE,
    ]
    if _click_first_text(page, button_patterns):
        page.wait_for_timeout(2500)
        return

    raise BloggerEditorAutomationError(
        "Could not find a Blogger editor save or update button.",
        status_code=502,
    )


def sync_article_search_description(db: Session, article: Article) -> SearchDescriptionSyncResult:
    if not article.blog or not (article.blog.blogger_blog_id or "").strip():
        raise BloggerEditorAutomationError("This article is not connected to a Blogger blog.", status_code=400)
    if not article.blogger_post or not (article.blogger_post.blogger_post_id or "").strip():
        raise BloggerEditorAutomationError("Publish the article first so it gets a Blogger post ID.", status_code=400)
    if not (article.meta_description or "").strip():
        raise BloggerEditorAutomationError("This article does not have a meta description.", status_code=400)
    if not is_blogger_playwright_enabled(db):
        raise BloggerEditorAutomationError(
            "Playwright sync is disabled. Turn on blogger_playwright_enabled first.",
            status_code=409,
        )

    cdp_url, account_index = _get_playwright_settings(db)
    editor_url = _build_editor_url(article.blog.blogger_blog_id, article.blogger_post.blogger_post_id, account_index)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=45000)
            if not browser.contexts:
                raise BloggerEditorAutomationError(
                    "No browser context found. Start Chrome or Edge with remote debugging and sign into Blogger first.",
                    status_code=409,
                )

            context = browser.contexts[0]
            page = context.new_page()
            try:
                page.goto(editor_url, wait_until="domcontentloaded", timeout=60000)
                if "accounts.google.com" in page.url.lower() or "servicelogin" in page.url.lower():
                    raise BloggerEditorAutomationError(
                        "The remote browser is not signed into Google Blogger. Sign in once and try again.",
                        status_code=409,
                    )

                page.wait_for_timeout(2500)
                _open_search_description(page)
                _fill_description(page, article.meta_description)
                _save_editor(page)
            finally:
                page.close()
    except BloggerEditorAutomationError:
        raise
    except PlaywrightTimeoutError as exc:
        raise BloggerEditorAutomationError(
            "Timed out while trying to edit the Blogger post. Check the remote browser session and try again.",
            status_code=504,
        ) from exc
    except Exception as exc:
        raise BloggerEditorAutomationError(
            f"Playwright sync failed: {exc}",
            status_code=502,
        ) from exc

    return SearchDescriptionSyncResult(
        article_id=article.id,
        blogger_post_id=article.blogger_post.blogger_post_id,
        editor_url=editor_url,
        cdp_url=cdp_url,
        description=article.meta_description,
        status="ok",
        message="Blogger editor search description sync finished.",
    )
