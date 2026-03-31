from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib import error, parse, request

from sqlalchemy.orm import Session

from app.services.settings_service import get_settings_map


TELEGRAM_API_BASE = "https://api.telegram.org"
logger = logging.getLogger(__name__)


def _post_telegram_message(*, bot_token: str, chat_id: str, text: str) -> dict:
    endpoint = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"}).encode("utf-8")
    req = request.Request(endpoint, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}
            result = body.get("result") if isinstance(body, dict) else {}
            if isinstance(body, dict) and body.get("ok"):
                return {
                    "delivery_status": "sent",
                    "chat_id": str(result.get("chat", {}).get("id", chat_id)),
                    "message_id": result.get("message_id"),
                    "response_text": raw,
                }
            return {
                "delivery_status": "failed",
                "chat_id": chat_id,
                "error_code": body.get("error_code") if isinstance(body, dict) else None,
                "error_message": body.get("description") if isinstance(body, dict) else "Unknown Telegram API error",
                "response_text": raw,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "delivery_status": "failed",
            "chat_id": chat_id,
            "error_code": exc.code,
            "error_message": str(exc),
            "response_text": body,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "delivery_status": "failed",
            "chat_id": chat_id,
            "error_message": str(exc),
        }


def _get_telegram_updates(*, bot_token: str, offset: int, timeout: int = 10) -> list[dict]:
    endpoint = f"{TELEGRAM_API_BASE}/bot{bot_token}/getUpdates"
    payload = parse.urlencode(
        {
            "offset": str(offset),
            "timeout": str(max(0, timeout)),
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
    ).encode("utf-8")
    req = request.Request(endpoint, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=max(15, timeout + 5)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}
            if isinstance(body, dict) and body.get("ok") and isinstance(body.get("result"), list):
                return list(body["result"])
    except Exception:  # noqa: BLE001
        return []
    return []


def _ops_help_text() -> str:
    return "\n".join(
        [
            "Bloggent ops commands",
            "/ops status",
            "/ops queue",
            "/ops review <id>",
            "/ops approve <id>",
            "/ops apply <id>",
            "/ops reject <id>",
            "/ops rerun <id>",
            "/ops sync-now",
            "/ops pause-learning",
            "/ops resume-learning",
        ]
    )


def send_telegram_post_notification(
    db: Session,
    *,
    blog_name: str,
    article_title: str,
    post_url: str,
    post_status: str,
    scheduled_for: datetime | None = None,
) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}

    lines = [
        f"[{blog_name}] {post_status.upper()}",
        article_title,
        post_url,
    ]
    if scheduled_for:
        lines.append(f"scheduled_for: {scheduled_for.isoformat()}")
    return _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text="\n".join(lines))


def send_telegram_error_notification(
    db: Session,
    *,
    title: str,
    detail: str,
    context: dict | None = None,
) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}

    context_text = ""
    if context:
        pairs = [f"{k}={v}" for k, v in sorted(context.items())]
        context_text = "\n" + "\n".join(pairs)
    message = f"[ERROR] {title}\n{detail}{context_text}"
    return _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text=message)


def send_telegram_ops_notification(db: Session, *, title: str, detail: str) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}
    return _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text=f"[OPS] {title}\n{detail}")


def send_telegram_test_message(db: Session, *, message: str | None = None) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}

    text = message or "Bloggent test notification"
    return _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text=text)


def poll_telegram_ops_commands(db: Session) -> dict:
    from app.services.content_ops_service import (
        ContentOpsError,
        apply_content_review,
        approve_content_review,
        get_content_ops_status,
        list_content_reviews,
        reject_content_review,
        rerun_content_review,
        serialize_review_item,
        sync_live_content_reviews,
    )
    from app.models.entities import ContentReviewItem
    from app.services.settings_service import upsert_settings

    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"status": "skipped", "reason": "telegram_not_configured"}

    try:
        offset = int((values.get("content_ops_telegram_update_offset") or "0").strip())
    except ValueError:
        offset = 0

    updates = _get_telegram_updates(bot_token=bot_token, offset=offset, timeout=10)
    if not updates:
        return {"status": "idle", "processed": 0, "ignored": 0}

    processed = 0
    ignored = 0
    max_update_id = offset

    for update in updates:
        update_id = int(update.get("update_id", 0) or 0)
        max_update_id = max(max_update_id, update_id)
        message = update.get("message") or update.get("edited_message") or {}
        if not isinstance(message, dict):
            ignored += 1
            continue
        text = str(message.get("text") or "").strip()
        if not text.startswith("/ops"):
            ignored += 1
            continue

        chat = message.get("chat") or {}
        incoming_chat_id = str(chat.get("id") or "").strip()
        if incoming_chat_id != chat_id:
            logger.warning("Ignoring unauthorized Telegram ops command from chat_id=%s", incoming_chat_id or "unknown")
            ignored += 1
            continue

        user = message.get("from") or {}
        actor = str(user.get("username") or user.get("first_name") or "telegram")
        reply_text = ""
        try:
            if text == "/ops" or text == "/ops help":
                reply_text = _ops_help_text()
            elif text == "/ops status":
                status = get_content_ops_status(db)
                reply_text = "\n".join(
                    [
                        "Content ops status",
                        f"queue={status['review_queue_count']}",
                        f"high_risk={status['high_risk_count']}",
                        f"auto_fix_today={status['auto_fix_applied_today']}",
                        f"learning_paused={status['learning_paused']}",
                        f"learning_snapshot_age={status['learning_snapshot_age']}",
                    ]
                )
            elif text == "/ops queue":
                rows = list_content_reviews(db, approval_status="pending", limit=10)
                if not rows:
                    reply_text = "Pending review queue is empty."
                else:
                    lines = ["Pending reviews"]
                    for item in rows:
                        lines.append(f"#{item.id} [{item.risk_level}] {item.review_kind} - {item.source_title}")
                    reply_text = "\n".join(lines)
            elif text.startswith("/ops review "):
                item_id = int(text.split(maxsplit=2)[2])
                item = db.get(ContentReviewItem, item_id)
                if not item:
                    raise ContentOpsError("Review item not found.", status_code=404)
                payload = serialize_review_item(item)
                lines = [
                    f"Review #{payload['id']}",
                    f"kind={payload['review_kind']}",
                    f"risk={payload['risk_level']}",
                    f"approval={payload['approval_status']}",
                    f"apply={payload['apply_status']}",
                    f"title={payload['source_title']}",
                ]
                for issue in payload["issues"][:5]:
                    lines.append(f"- {issue['code']}: {issue['message']}")
                reply_text = "\n".join(lines)
            elif text.startswith("/ops approve "):
                item_id = int(text.split(maxsplit=2)[2])
                item = approve_content_review(db, item_id, actor=actor, channel="telegram")
                reply_text = f"Approved review #{item.id}."
            elif text.startswith("/ops apply "):
                item_id = int(text.split(maxsplit=2)[2])
                item = apply_content_review(db, item_id, actor=actor, channel="telegram")
                reply_text = f"Applied review #{item.id}."
            elif text.startswith("/ops reject "):
                item_id = int(text.split(maxsplit=2)[2])
                item = reject_content_review(db, item_id, actor=actor, channel="telegram")
                reply_text = f"Rejected review #{item.id}."
            elif text.startswith("/ops rerun "):
                item_id = int(text.split(maxsplit=2)[2])
                item = rerun_content_review(db, item_id, actor=actor, channel="telegram")
                reply_text = f"Reran review #{item.id}."
            elif text == "/ops sync-now":
                result = sync_live_content_reviews(db)
                reply_text = f"sync status={result['status']} changed={result['changed_count']} failed={len(result['failed_blogs'])}"
            elif text == "/ops pause-learning":
                upsert_settings(db, {"content_ops_learning_paused": "true"})
                reply_text = "Scheduled learning paused."
            elif text == "/ops resume-learning":
                upsert_settings(db, {"content_ops_learning_paused": "false"})
                reply_text = "Scheduled learning resumed."
            else:
                reply_text = _ops_help_text()
        except ContentOpsError as exc:
            reply_text = f"Error: {exc.message}"
        except Exception as exc:  # noqa: BLE001
            reply_text = f"Error: {exc}"

        _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text=reply_text)
        processed += 1

    upsert_settings(db, {"content_ops_telegram_update_offset": str(max_update_id + 1)})
    return {"status": "ok", "processed": processed, "ignored": ignored}
