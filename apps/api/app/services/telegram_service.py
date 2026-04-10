from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib import error, parse, request

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.entities import (
    ContentReviewItem,
    TelegramChatBinding,
    TelegramCommandEvent,
    TelegramDeliveryEvent,
    TelegramSubscription,
)
from app.services.help_service import get_help_topic, list_help_topics, search_help_topics
from app.services.settings_service import get_settings_map, upsert_settings

TELEGRAM_API_BASE = "https://api.telegram.org"
logger = logging.getLogger(__name__)

DEFAULT_SUBSCRIPTIONS: dict[str, bool] = {
    "ops_status": True,
    "ops_queue": True,
    "content_review": True,
    "publish_alerts": True,
    "indexing_alerts": True,
}
MAX_MESSAGES_PER_MINUTE = 20
CONFIRM_TOKEN_TTL = timedelta(minutes=5)
_pending_confirmations: dict[str, dict] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_target_chat_id(values: dict[str, str], chat_id: str | None = None) -> str:
    target = str(chat_id or values.get("telegram_chat_id") or "").strip()
    if not target:
        raise ValueError("telegram_chat_not_configured")
    return target


def _ensure_chat_binding(
    db: Session,
    *,
    chat_id: str,
    username: str | None = None,
    chat_title: str | None = None,
) -> TelegramChatBinding:
    binding = db.query(TelegramChatBinding).filter(TelegramChatBinding.chat_id == chat_id).one_or_none()
    if binding is None:
        binding = TelegramChatBinding(
            chat_id=chat_id,
            username=(username or "").strip() or None,
            chat_title=(chat_title or "").strip() or None,
            is_admin=False,
            is_active=True,
            binding_metadata={},
        )
        db.add(binding)
        db.flush()
        return binding
    if username is not None:
        binding.username = (username or "").strip() or None
    if chat_title is not None:
        binding.chat_title = (chat_title or "").strip() or None
    db.flush()
    return binding


def _subscription_map(rows: list[TelegramSubscription]) -> dict[str, bool]:
    merged = dict(DEFAULT_SUBSCRIPTIONS)
    for row in rows:
        merged[str(row.event_key)] = bool(row.is_enabled)
    return merged


def list_telegram_subscriptions(db: Session, *, chat_id: str | None = None) -> dict:
    values = get_settings_map(db)
    resolved_chat_id = _resolve_target_chat_id(values, chat_id=chat_id)
    binding = db.query(TelegramChatBinding).filter(TelegramChatBinding.chat_id == resolved_chat_id).one_or_none()
    if binding is None:
        return {"chat_id": resolved_chat_id, "subscriptions": dict(DEFAULT_SUBSCRIPTIONS), "updated_at": None}
    rows = db.query(TelegramSubscription).filter(TelegramSubscription.chat_binding_id == binding.id).all()
    return {
        "chat_id": resolved_chat_id,
        "subscriptions": _subscription_map(rows),
        "updated_at": binding.updated_at.isoformat() if binding.updated_at else None,
    }


def update_telegram_subscriptions(db: Session, *, chat_id: str, subscriptions: dict[str, bool]) -> dict:
    values = get_settings_map(db)
    resolved_chat_id = _resolve_target_chat_id(values, chat_id=chat_id)
    binding = _ensure_chat_binding(db, chat_id=resolved_chat_id)
    rows = db.query(TelegramSubscription).filter(TelegramSubscription.chat_binding_id == binding.id).all()
    row_by_key = {row.event_key: row for row in rows}
    merged = dict(DEFAULT_SUBSCRIPTIONS)
    merged.update({str(key): bool(value) for key, value in subscriptions.items()})
    for event_key, enabled in merged.items():
        row = row_by_key.get(event_key)
        if row is None:
            db.add(
                TelegramSubscription(
                    chat_binding_id=binding.id,
                    event_key=event_key,
                    is_enabled=bool(enabled),
                    config_payload={},
                )
            )
        else:
            row.is_enabled = bool(enabled)
    db.commit()
    return list_telegram_subscriptions(db, chat_id=resolved_chat_id)


def _log_command_event(
    db: Session,
    *,
    chat_id: str,
    user_id: str | None,
    username: str | None,
    command: str,
    status: str,
    detail: str | None = None,
) -> None:
    db.add(
        TelegramCommandEvent(
            chat_id=chat_id,
            user_id=(user_id or "").strip() or None,
            username=(username or "").strip() or None,
            command=command,
            status=status,
            detail=detail,
            event_payload={},
        )
    )
    db.flush()


def _log_delivery_event(
    db: Session,
    *,
    chat_id: str,
    message_type: str,
    status: str,
    payload: dict,
    dedupe_key: str | None = None,
    error_code: int | None = None,
    error_message: str | None = None,
) -> None:
    db.add(
        TelegramDeliveryEvent(
            chat_id=chat_id,
            message_type=message_type,
            dedupe_key=dedupe_key,
            status=status,
            error_code=error_code,
            error_message=error_message,
            event_payload=payload,
            delivered_at=_now_utc() if status == "sent" else None,
        )
    )
    db.flush()


def _delivery_rate_limited(db: Session, *, chat_id: str) -> bool:
    since = _now_utc() - timedelta(minutes=1)
    count = (
        db.query(sa.func.count(TelegramDeliveryEvent.id))
        .filter(TelegramDeliveryEvent.chat_id == chat_id)
        .filter(TelegramDeliveryEvent.created_at >= since)
        .scalar()
        or 0
    )
    return int(count) >= MAX_MESSAGES_PER_MINUTE


def _post_telegram_message(*, bot_token: str, chat_id: str, text: str, reply_markup: dict | None = None) -> dict:
    endpoint = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"}
    if reply_markup:
        body["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    payload = parse.urlencode(body).encode("utf-8")
    req = request.Request(endpoint, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body_data = json.loads(raw) if raw else {}
            result = body_data.get("result") if isinstance(body_data, dict) else {}
            if isinstance(body_data, dict) and body_data.get("ok"):
                return {
                    "delivery_status": "sent",
                    "chat_id": str(result.get("chat", {}).get("id", chat_id)),
                    "message_id": result.get("message_id"),
                    "response_text": raw,
                }
            return {
                "delivery_status": "failed",
                "chat_id": chat_id,
                "error_code": body_data.get("error_code") if isinstance(body_data, dict) else None,
                "error_message": body_data.get("description") if isinstance(body_data, dict) else "Unknown Telegram API error",
                "response_text": raw,
            }
    except error.HTTPError as exc:
        body_data = exc.read().decode("utf-8", errors="replace")
        return {
            "delivery_status": "failed",
            "chat_id": chat_id,
            "error_code": exc.code,
            "error_message": str(exc),
            "response_text": body_data,
        }
    except Exception as exc:  # noqa: BLE001
        return {"delivery_status": "failed", "chat_id": chat_id, "error_message": str(exc)}


def _get_telegram_updates(*, bot_token: str, offset: int, timeout: int = 10) -> list[dict]:
    endpoint = f"{TELEGRAM_API_BASE}/bot{bot_token}/getUpdates"
    payload = parse.urlencode(
        {
            "offset": str(offset),
            "timeout": str(max(0, timeout)),
            "allowed_updates": json.dumps(["message", "edited_message", "callback_query"]),
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


def _send_telegram_message(
    db: Session,
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    message_type: str = "message",
    dedupe_key: str | None = None,
    reply_markup: dict | None = None,
) -> dict:
    if dedupe_key:
        if db.query(TelegramDeliveryEvent.id).filter(TelegramDeliveryEvent.dedupe_key == dedupe_key).first():
            return {"delivery_status": "skipped", "chat_id": chat_id, "skipped_reason": "duplicate"}
    if _delivery_rate_limited(db, chat_id=chat_id):
        return {"delivery_status": "skipped", "chat_id": chat_id, "skipped_reason": "rate_limited"}
    result = _post_telegram_message(bot_token=bot_token, chat_id=chat_id, text=text, reply_markup=reply_markup)
    _log_delivery_event(
        db,
        chat_id=chat_id,
        message_type=message_type,
        status=result.get("delivery_status") or "failed",
        dedupe_key=dedupe_key,
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
        payload={"text": text[:1000], "message_id": result.get("message_id"), "response_text": result.get("response_text")},
    )
    db.commit()
    return result


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
            "/ops menu",
            "",
            "Help commands",
            "/help",
            "/help ops",
            "/help settings",
            "/help runbook <id>",
            "/help search <keyword>",
        ]
    )


def _ops_menu_markup() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "상태", "callback_data": "ops:status"}, {"text": "큐", "callback_data": "ops:queue"}],
            [{"text": "동기화", "callback_data": "ops:sync"}, {"text": "도움말", "callback_data": "help:ops"}],
        ]
    }


def _execute_help_command(text: str) -> str:
    command = text.strip()
    if command in {"/help", "/help all"}:
        topics = list_help_topics()
        lines = ["Bloggent 도움말 토픽", ""]
        for row in topics[:10]:
            lines.append(f"- {row['topic_id']}: {row['title']}")
        return "\n".join(lines)
    if command.startswith("/help runbook "):
        topic_id = command[len("/help runbook ") :].strip()
        row = get_help_topic(topic_id)
        if row is None:
            return f"runbook '{topic_id}' 을(를) 찾을 수 없습니다."
        return f"[{row['topic_id']}] {row['title']}\n{row['summary']}"
    if command.startswith("/help search "):
        keyword = command[len("/help search ") :].strip()
        rows = search_help_topics(keyword, limit=5)
        if not rows:
            return f"'{keyword}' 검색 결과가 없습니다."
        return "\n".join([f"- {row['topic_id']}: {row['title']}" for row in rows])
    tag = command.replace("/help", "").strip()
    if tag:
        rows = list_help_topics(tag=tag)
        if rows:
            return "\n".join([f"- {row['topic_id']}: {row['title']}" for row in rows[:5]])
    return _ops_help_text()


def _confirmation_key(chat_id: str, action: str, item_id: int) -> str:
    return f"{chat_id}:{action}:{item_id}"


def _execute_ops_command(db: Session, *, text: str, actor: str, chat_id: str) -> str:
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

    try:
        if text in {"/ops", "/ops help"}:
            return _ops_help_text()
        if text == "/ops menu":
            return "운영 메뉴를 열었습니다."
        if text == "/ops status":
            status = get_content_ops_status(db)
            return "\n".join(
                [
                    "Content ops status",
                    f"queue={status['review_queue_count']}",
                    f"high_risk={status['high_risk_count']}",
                    f"auto_fix_today={status['auto_fix_applied_today']}",
                ]
            )
        if text == "/ops queue":
            rows = list_content_reviews(db, approval_status="pending", limit=10)
            if not rows:
                return "Pending review queue is empty."
            return "\n".join([f"#{row.id} [{row.risk_level}] {row.source_title}" for row in rows])
        if text.startswith("/ops review "):
            item_id = int(text.split()[2])
            item = db.get(ContentReviewItem, item_id)
            if not item:
                raise ContentOpsError("Review item not found.", status_code=404)
            payload = serialize_review_item(item)
            return f"Review #{payload['id']}\nkind={payload['review_kind']}\nrisk={payload['risk_level']}\ntitle={payload['source_title']}"
        if text.startswith("/ops approve "):
            parts = text.split()
            item_id = int(parts[2])
            item = db.get(ContentReviewItem, item_id)
            if item and str(item.risk_level or "").lower() in {"high", "critical"} and len(parts) < 5:
                token = secrets.token_hex(2).upper()
                _pending_confirmations[_confirmation_key(chat_id, "approve", item_id)] = {
                    "token": token,
                    "expires_at": _now_utc() + CONFIRM_TOKEN_TTL,
                }
                return f"고위험 승인입니다. 확인 명령: /ops confirm approve {item_id} {token}"
            row = approve_content_review(db, item_id, actor=actor, channel="telegram")
            return f"Approved review #{row.id}."
        if text.startswith("/ops apply "):
            parts = text.split()
            item_id = int(parts[2])
            item = db.get(ContentReviewItem, item_id)
            if item and str(item.risk_level or "").lower() in {"high", "critical"} and len(parts) < 5:
                token = secrets.token_hex(2).upper()
                _pending_confirmations[_confirmation_key(chat_id, "apply", item_id)] = {
                    "token": token,
                    "expires_at": _now_utc() + CONFIRM_TOKEN_TTL,
                }
                return f"고위험 적용입니다. 확인 명령: /ops confirm apply {item_id} {token}"
            row = apply_content_review(db, item_id, actor=actor, channel="telegram")
            return f"Applied review #{row.id}."
        if text.startswith("/ops confirm "):
            parts = text.split()
            if len(parts) < 5:
                return "형식: /ops confirm <approve|apply> <id> <token>"
            action = parts[2]
            item_id = int(parts[3])
            token = parts[4]
            key = _confirmation_key(chat_id, action, item_id)
            payload = _pending_confirmations.get(key)
            if payload is None or payload["expires_at"] < _now_utc() or str(payload["token"]).upper() != token.upper():
                return "확인 토큰이 유효하지 않습니다."
            _pending_confirmations.pop(key, None)
            return _execute_ops_command(db, text=f"/ops {action} {item_id} {token}", actor=actor, chat_id=chat_id)
        if text.startswith("/ops reject "):
            row = reject_content_review(db, int(text.split()[2]), actor=actor, channel="telegram")
            return f"Rejected review #{row.id}."
        if text.startswith("/ops rerun "):
            row = rerun_content_review(db, int(text.split()[2]), actor=actor, channel="telegram")
            return f"Reran review #{row.id}."
        if text == "/ops sync-now":
            result = sync_live_content_reviews(db)
            return f"sync status={result['status']} changed={result['changed_count']} failed={len(result['failed_blogs'])}"
        if text == "/ops pause-learning":
            upsert_settings(db, {"content_ops_learning_paused": "true"})
            return "Scheduled learning paused."
        if text == "/ops resume-learning":
            upsert_settings(db, {"content_ops_learning_paused": "false"})
            return "Scheduled learning resumed."
    except ContentOpsError as exc:
        return f"Error: {exc.message}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"
    return _ops_help_text()


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
    lines = [f"[{blog_name}] {post_status.upper()}", article_title, post_url]
    if scheduled_for:
        lines.append(f"scheduled_for: {scheduled_for.isoformat()}")
    return _send_telegram_message(db, bot_token=bot_token, chat_id=chat_id, text="\n".join(lines), message_type="publish_notification", dedupe_key=f"publish:{post_url}")


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
        context_text = "\n" + "\n".join([f"{k}={v}" for k, v in sorted(context.items())])
    return _send_telegram_message(db, bot_token=bot_token, chat_id=chat_id, text=f"[ERROR] {title}\n{detail}{context_text}", message_type="error_notification", dedupe_key=f"error:{title}:{detail[:60]}")


def send_telegram_ops_notification(db: Session, *, title: str, detail: str) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}
    return _send_telegram_message(db, bot_token=bot_token, chat_id=chat_id, text=f"[OPS] {title}\n{detail}", message_type="ops_notification", dedupe_key=f"ops:{title}:{detail[:60]}")


def send_telegram_test_message(db: Session, *, message: str | None = None) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"delivery_status": "skipped", "skipped_reason": "telegram_not_configured"}
    _ensure_chat_binding(db, chat_id=chat_id)
    return _send_telegram_message(db, bot_token=bot_token, chat_id=chat_id, text=message or "Bloggent test notification", message_type="test")


def poll_telegram_ops_commands(db: Session) -> dict:
    values = get_settings_map(db)
    bot_token = (values.get("telegram_bot_token") or "").strip()
    chat_id = (values.get("telegram_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return {"status": "skipped", "reason": "telegram_not_configured", "processed": 0, "ignored": 0}
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

        callback = update.get("callback_query") if isinstance(update, dict) else None
        message = (update.get("message") or update.get("edited_message")) if isinstance(update, dict) else None
        incoming_chat_id = ""
        user_id = ""
        actor = "telegram"
        text = ""
        show_menu = False

        if isinstance(callback, dict):
            callback_message = callback.get("message") or {}
            chat = callback_message.get("chat") or {}
            incoming_chat_id = str(chat.get("id") or "").strip()
            user = callback.get("from") or {}
            user_id = str(user.get("id") or "").strip()
            actor = str(user.get("username") or user.get("first_name") or "telegram")
            token = str(callback.get("data") or "").strip().lower()
            if token == "ops:status":
                text = "/ops status"
            elif token == "ops:queue":
                text = "/ops queue"
            elif token == "ops:sync":
                text = "/ops sync-now"
            elif token == "help:ops":
                text = "/help ops"
            else:
                ignored += 1
                continue
        elif isinstance(message, dict):
            text = str(message.get("text") or "").strip()
            chat = message.get("chat") or {}
            incoming_chat_id = str(chat.get("id") or "").strip()
            user = message.get("from") or {}
            user_id = str(user.get("id") or "").strip()
            actor = str(user.get("username") or user.get("first_name") or "telegram")
            _ensure_chat_binding(db, chat_id=incoming_chat_id, username=str(user.get("username") or ""), chat_title=str(chat.get("title") or ""))
        else:
            ignored += 1
            continue

        if not text.startswith("/ops") and not text.startswith("/help"):
            ignored += 1
            continue
        if incoming_chat_id != chat_id:
            logger.warning("Ignoring unauthorized Telegram ops command from chat_id=%s", incoming_chat_id or "unknown")
            _log_command_event(db, chat_id=incoming_chat_id or "unknown", user_id=user_id or None, username=actor, command=text, status="unauthorized", detail="chat_id_mismatch")
            db.commit()
            ignored += 1
            continue

        if text == "/ops menu":
            reply_text = "운영 메뉴"
            show_menu = True
            _log_command_event(db, chat_id=incoming_chat_id, user_id=user_id or None, username=actor, command=text, status="ok", detail="menu")
        elif text.startswith("/ops"):
            reply_text = _execute_ops_command(db, text=text, actor=actor, chat_id=incoming_chat_id)
            _log_command_event(db, chat_id=incoming_chat_id, user_id=user_id or None, username=actor, command=text, status="ok" if not reply_text.startswith("Error:") else "error", detail=reply_text[:400])
        else:
            reply_text = _execute_help_command(text)
            _log_command_event(db, chat_id=incoming_chat_id, user_id=user_id or None, username=actor, command=text, status="ok", detail=reply_text[:400])
        _send_telegram_message(db, bot_token=bot_token, chat_id=chat_id, text=reply_text, message_type="command_reply", reply_markup=_ops_menu_markup() if show_menu else None)
        processed += 1

    upsert_settings(db, {"content_ops_telegram_update_offset": str(max_update_id + 1)})
    return {"status": "ok", "processed": processed, "ignored": ignored}


def get_telegram_telemetry(db: Session, *, days: int = 7) -> dict:
    normalized_days = max(1, min(int(days), 30))
    since = _now_utc() - timedelta(days=normalized_days)
    command_events = db.query(sa.func.count(TelegramCommandEvent.id)).filter(TelegramCommandEvent.created_at >= since).scalar() or 0
    command_success = db.query(sa.func.count(TelegramCommandEvent.id)).filter(TelegramCommandEvent.created_at >= since).filter(TelegramCommandEvent.status == "ok").scalar() or 0
    command_failed = db.query(sa.func.count(TelegramCommandEvent.id)).filter(TelegramCommandEvent.created_at >= since).filter(TelegramCommandEvent.status != "ok").scalar() or 0
    deliveries_sent = db.query(sa.func.count(TelegramDeliveryEvent.id)).filter(TelegramDeliveryEvent.created_at >= since).filter(TelegramDeliveryEvent.status == "sent").scalar() or 0
    deliveries_failed = db.query(sa.func.count(TelegramDeliveryEvent.id)).filter(TelegramDeliveryEvent.created_at >= since).filter(TelegramDeliveryEvent.status != "sent").scalar() or 0
    top_rows = (
        db.query(TelegramCommandEvent.command.label("command"), sa.func.count(TelegramCommandEvent.id).label("count"))
        .filter(TelegramCommandEvent.created_at >= since)
        .group_by(TelegramCommandEvent.command)
        .order_by(sa.desc("count"), sa.asc("command"))
        .limit(10)
        .all()
    )
    return {
        "days": normalized_days,
        "command_events": int(command_events),
        "command_success": int(command_success),
        "command_failed": int(command_failed),
        "deliveries_sent": int(deliveries_sent),
        "deliveries_failed": int(deliveries_failed),
        "top_commands": [{"command": str(row.command), "count": int(row.count)} for row in top_rows],
    }
