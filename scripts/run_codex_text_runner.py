from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def restore_orphaned_requests(processing_dir: Path, requests_dir: Path, *, stale_seconds: int = 30) -> None:
    cutoff = time.time() - max(stale_seconds, 1)
    for item in processing_dir.glob("*.json"):
        try:
            if item.stat().st_mtime < cutoff:
                item.replace(requests_dir / item.name)
        except FileNotFoundError:
            continue


def invoke_codex_queue_item(request_path: Path, *, processing_dir: Path, responses_dir: Path, failed_dir: Path) -> None:
    processing_path = processing_dir / request_path.name
    request_path.replace(processing_path)
    request = read_json(processing_path)
    request_id = str(request.get("request_id") or processing_path.stem).strip()
    stage_name = str(request.get("stage_name") or "").strip()
    model = str(request.get("model") or "gpt-5.4").strip() or "gpt-5.4"
    workspace_dir = Path(str(request.get("workspace_dir") or "").strip() or Path.cwd()).resolve()
    if not workspace_dir.exists():
        workspace_dir = Path.cwd().resolve()
    prompt = str(request.get("prompt") or "")
    response_kind = str(request.get("response_kind") or "text").strip() or "text"
    response_schema = request.get("response_schema")

    temp_root = Path(tempfile.gettempdir()) / "bloggent-codex-runner"
    ensure_directory(temp_root)
    prompt_path = temp_root / f"{request_id}.prompt.txt"
    output_path = temp_root / f"{request_id}.output.txt"
    log_path = temp_root / f"{request_id}.log.txt"
    schema_path = temp_root / f"{request_id}.schema.json"

    codex_command = shutil.which("codex.cmd") or shutil.which("codex")
    if not codex_command:
        raise RuntimeError("codex executable was not found in PATH.")

    prompt_path.write_text(prompt, encoding="utf-8")
    if response_kind == "json_schema" and response_schema is not None:
        schema_path.write_text(json.dumps(response_schema, ensure_ascii=False, indent=2), encoding="utf-8")

    args = [
        "exec",
        "-m",
        model,
        "-C",
        str(workspace_dir),
        "-s",
        "read-only",
        "--disable",
        "plugins",
        "--skip-git-repo-check",
        "--ephemeral",
        "-o",
        str(output_path),
        "-",
    ]
    if response_kind == "json_schema" and schema_path.exists():
        args.extend(["--output-schema", str(schema_path)])

    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", codex_command, *args],
            input=prompt,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workspace_dir),
        )
        log_text = "\n".join(part.strip() for part in (proc.stderr, proc.stdout) if part and part.strip())
        log_path.write_text(log_text, encoding="utf-8")

        if proc.returncode != 0:
            raise RuntimeError(f"codex exited with code {proc.returncode}")

        content = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        write_json(
            responses_dir / f"{request_id}.json",
            {
                "status": "completed",
                "request_id": request_id,
                "stage_name": stage_name,
                "provider_name": "codex-cli",
                "provider_model": model,
                "runtime_kind": "codex_cli",
                "content": content,
                "log_path": str(log_path),
            },
        )
    except Exception as exc:  # noqa: BLE001
        log_excerpt = ""
        if log_path.exists():
            log_excerpt = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        write_json(
            failed_dir / f"{request_id}.json",
            {
                "status": "failed",
                "request_id": request_id,
                "stage_name": stage_name,
                "provider_name": "codex-cli",
                "provider_model": model,
                "runtime_kind": "codex_cli",
                "error": str(exc),
                "log_excerpt": log_excerpt,
            },
        )
    finally:
        processing_path.unlink(missing_ok=True)
        prompt_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        schema_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--poll-seconds", type=int, default=1)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    queue_root = Path(args.storage_root).resolve()
    requests_dir = queue_root / "codex-queue" / "requests"
    processing_dir = queue_root / "codex-queue" / "processing"
    responses_dir = queue_root / "codex-queue" / "responses"
    failed_dir = queue_root / "codex-queue" / "failed"
    for path in (requests_dir, processing_dir, responses_dir, failed_dir):
        ensure_directory(path)

    while True:
        restore_orphaned_requests(processing_dir, requests_dir)
        request = next(iter(sorted(requests_dir.glob("*.json"), key=lambda item: item.stat().st_mtime)), None)
        if request is None:
            if args.once:
                return 0
            time.sleep(max(args.poll_seconds, 1))
            continue
        invoke_codex_queue_item(
            request,
            processing_dir=processing_dir,
            responses_dir=responses_dir,
            failed_dir=failed_dir,
        )
        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
