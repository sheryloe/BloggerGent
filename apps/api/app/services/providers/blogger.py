from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.models.entities import PostStatus, PublishMode


class BloggerPublishingProvider:
    def __init__(self, *, access_token: str, blog_id: str) -> None:
        self.access_token = access_token
        self.blog_id = blog_id

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def publish(
        self,
        *,
        title: str,
        content: str,
        labels: list[str],
        meta_description: str,
        slug: str,
        publish_mode: PublishMode,
    ) -> tuple[dict, dict]:
        params = {"isDraft": str(publish_mode == PublishMode.DRAFT).lower()}
        url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/?{urlencode(params)}"
        payload = {
            "kind": "blogger#post",
            "title": title,
            "content": content,
            "labels": labels,
        }
        response = httpx.post(
            url,
            headers=self._auth_headers(),
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "id": data.get("id", slug),
            "url": data.get("url", ""),
            "published": data.get("published"),
            "isDraft": bool(data.get("status") == "DRAFT" or params["isDraft"] == "true"),
            "postStatus": PostStatus.DRAFT.value if params["isDraft"] == "true" else PostStatus.PUBLISHED.value,
            "scheduledFor": None,
        }, data

    def update_post(
        self,
        *,
        post_id: str,
        title: str,
        content: str,
        labels: list[str],
        meta_description: str,
    ) -> tuple[dict, dict]:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}"
        payload = {
            "kind": "blogger#post",
            "id": post_id,
            "title": title,
            "content": content,
            "labels": labels,
        }
        response = httpx.put(
            url,
            headers=self._auth_headers(),
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        raw_status = str(data.get("status", "")).upper()
        if raw_status == "DRAFT":
            post_status = PostStatus.DRAFT.value
        elif raw_status == "SCHEDULED":
            post_status = PostStatus.SCHEDULED.value
        else:
            post_status = PostStatus.PUBLISHED.value
        return {
            "id": data.get("id", post_id),
            "url": data.get("url", ""),
            "published": data.get("published"),
            "isDraft": raw_status == "DRAFT",
            "postStatus": post_status,
            "scheduledFor": data.get("published") if raw_status == "SCHEDULED" else None,
        }, data

    def publish_draft(self, post_id: str, publish_date: str | None = None) -> tuple[dict, dict]:
        params = {"publishDate": publish_date} if publish_date else None
        query = f"?{urlencode(params)}" if params else ""
        url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}/publish{query}"
        response = httpx.post(
            url,
            headers=self._auth_headers(),
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        raw_status = str(data.get("status", "")).upper()
        post_status = PostStatus.SCHEDULED.value if publish_date or raw_status == "SCHEDULED" else PostStatus.PUBLISHED.value
        return {
            "id": data.get("id", post_id),
            "url": data.get("url", ""),
            "published": data.get("published"),
            "isDraft": False,
            "postStatus": post_status,
            "scheduledFor": data.get("published") if post_status == PostStatus.SCHEDULED.value else None,
        }, data

    def delete_post(self, post_id: str) -> None:
        url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}?useTrash=true"
        response = httpx.delete(
            url,
            headers=self._auth_headers(),
            timeout=30.0,
        )
        if response.status_code in {200, 204, 404}:
            return
        response.raise_for_status()
