from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import quote

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SEARCH_CONSOLE_INSPECT_URL = "https://search.google.com/search-console/inspect?resource_id={resource_id}&id={url}"

REQUEST_INDEXING_TEXTS = (
    "Request indexing",
    "색인 생성 요청",
    "색인 요청",
    "Demander l'indexation",
    "Solicitar indexación",
    "Solicitar indexacao",
    "Richiedi indicizzazione",
    "インデックス登録をリクエスト",
)

SUCCESS_TEXTS = (
    "Indexing request submitted",
    "Indexing requested",
    "색인 생성 요청이 제출됨",
    "색인 요청이 제출됨",
    "Demande d'indexation envoyée",
    "Solicitud de indexación enviada",
    "Solicitud de indexación enviada correctamente",
    "インデックス登録をリクエストしました",
)

LOGIN_REQUIRED_TEXTS = (
    "Sign in",
    "로그인",
    "로그인이 필요합니다",
    "계정에 로그인",
    "Iniciar sesión",
)

PERMISSION_DENIED_TEXTS = (
    "you do not have access",
    "don't have access",
    "권한이 없습니다",
    "access denied",
    "no tienes acceso",
    "autorisation requise",
)

CAPTCHA_TEXTS = (
    "captcha",
    "unusual traffic",
    "verify you are human",
    "not a robot",
    "로봇이 아닙니다",
    "비정상 트래픽",
)


@dataclass(slots=True)
class SearchConsolePlaywrightResult:
    status: str
    code: str
    message: str
    cdp_url: str
    site_url: str
    url: str
    inspection_url: str
    matched_text: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SearchConsolePlaywrightError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def build_inspection_url(site_url: str, target_url: str) -> str:
    resource_id = quote(site_url, safe="")
    encoded_url = quote(target_url, safe="")
    return SEARCH_CONSOLE_INSPECT_URL.format(resource_id=resource_id, url=encoded_url)


def _safe_page_text(page: Page) -> str:
    try:
        return page.content().lower()
    except Exception:
        return ""


def _match_text(page: Page, texts: tuple[str, ...]) -> str | None:
    lowered_html = _safe_page_text(page)
    for text in texts:
        if text.lower() in lowered_html:
            return text
        try:
            locator = page.get_by_text(text, exact=False).first
            if locator.count() > 0 and locator.is_visible():
                return text
        except Exception:
            continue
    return None


def _is_login_redirect(url: str) -> bool:
    lowered = (url or "").lower()
    return "accounts.google.com" in lowered or "servicelogin" in lowered


def _is_captcha_redirect(url: str) -> bool:
    lowered = (url or "").lower()
    return "/sorry/" in lowered or "captcha" in lowered


def _click_request_button(page: Page) -> bool:
    pattern = re.compile("|".join(re.escape(text) for text in REQUEST_INDEXING_TEXTS), re.I)
    for role in ("button", "link", "menuitem"):
        try:
            locator = page.get_by_role(role, name=pattern).first
            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=5000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue

    for text in REQUEST_INDEXING_TEXTS:
        try:
            locator = page.get_by_text(text, exact=False).first
            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=5000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue

    return False


def request_indexing_via_search_console(
    *,
    cdp_url: str,
    site_url: str,
    target_url: str,
    timeout_ms: int = 90000,
) -> SearchConsolePlaywrightResult:
    inspection_url = build_inspection_url(site_url, target_url)
    normalized_cdp = str(cdp_url or "").strip()
    if not normalized_cdp:
        raise SearchConsolePlaywrightError(
            "Playwright CDP URL is empty.",
            code="cdp_url_missing",
            status_code=400,
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(normalized_cdp, timeout=min(timeout_ms, 45000))
            if not browser.contexts:
                raise SearchConsolePlaywrightError(
                    "No active browser context. Start the CDP browser and log in first.",
                    code="browser_context_missing",
                    status_code=409,
                )
            context = browser.contexts[0]
            page = context.new_page()
            try:
                page.goto(inspection_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)

                if _is_login_redirect(page.url) or _match_text(page, LOGIN_REQUIRED_TEXTS):
                    return SearchConsolePlaywrightResult(
                        status="failed",
                        code="login_required",
                        message="Google login is required for Search Console.",
                        cdp_url=normalized_cdp,
                        site_url=site_url,
                        url=target_url,
                        inspection_url=inspection_url,
                    )

                if _is_captcha_redirect(page.url) or _match_text(page, CAPTCHA_TEXTS):
                    return SearchConsolePlaywrightResult(
                        status="failed",
                        code="captcha_detected",
                        message="CAPTCHA or anti-bot challenge detected.",
                        cdp_url=normalized_cdp,
                        site_url=site_url,
                        url=target_url,
                        inspection_url=inspection_url,
                    )

                denied_text = _match_text(page, PERMISSION_DENIED_TEXTS)
                if denied_text:
                    return SearchConsolePlaywrightResult(
                        status="failed",
                        code="permission_denied",
                        message="The current account does not have Search Console property access.",
                        cdp_url=normalized_cdp,
                        site_url=site_url,
                        url=target_url,
                        inspection_url=inspection_url,
                        matched_text=denied_text,
                    )

                if not _click_request_button(page):
                    return SearchConsolePlaywrightResult(
                        status="failed",
                        code="button_not_found",
                        message="Request indexing button was not found.",
                        cdp_url=normalized_cdp,
                        site_url=site_url,
                        url=target_url,
                        inspection_url=inspection_url,
                    )

                for _ in range(20):
                    success_text = _match_text(page, SUCCESS_TEXTS)
                    if success_text:
                        return SearchConsolePlaywrightResult(
                            status="ok",
                            code="request_submitted",
                            message="Search Console accepted the indexing request.",
                            cdp_url=normalized_cdp,
                            site_url=site_url,
                            url=target_url,
                            inspection_url=inspection_url,
                            matched_text=success_text,
                        )

                    if _is_login_redirect(page.url) or _match_text(page, LOGIN_REQUIRED_TEXTS):
                        return SearchConsolePlaywrightResult(
                            status="failed",
                            code="login_required",
                            message="Google login session expired during request.",
                            cdp_url=normalized_cdp,
                            site_url=site_url,
                            url=target_url,
                            inspection_url=inspection_url,
                        )
                    if _is_captcha_redirect(page.url) or _match_text(page, CAPTCHA_TEXTS):
                        return SearchConsolePlaywrightResult(
                            status="failed",
                            code="captcha_detected",
                            message="CAPTCHA detected while requesting indexing.",
                            cdp_url=normalized_cdp,
                            site_url=site_url,
                            url=target_url,
                            inspection_url=inspection_url,
                        )
                    denied_text = _match_text(page, PERMISSION_DENIED_TEXTS)
                    if denied_text:
                        return SearchConsolePlaywrightResult(
                            status="failed",
                            code="permission_denied",
                            message="Search Console property permission denied.",
                            cdp_url=normalized_cdp,
                            site_url=site_url,
                            url=target_url,
                            inspection_url=inspection_url,
                            matched_text=denied_text,
                        )
                    page.wait_for_timeout(700)

                return SearchConsolePlaywrightResult(
                    status="failed",
                    code="result_not_detected",
                    message="No success/failure marker was detected after clicking request indexing.",
                    cdp_url=normalized_cdp,
                    site_url=site_url,
                    url=target_url,
                    inspection_url=inspection_url,
                )
            finally:
                page.close()
    except SearchConsolePlaywrightError:
        raise
    except PlaywrightTimeoutError as exc:
        raise SearchConsolePlaywrightError(
            "Timed out while trying to request indexing in Search Console.",
            code="timeout",
            status_code=504,
        ) from exc
    except Exception as exc:
        raise SearchConsolePlaywrightError(
            f"Playwright indexing request failed: {exc}",
            code="playwright_error",
            status_code=502,
        ) from exc
