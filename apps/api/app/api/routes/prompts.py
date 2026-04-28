from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.api import PromptTemplateRead, PromptTemplateUpdate
from app.services.content.prompt_service import get_prompt_template, list_prompt_templates, update_prompt_template
from app.api.deps.admin_auth import AdminMutationRoute

router = APIRouter(route_class=AdminMutationRoute)


@router.get("", response_model=list[PromptTemplateRead])
def get_prompts() -> list[dict]:
    return list_prompt_templates()


@router.get("/{prompt_key}", response_model=PromptTemplateRead)
def get_prompt(prompt_key: str) -> dict:
    try:
        return get_prompt_template(prompt_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Prompt template not found") from exc


@router.put("/{prompt_key}", response_model=PromptTemplateRead)
def update_prompt(prompt_key: str, payload: PromptTemplateUpdate) -> dict:
    try:
        return update_prompt_template(prompt_key, payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Prompt template not found") from exc
