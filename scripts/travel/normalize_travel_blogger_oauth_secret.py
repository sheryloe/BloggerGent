from __future__ import annotations

import argparse
import json
import os
import sys
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal
from app.models.entities import PlatformCredential, Setting

ENCRYPTION_PREFIX = "enc:v1:"
TRAVEL_CREDENTIAL_KEYS = ("blogger:34", "blogger:36", "blogger:37")
DEFAULT_SETTING_KEYS = ("blogger_client_secret",)
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
DEFAULT_LEGACY_SECRET = "bloggent-dockerdesktop-2026-03-17"
DEFAULT_TARGET_SECRET = "cloudflare-bootstrap-20260418"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fernet(secret: str) -> Fernet:
    secret = str(secret or "").strip()
    if not secret:
        raise ValueError("encryption secret is required")
    return Fernet(urlsafe_b64encode(sha256(secret.encode("utf-8")).digest()))


def _is_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(ENCRYPTION_PREFIX))


def _decrypt_with_secret(value: str, secret: str) -> str | None:
    if not value:
        return ""
    if not _is_encrypted(value):
        return value
    token = value[len(ENCRYPTION_PREFIX) :]
    try:
        return _fernet(secret).decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def _encrypt_with_secret(value: str, secret: str) -> str:
    if not value:
        return ""
    token = _fernet(secret).encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTION_PREFIX}{token}"


def _token_shape(value: str | None) -> str:
    value = str(value or "")
    if not value:
        return "empty"
    if value.startswith(ENCRYPTION_PREFIX):
        return "still_encrypted"
    if value.startswith("ya29."):
        return "google_access_token"
    if value.startswith("1//") or value.startswith("1/"):
        return "google_refresh_token"
    if len(value) >= 40:
        return "opaque_token"
    return "unexpected_short_token"


def _resolve_token(raw: str, *, current_secret: str, legacy_secret: str) -> tuple[str | None, str, bool]:
    current_value = _decrypt_with_secret(raw, current_secret)
    if current_value is not None and not _is_encrypted(current_value):
        return current_value, "current", False

    legacy_value = _decrypt_with_secret(raw, legacy_secret)
    if legacy_value is not None and not _is_encrypted(legacy_value):
        return legacy_value, "legacy", True

    if raw and not _is_encrypted(raw):
        return raw, "plaintext", True

    return None, "unreadable", False


def _report_path(report_root: Path, prefix: str) -> Path:
    out_dir = report_root / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%d-%H%M%S")
    return out_dir / f"{prefix}-{stamp}.json"


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def normalize_credentials(
    *,
    execute: bool,
    current_secret: str,
    legacy_secret: str,
    credential_keys: tuple[str, ...],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": _utc_now().isoformat(),
        "execute": execute,
        "credential_keys": list(credential_keys),
        "items": [],
    }
    with SessionLocal() as db:
        for credential_key in credential_keys:
            item: dict[str, Any] = {
                "credential_key": credential_key,
                "found": False,
                "action": "none",
                "access_source": None,
                "refresh_source": None,
                "access_shape": None,
                "refresh_shape": None,
            }
            credential = (
                db.query(PlatformCredential)
                .filter(
                    PlatformCredential.provider == "blogger",
                    PlatformCredential.credential_key == credential_key,
                )
                .one_or_none()
            )
            if credential is None:
                item.update({"action": "missing"})
                report["items"].append(item)
                continue

            item["found"] = True
            access_token, access_source, access_needs_update = _resolve_token(
                credential.access_token_encrypted,
                current_secret=current_secret,
                legacy_secret=legacy_secret,
            )
            refresh_token, refresh_source, refresh_needs_update = _resolve_token(
                credential.refresh_token_encrypted,
                current_secret=current_secret,
                legacy_secret=legacy_secret,
            )
            item.update(
                {
                    "access_source": access_source,
                    "refresh_source": refresh_source,
                    "access_shape": _token_shape(access_token),
                    "refresh_shape": _token_shape(refresh_token),
                    "expires_at": credential.expires_at,
                    "is_valid_before": bool(credential.is_valid),
                    "last_error_before": credential.last_error,
                }
            )

            if access_token is None or refresh_token is None:
                item["action"] = "unreadable"
                report["items"].append(item)
                continue
            if _token_shape(access_token) == "still_encrypted" or _token_shape(refresh_token) == "still_encrypted":
                item["action"] = "unreadable"
                report["items"].append(item)
                continue

            needs_update = access_needs_update or refresh_needs_update
            if not needs_update:
                item["action"] = "already_current"
                report["items"].append(item)
                continue

            item["action"] = "reencrypt_to_current"
            if execute:
                credential.access_token_encrypted = _encrypt_with_secret(access_token, current_secret)
                credential.refresh_token_encrypted = _encrypt_with_secret(refresh_token, current_secret)
                credential.is_valid = True
                credential.last_error = None
                credential.refresh_metadata = {
                    **dict(credential.refresh_metadata or {}),
                    "normalized_for_travel_at": _utc_now().isoformat(),
                    "normalized_from": {
                        "access": access_source,
                        "refresh": refresh_source,
                    },
                }
                db.add(credential)
                item["updated"] = True
            else:
                item["updated"] = False
            report["items"].append(item)
        if execute:
            db.commit()

    counts: dict[str, int] = {}
    for item in report["items"]:
        action = str(item.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    report["counts"] = counts
    return report


def normalize_settings(
    *,
    execute: bool,
    current_secret: str,
    legacy_secret: str,
    setting_keys: tuple[str, ...],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": _utc_now().isoformat(),
        "execute": execute,
        "setting_keys": list(setting_keys),
        "items": [],
    }
    with SessionLocal() as db:
        for key in setting_keys:
            item: dict[str, Any] = {
                "key": key,
                "found": False,
                "action": "none",
                "current_shape": None,
                "legacy_shape": None,
            }
            row = db.query(Setting).filter(Setting.key == key).one_or_none()
            if row is None:
                item["action"] = "missing"
                report["items"].append(item)
                continue
            item["found"] = True
            if not row.is_secret:
                item["action"] = "not_secret"
                report["items"].append(item)
                continue

            current_value = _decrypt_with_secret(row.value, current_secret)
            legacy_value = _decrypt_with_secret(row.value, legacy_secret)
            item["current_shape"] = _token_shape(current_value)
            item["legacy_shape"] = _token_shape(legacy_value)

            if current_value is not None and not _is_encrypted(current_value):
                item["action"] = "already_current"
                report["items"].append(item)
                continue
            if legacy_value is None or _is_encrypted(legacy_value):
                item["action"] = "unreadable"
                report["items"].append(item)
                continue

            item["action"] = "reencrypt_to_current"
            if execute:
                row.value = _encrypt_with_secret(legacy_value, current_secret)
                db.add(row)
                item["updated"] = True
            else:
                item["updated"] = False
            report["items"].append(item)
        if execute:
            db.commit()

    counts: dict[str, int] = {}
    for item in report["items"]:
        action = str(item.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    report["counts"] = counts
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Travel Blogger OAuth credential encryption to the current secret.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-oauth-secret-normalize")
    parser.add_argument(
        "--current-secret",
        default=os.environ.get("SETTINGS_ENCRYPTION_SECRET") or DEFAULT_TARGET_SECRET,
        help="Target SETTINGS_ENCRYPTION_SECRET. Defaults to env SETTINGS_ENCRYPTION_SECRET.",
    )
    parser.add_argument(
        "--legacy-secret",
        default=os.environ.get("TRAVEL_LEGACY_SETTINGS_ENCRYPTION_SECRET") or DEFAULT_LEGACY_SECRET,
        help="Legacy SETTINGS_ENCRYPTION_SECRET used by old Blogger OAuth credential rows.",
    )
    parser.add_argument("--credential-keys", default=",".join(TRAVEL_CREDENTIAL_KEYS))
    parser.add_argument("--setting-keys", default=",".join(DEFAULT_SETTING_KEYS))
    args = parser.parse_args()

    credential_keys = tuple(
        dict.fromkeys(key.strip() for key in str(args.credential_keys or "").split(",") if key.strip()).keys()
    )
    if not credential_keys:
        raise SystemExit("No credential keys provided.")
    setting_keys = tuple(
        dict.fromkeys(key.strip() for key in str(args.setting_keys or "").split(",") if key.strip()).keys()
    )

    report = normalize_credentials(
        execute=bool(args.execute),
        current_secret=str(args.current_secret or ""),
        legacy_secret=str(args.legacy_secret or ""),
        credential_keys=credential_keys,
    )
    report["settings"] = normalize_settings(
        execute=bool(args.execute),
        current_secret=str(args.current_secret or ""),
        legacy_secret=str(args.legacy_secret or ""),
        setting_keys=setting_keys,
    )
    path = _report_path(Path(args.report_root), str(args.report_prefix))
    _write_report(path, report)
    print(json.dumps({"report_path": str(path), "counts": report["counts"], "items": report["items"]}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
