from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.providers.base import ProviderRuntimeError, RuntimeProviderConfig


POLL_INTERVAL_SECONDS = 1.0


def _codex_command_path() -> str | None:
    return shutil.which("codex.cmd") or shutil.which("codex")


def _queue_root(runtime: RuntimeProviderConfig | None = None) -> Path:
    root = Path(settings.storage_root).resolve() / "codex-queue"
    if runtime and str(runtime.provider_mode or "").strip().lower() == "mock":
        root = Path(settings.storage_root).resolve() / "codex-queue"
    return root


def _requests_dir(runtime: RuntimeProviderConfig | None = None) -> Path:
    path = _queue_root(runtime) / "requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _responses_dir(runtime: RuntimeProviderConfig | None = None) -> Path:
    path = _queue_root(runtime) / "responses"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _processing_dir(runtime: RuntimeProviderConfig | None = None) -> Path:
    path = _queue_root(runtime) / "processing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _failed_dir(runtime: RuntimeProviderConfig | None = None) -> Path:
    path = _queue_root(runtime) / "failed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request_payload(
    *,
    request_id: str,
    stage_name: str,
    model: str,
    prompt: str,
    response_kind: str,
    response_schema: dict[str, Any] | None,
    workspace_dir: str,
    codex_config_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "stage_name": stage_name,
        "model": model,
        "prompt": prompt,
        "response_kind": response_kind,
        "response_schema": response_schema,
        "workspace_dir": workspace_dir,
        "codex_config_overrides": codex_config_overrides or {},
    }


def _normalize_codex_response_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_codex_response_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _normalize_codex_response_schema(item) for key, item in value.items()}
    if normalized.get("type") == "object" or "properties" in normalized:
        normalized["additionalProperties"] = False
        properties = normalized.get("properties")
        if isinstance(properties, dict) and properties:
            normalized["required"] = list(properties.keys())
    return normalized


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _to_toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _run_codex_text_job_inline(
    *,
    request_id: str,
    stage_name: str,
    model: str,
    prompt: str,
    response_kind: str,
    response_schema: dict[str, Any] | None = None,
    workspace_dir: str,
    codex_config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    temp_root = Path(tempfile.gettempdir()) / "bloggent-codex-inline"
    temp_root.mkdir(parents=True, exist_ok=True)

    output_path = temp_root / f"{request_id}.output.txt"
    log_path = temp_root / f"{request_id}.log.txt"
    schema_path = temp_root / f"{request_id}.schema.json"

    codex_command = _codex_command_path()
    if not codex_command:
        raise ProviderRuntimeError(
            provider="codex_cli",
            status_code=503,
            message="codex executable was not found in PATH.",
            detail="codex.cmd/codex unavailable",
        )

    args = [
        "exec",
        "-m",
        model,
        "-C",
        workspace_dir,
        "-s",
        "read-only",
        "--disable",
        "plugins",
        "--skip-git-repo-check",
        "--ephemeral",
        "-o",
        str(output_path),
    ]
    for key, value in sorted((codex_config_overrides or {}).items()):
        key_text = str(key or "").strip()
        if not key_text:
            continue
        args.extend(["-c", f"{key_text}={_to_toml_literal(value)}"])
    if response_kind == "json_schema" and response_schema is not None:
        schema_path.write_text(json.dumps(response_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        args.extend(["--output-schema", str(schema_path)])
    args.append("-")

    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", codex_command, *args],
            input=prompt,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace_dir,
        )
        log_text = "\n".join(part.strip() for part in (proc.stderr, proc.stdout) if part and part.strip())
        log_path.write_text(log_text, encoding="utf-8")

        if proc.returncode != 0:
            raise ProviderRuntimeError(
                provider="codex_cli",
                status_code=502,
                message="Codex CLI job failed.",
                detail=log_text[-4000:] or f"codex exited with code {proc.returncode}",
            )

        content = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        return {
            "status": "completed",
            "request_id": request_id,
            "stage_name": stage_name,
            "provider_name": "codex-cli",
            "provider_model": model,
            "runtime_kind": "codex_cli",
            "content": content,
            "log_path": str(log_path),
        }
    finally:
        output_path.unlink(missing_ok=True)
        schema_path.unlink(missing_ok=True)


def submit_codex_text_job(
    *,
    runtime: RuntimeProviderConfig,
    stage_name: str,
    model: str,
    prompt: str,
    response_kind: str,
    response_schema: dict[str, Any] | None = None,
    timeout_seconds: int | None = None,
    inline: bool = False,
    codex_config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    normalized_schema = _normalize_codex_response_schema(response_schema)
    workspace_dir = str(Path.cwd().resolve())

    if inline and not _codex_command_path():
        inline = False

    if inline:
        return _run_codex_text_job_inline(
            request_id=request_id,
            stage_name=stage_name,
            model=model,
            prompt=prompt,
            response_kind=response_kind,
            response_schema=normalized_schema,
            workspace_dir=workspace_dir,
            codex_config_overrides=codex_config_overrides,
        )

    request_path = _requests_dir(runtime) / f"{request_id}.json"
    processing_path = _processing_dir(runtime) / f"{request_id}.json"
    response_path = _responses_dir(runtime) / f"{request_id}.json"
    failed_path = _failed_dir(runtime) / f"{request_id}.json"
    payload = _request_payload(
        request_id=request_id,
        stage_name=stage_name,
        model=model,
        prompt=prompt,
        response_kind=response_kind,
        response_schema=normalized_schema,
        workspace_dir=workspace_dir,
        codex_config_overrides=codex_config_overrides or {},
    )
    _write_json(request_path, payload)

    deadline = time.monotonic() + max(int(timeout_seconds or runtime.codex_job_timeout_seconds or 900), 30)
    while time.monotonic() < deadline:
        if response_path.exists():
            data = _read_json(response_path)
            response_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
            processing_path.unlink(missing_ok=True)
            if str(data.get("status") or "").strip().lower() != "completed":
                raise ProviderRuntimeError(
                    provider="codex_cli",
                    status_code=502,
                    message="Codex CLI job returned a non-completed response.",
                    detail=str(data.get("error") or data),
                )
            return data
        if failed_path.exists():
            data = _read_json(failed_path)
            failed_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
            processing_path.unlink(missing_ok=True)
            raise ProviderRuntimeError(
                provider="codex_cli",
                status_code=502,
                message="Codex CLI job failed.",
                detail=str(data.get("error") or data),
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    if processing_path.exists() and not request_path.exists():
        processing_path.replace(request_path)

    raise ProviderRuntimeError(
        provider="codex_cli",
        status_code=504,
        message="Timed out waiting for Codex CLI response.",
        detail=f"request_id={request_id}, stage_name={stage_name}, timeout_seconds={int(timeout_seconds or runtime.codex_job_timeout_seconds or 900)}",
    )
