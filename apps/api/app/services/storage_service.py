from __future__ import annotations

import base64
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.providers.base import ProviderRuntimeError
from app.services.settings_service import get_settings_map


def ensure_storage_dirs() -> None:
    settings.storage_images_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_html_dir.mkdir(parents=True, exist_ok=True)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_storage_public_url(relative: Path, base_url: str | None = None) -> str:
    resolved_base_url = _normalize_base_url(base_url or settings.public_api_base_url)
    return f"{resolved_base_url}/storage/{relative.as_posix()}"


def _looks_private_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        return True
    return False


def is_private_asset_url(url: str) -> bool:
    return _looks_private_url(url)


def _resolve_local_public_base_url(values: dict[str, str]) -> str:
    configured = (values.get("public_asset_base_url") or "").strip()
    if configured:
        return _normalize_base_url(configured)
    return _normalize_base_url(settings.public_api_base_url)


def _github_pages_base_url(values: dict[str, str]) -> str:
    configured = (values.get("github_pages_base_url") or "").strip()
    if configured:
        return _normalize_base_url(configured)

    owner = (values.get("github_pages_owner") or "").strip()
    repo = (values.get("github_pages_repo") or "").strip()
    if not owner or not repo:
        return ""
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io"
    return f"https://{owner}.github.io/{repo}"


def _build_github_pages_asset_path(values: dict[str, str], filename: str) -> str:
    root_dir = (values.get("github_pages_assets_dir") or "assets/images").strip().strip("/")
    now = datetime.now(timezone.utc)
    return f"{root_dir}/{now:%Y/%m/%d}/{filename}"


def _github_api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_github_pages_source_path(owner: str, repo: str, token: str) -> str:
    response = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}/pages",
        headers=_github_api_headers(token),
        timeout=60.0,
    )
    if response.status_code == 404:
        return ""
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=response.status_code,
            message="GitHub Pages 설정 조회에 실패했습니다.",
            detail=response.text,
        )
    payload = response.json()
    return str((payload.get("source") or {}).get("path") or "").strip()


def _normalize_github_pages_repo_asset_path(asset_path: str, source_path: str) -> str:
    normalized_asset_path = asset_path.strip("/")
    normalized_source = source_path.strip().strip("/")
    if not normalized_source:
        return normalized_asset_path
    if normalized_asset_path.startswith(f"{normalized_source}/") or normalized_asset_path == normalized_source:
        return normalized_asset_path
    return f"{normalized_source}/{normalized_asset_path}"


def _normalize_github_pages_public_asset_path(repo_asset_path: str, source_path: str) -> str:
    normalized_repo_path = repo_asset_path.strip("/")
    normalized_source = source_path.strip().strip("/")
    if normalized_source and normalized_repo_path.startswith(f"{normalized_source}/"):
        return normalized_repo_path[len(normalized_source) + 1 :]
    if normalized_source and normalized_repo_path == normalized_source:
        return ""
    return normalized_repo_path


def _upload_to_github_pages(
    *,
    values: dict[str, str],
    filename: str,
    content: bytes,
) -> tuple[str, dict]:
    owner = (values.get("github_pages_owner") or "").strip()
    repo = (values.get("github_pages_repo") or "").strip()
    branch = (values.get("github_pages_branch") or "main").strip()
    token = (values.get("github_pages_token") or "").strip()
    base_url = _github_pages_base_url(values)

    if not owner or not repo or not token:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=422,
            message="GitHub Pages 공개 업로드 설정이 비어 있습니다.",
            detail="github_pages_owner, github_pages_repo, github_pages_token을 모두 입력해야 합니다.",
        )
    if not base_url:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=422,
            message="GitHub Pages 공개 URL을 계산할 수 없습니다.",
            detail="github_pages_base_url을 직접 입력하거나 owner/repo를 올바르게 설정해주세요.",
        )

    source_path = _fetch_github_pages_source_path(owner, repo, token)
    public_asset_path = _build_github_pages_asset_path(values, filename)
    repo_asset_path = _normalize_github_pages_repo_asset_path(public_asset_path, source_path)
    normalized_public_path = _normalize_github_pages_public_asset_path(repo_asset_path, source_path)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_asset_path}"
    headers = _github_api_headers(token)

    existing_sha = None
    get_response = httpx.get(api_url, headers=headers, params={"ref": branch}, timeout=60.0)
    if get_response.status_code == 200:
        existing_sha = get_response.json().get("sha")
    elif get_response.status_code != 404:
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=get_response.status_code,
            message="GitHub Pages 기존 파일 확인에 실패했습니다.",
            detail=get_response.text,
        )

    payload = {
        "message": f"bloggent: upload asset {repo_asset_path}",
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha

    response = httpx.put(api_url, headers=headers, json=payload, timeout=120.0)
    if not response.is_success:
        detail = response.text
        try:
            data = response.json()
            detail = data.get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="github_pages",
            status_code=response.status_code,
            message="GitHub Pages 이미지 업로드에 실패했습니다.",
            detail=detail,
        )

    response_payload = response.json()
    public_url = f"{base_url}/{normalized_public_path}"
    return public_url, {
        "asset_path": normalized_public_path,
        "repo_asset_path": repo_asset_path,
        "pages_source_path": source_path or "/",
        "branch": branch,
        "response": response_payload,
    }


def _cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    serialized = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1(f"{serialized}{api_secret}".encode("utf-8")).hexdigest()


def _upload_to_cloudinary(
    *,
    values: dict[str, str],
    filename: str,
    content: bytes,
) -> tuple[str, dict]:
    cloud_name = (values.get("cloudinary_cloud_name") or "").strip()
    api_key = (values.get("cloudinary_api_key") or "").strip()
    api_secret = (values.get("cloudinary_api_secret") or "").strip()
    folder = (values.get("cloudinary_folder") or "bloggent").strip()

    if not cloud_name or not api_key or not api_secret:
        raise ProviderRuntimeError(
            provider="cloudinary",
            status_code=422,
            message="Cloudinary 공개 업로드 설정이 비어 있습니다.",
            detail="cloud_name, api_key, api_secret를 모두 입력해야 공개 이미지 업로드를 사용할 수 있습니다.",
        )

    timestamp = str(int(time.time()))
    public_id = Path(filename).stem
    sign_params = {
        "folder": folder,
        "overwrite": "true",
        "public_id": public_id,
        "timestamp": timestamp,
    }
    signature = _cloudinary_signature(sign_params, api_secret)
    response = httpx.post(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data={
            "api_key": api_key,
            "folder": folder,
            "overwrite": "true",
            "public_id": public_id,
            "signature": signature,
            "timestamp": timestamp,
        },
        files={"file": (filename, content, "application/octet-stream")},
        timeout=120.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="cloudinary",
            status_code=response.status_code,
            message="Cloudinary 공개 이미지 업로드에 실패했습니다.",
            detail=detail,
        )

    payload = response.json()
    return payload.get("secure_url") or payload.get("url") or "", payload


def save_binary(
    *,
    subdir: str,
    filename: str,
    content: bytes,
    public_base_url: str | None = None,
) -> tuple[str, str]:
    ensure_storage_dirs()
    relative = Path(subdir) / filename
    destination = Path(settings.storage_root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    public_url = build_storage_public_url(relative, public_base_url)
    return str(destination), public_url


def save_public_binary(
    db: Session,
    *,
    subdir: str,
    filename: str,
    content: bytes,
) -> tuple[str, str, dict]:
    values = get_settings_map(db)
    local_base_url = _resolve_local_public_base_url(values)
    file_path, local_public_url = save_binary(
        subdir=subdir,
        filename=filename,
        content=content,
        public_base_url=local_base_url,
    )
    provider = (values.get("public_image_provider") or "local").strip().lower()
    metadata = {
        "storage_provider": provider,
        "local_public_url": local_public_url,
        "local_public_url_is_private": _looks_private_url(local_public_url),
    }

    if provider == "cloudinary":
        public_url, upload_payload = _upload_to_cloudinary(values=values, filename=filename, content=content)
        metadata["cloudinary"] = upload_payload
        metadata["public_url"] = public_url
        return file_path, public_url, metadata

    if provider == "github_pages":
        public_url, upload_payload = _upload_to_github_pages(values=values, filename=filename, content=content)
        metadata["github_pages"] = upload_payload
        metadata["public_url"] = public_url
        return file_path, public_url, metadata

    metadata["public_url"] = local_public_url
    return file_path, local_public_url, metadata


def ensure_existing_public_image_url(db: Session, *, file_path: str) -> tuple[str, dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")

    try:
        relative = path.resolve().relative_to(Path(settings.storage_root).resolve())
    except ValueError:
        relative = Path("images") / path.name

    values = get_settings_map(db)
    local_base_url = _resolve_local_public_base_url(values)
    local_public_url = build_storage_public_url(relative, local_base_url)
    provider = (values.get("public_image_provider") or "local").strip().lower()
    metadata = {
        "storage_provider": provider,
        "local_public_url": local_public_url,
        "local_public_url_is_private": _looks_private_url(local_public_url),
    }

    if provider == "cloudinary":
        public_url, upload_payload = _upload_to_cloudinary(values=values, filename=path.name, content=path.read_bytes())
        metadata["cloudinary"] = upload_payload
        metadata["public_url"] = public_url
        return public_url, metadata

    if provider == "github_pages":
        public_url, upload_payload = _upload_to_github_pages(values=values, filename=path.name, content=path.read_bytes())
        metadata["github_pages"] = upload_payload
        metadata["public_url"] = public_url
        return public_url, metadata

    metadata["public_url"] = local_public_url
    return local_public_url, metadata


def save_html(*, slug: str, html: str) -> tuple[str, str]:
    ensure_storage_dirs()
    filename = f"{slug}.html"
    relative = Path("html") / filename
    destination = Path(settings.storage_root) / relative
    destination.write_text(html, encoding="utf-8")
    public_url = build_storage_public_url(relative)
    return str(destination), public_url


def clear_generated_storage(*, subdirs: tuple[str, ...] = ("images", "html")) -> int:
    ensure_storage_dirs()
    deleted_files = 0

    for subdir in subdirs:
        root = Path(settings.storage_root) / subdir
        if not root.exists():
            continue

        for path in sorted(root.rglob("*"), reverse=True):
            if path.name == ".gitkeep":
                continue
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted_files += 1
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    return deleted_files
