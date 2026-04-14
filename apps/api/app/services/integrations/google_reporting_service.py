from __future__ import annotations

from datetime import date, timedelta
from html import unescape
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.models.entities import Blog
from app.services.blogger.blogger_oauth_service import BloggerOAuthError, authorized_google_request

BLOGGER_BLOG_URL = "https://www.googleapis.com/blogger/v3/blogs/{blog_id}"
BLOGGER_POSTS_URL = "https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
BLOGGER_PAGEVIEWS_URL = "https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pageviews/{range_name}"
SEARCH_CONSOLE_SITES_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites"
SEARCH_CONSOLE_QUERY_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"
ANALYTICS_ACCOUNT_SUMMARIES_URL = "https://analyticsadmin.googleapis.com/v1alpha/accountSummaries"
ANALYTICS_RUN_REPORT_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"


def _error_detail(response: httpx.Response) -> str:
    detail = response.text
    try:
        payload = response.json()
    except ValueError:
        return detail

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message", detail)
        if isinstance(error, str):
            return error
    return detail


def _raise_google_error(response: httpx.Response, message: str) -> None:
    raise BloggerOAuthError(message, detail=_error_detail(response), status_code=response.status_code)


def get_blogger_blog_detail(db: Session, remote_blog_id: str) -> dict:
    response = authorized_google_request(
        db,
        "GET",
        BLOGGER_BLOG_URL.format(blog_id=remote_blog_id),
        params={"view": "ADMIN"},
    )
    if not response.is_success:
        _raise_google_error(response, "Blogger 블로그 상세 조회에 실패했습니다.")

    item = response.json()
    posts = item.get("posts", {}) if isinstance(item.get("posts"), dict) else {}
    pages = item.get("pages", {}) if isinstance(item.get("pages"), dict) else {}
    return {
        "id": item.get("id", ""),
        "name": unescape(item.get("name", "")),
        "description": unescape(item.get("description", "")),
        "url": unescape(item.get("url", "")),
        "published": item.get("published", ""),
        "updated": item.get("updated", ""),
        "locale": item.get("locale", {}),
        "posts_total_items": int(posts.get("totalItems", 0) or 0) if posts else None,
        "pages_total_items": int(pages.get("totalItems", 0) or 0) if pages else None,
    }


def list_blogger_posts(db: Session, remote_blog_id: str, *, max_results: int = 10) -> list[dict]:
    params: list[tuple[str, str]] = [
        ("fetchBodies", "false"),
        ("view", "ADMIN"),
        ("sortBy", "UPDATED"),
        ("maxResults", str(max(1, min(max_results, 50)))),
        ("status", "live"),
        ("status", "draft"),
    ]
    response = authorized_google_request(
        db,
        "GET",
        BLOGGER_POSTS_URL.format(blog_id=remote_blog_id),
        params=params,
    )
    if not response.is_success:
        _raise_google_error(response, "Blogger 게시글 목록 조회에 실패했습니다.")

    items = response.json().get("items", []) or []
    posts: list[dict] = []
    for item in items:
        replies = item.get("replies", {}) if isinstance(item.get("replies"), dict) else {}
        author = item.get("author", {}) if isinstance(item.get("author"), dict) else {}
        posts.append(
            {
                "id": item.get("id", ""),
                "title": unescape(item.get("title", "(제목 없음)")),
                "url": unescape(item.get("url", "")),
                "published": item.get("published", ""),
                "updated": item.get("updated", ""),
                "labels": [unescape(label) for label in (item.get("labels", []) or [])],
                "status": item.get("status", ""),
                "author_display_name": unescape(author.get("displayName", "")),
                "replies_total_items": int(replies.get("totalItems", 0) or 0) if replies else 0,
            }
        )
    return posts


def get_blogger_pageviews(db: Session, remote_blog_id: str) -> list[dict]:
    results: list[dict] = []
    for range_name in ("7D", "30D", "all"):
        response = authorized_google_request(
            db,
            "GET",
            BLOGGER_PAGEVIEWS_URL.format(blog_id=remote_blog_id, range_name=range_name),
        )
        if not response.is_success:
            _raise_google_error(response, "Blogger 조회수 통계 조회에 실패했습니다.")
        results.append({"range": range_name, "count": int(response.json().get("count", 0) or 0)})
    return results


def list_search_console_sites(db: Session) -> list[dict]:
    response = authorized_google_request(db, "GET", SEARCH_CONSOLE_SITES_URL)
    if not response.is_success:
        _raise_google_error(response, "Search Console 사이트 목록 조회에 실패했습니다.")

    return [
        {
            "site_url": item.get("siteUrl", ""),
            "permission_level": item.get("permissionLevel", ""),
        }
        for item in response.json().get("siteEntry", []) or []
    ]


def query_search_console_performance(
    db: Session,
    site_url: str,
    *,
    days: int = 28,
    row_limit: int = 10,
) -> dict:
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(days - 1, 0))
    encoded_site = quote(site_url, safe="")

    totals_response = authorized_google_request(
        db,
        "POST",
        SEARCH_CONSOLE_QUERY_URL.format(site_url=encoded_site),
        json={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "type": "web",
            "rowLimit": 1,
        },
    )
    if not totals_response.is_success:
        _raise_google_error(totals_response, "Search Console 성과 요약 조회에 실패했습니다.")

    query_response = authorized_google_request(
        db,
        "POST",
        SEARCH_CONSOLE_QUERY_URL.format(site_url=encoded_site),
        json={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "type": "web",
            "dimensions": ["query"],
            "rowLimit": max(1, min(row_limit, 25)),
        },
    )
    if not query_response.is_success:
        _raise_google_error(query_response, "Search Console 상위 검색어 조회에 실패했습니다.")

    page_response = authorized_google_request(
        db,
        "POST",
        SEARCH_CONSOLE_QUERY_URL.format(site_url=encoded_site),
        json={
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "type": "web",
            "dimensions": ["page"],
            "rowLimit": max(1, min(row_limit, 25)),
        },
    )
    if not page_response.is_success:
        _raise_google_error(page_response, "Search Console 상위 페이지 조회에 실패했습니다.")

    totals_rows = totals_response.json().get("rows", []) or []
    totals_source = totals_rows[0] if totals_rows else {}

    def _serialize_rows(rows: list[dict]) -> list[dict]:
        return [
            {
                "keys": row.get("keys", []) or [],
                "clicks": float(row.get("clicks", 0) or 0),
                "impressions": float(row.get("impressions", 0) or 0),
                "ctr": float(row.get("ctr", 0) or 0),
                "position": float(row.get("position", 0) or 0),
            }
            for row in rows
        ]

    return {
        "site_url": site_url,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "totals": {
            "clicks": float(totals_source.get("clicks", 0) or 0),
            "impressions": float(totals_source.get("impressions", 0) or 0),
            "ctr": float(totals_source.get("ctr", 0) or 0),
            "position": float(totals_source.get("position", 0) or 0),
        },
        "top_queries": _serialize_rows(query_response.json().get("rows", []) or []),
        "top_pages": _serialize_rows(page_response.json().get("rows", []) or []),
    }


def list_analytics_properties(db: Session) -> list[dict]:
    response = authorized_google_request(
        db,
        "GET",
        ANALYTICS_ACCOUNT_SUMMARIES_URL,
        params={"pageSize": 200},
    )
    if not response.is_success:
        _raise_google_error(response, "Google Analytics 속성 목록 조회에 실패했습니다.")

    items: list[dict] = []
    for account in response.json().get("accountSummaries", []) or []:
        account_name = account.get("displayName", "")
        for prop in account.get("propertySummaries", []) or []:
            property_name = prop.get("property", "")
            property_id = property_name.split("/")[-1] if property_name else ""
            items.append(
                {
                    "property_id": property_id,
                    "display_name": prop.get("displayName", ""),
                    "property_type": prop.get("propertyType", ""),
                    "parent_display_name": account_name,
                }
            )
    return items


def query_analytics_overview(db: Session, property_id: str, *, days: int = 28, row_limit: int = 10) -> dict:
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(days - 1, 0))
    body_base = {"dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}]}

    totals_response = authorized_google_request(
        db,
        "POST",
        ANALYTICS_RUN_REPORT_URL.format(property_id=property_id),
        json={
            **body_base,
            "metrics": [{"name": "screenPageViews"}, {"name": "sessions"}, {"name": "activeUsers"}],
        },
    )
    if not totals_response.is_success:
        _raise_google_error(totals_response, "Google Analytics 요약 조회에 실패했습니다.")

    top_pages_response = authorized_google_request(
        db,
        "POST",
        ANALYTICS_RUN_REPORT_URL.format(property_id=property_id),
        json={
            **body_base,
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "sessions"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": str(max(1, min(row_limit, 25))),
        },
    )
    if not top_pages_response.is_success:
        _raise_google_error(top_pages_response, "Google Analytics 상위 페이지 조회에 실패했습니다.")

    totals_rows = totals_response.json().get("rows", []) or []
    total_metrics = totals_rows[0].get("metricValues", []) if totals_rows else []
    totals = {
        "screenPageViews": float(total_metrics[0].get("value", 0) or 0) if len(total_metrics) > 0 else 0.0,
        "sessions": float(total_metrics[1].get("value", 0) or 0) if len(total_metrics) > 1 else 0.0,
        "activeUsers": float(total_metrics[2].get("value", 0) or 0) if len(total_metrics) > 2 else 0.0,
    }

    top_pages: list[dict] = []
    for row in top_pages_response.json().get("rows", []) or []:
        dimension_values = row.get("dimensionValues", []) or []
        metric_values = row.get("metricValues", []) or []
        top_pages.append(
            {
                "page_path": dimension_values[0].get("value", "") if dimension_values else "",
                "screenPageViews": float(metric_values[0].get("value", 0) or 0) if len(metric_values) > 0 else 0.0,
                "sessions": float(metric_values[1].get("value", 0) or 0) if len(metric_values) > 1 else 0.0,
            }
        )

    return {
        "property_id": property_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "totals": totals,
        "top_pages": top_pages,
    }


def build_google_blog_overview(db: Session, blog: Blog, *, days: int = 28, posts_limit: int = 10) -> dict:
    warnings: list[str] = []
    remote_blog = None
    pageviews: list[dict] = []
    recent_posts: list[dict] = []
    search_console = None
    analytics = None

    if blog.blogger_blog_id:
        try:
            remote_blog = get_blogger_blog_detail(db, blog.blogger_blog_id)
        except BloggerOAuthError as exc:
            warnings.append(f"Blogger 블로그 상세 조회 실패: {exc.detail}")
        try:
            pageviews = get_blogger_pageviews(db, blog.blogger_blog_id)
        except BloggerOAuthError as exc:
            warnings.append(f"Blogger 조회수 통계 조회 실패: {exc.detail}")
        try:
            recent_posts = list_blogger_posts(db, blog.blogger_blog_id, max_results=posts_limit)
        except BloggerOAuthError as exc:
            warnings.append(f"Blogger 게시글 목록 조회 실패: {exc.detail}")
    else:
        warnings.append("이 블로그에 Blogger 블로그 ID가 아직 연결되지 않았습니다.")

    if blog.search_console_site_url:
        try:
            search_console = query_search_console_performance(db, blog.search_console_site_url, days=days)
        except BloggerOAuthError as exc:
            warnings.append(f"Search Console 조회 실패: {exc.detail}")
    else:
        warnings.append("Search Console 속성 URL이 아직 설정되지 않았습니다.")

    if blog.ga4_property_id:
        try:
            analytics = query_analytics_overview(db, blog.ga4_property_id, days=days)
        except BloggerOAuthError as exc:
            warnings.append(f"Google Analytics 조회 실패: {exc.detail}")
    else:
        warnings.append("GA4 속성 ID가 아직 설정되지 않았습니다.")

    return {
        "blog_id": blog.id,
        "blog_name": blog.name,
        "blogger_blog_id": blog.blogger_blog_id,
        "remote_blog": remote_blog,
        "pageviews": pageviews,
        "recent_posts": recent_posts,
        "search_console": search_console,
        "analytics": analytics,
        "warnings": warnings,
    }
