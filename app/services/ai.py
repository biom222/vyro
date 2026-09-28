from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import settings


class ClipSuggestion(BaseModel):
    title: str
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    score: float = Field(ge=0, le=100)
    reason: str


class ContentPack(BaseModel):
    title: str
    description: str
    hooks: list[str]
    hashtags: list[str]
    clip_suggestions: list[ClipSuggestion]
    copyright_note: str


class ContentAssistant(ABC):
    @abstractmethod
    def generate(self, source_text: str, duration: float | None = None) -> ContentPack:
        raise NotImplementedError


class MockContentAssistant(ContentAssistant):
    def generate(self, source_text: str, duration: float | None = None) -> ContentPack:
        clean = " ".join(source_text.split()) or "Новый ролик"
        preview = clean[:80].rstrip(" .,;:")
        clip_end = max(3.0, min(duration or 30.0, 45.0))
        return ContentPack(
            title=f"{preview}: главное за минуту"[:100],
            description=f"Короткий вертикальный ролик по теме: {preview}.",
            hooks=[
                f"Почему все обсуждают: {preview}?",
                "Досмотри до конца — главный момент впереди.",
                "Один фрагмент, который меняет весь контекст.",
            ],
            hashtags=["#shorts", "#видео", "#рекомендации"],
            clip_suggestions=[
                ClipSuggestion(
                    title=preview[:60],
                    start_time=0.0,
                    end_time=clip_end,
                    score=72.0,
                    reason="Mock suggestion based on the available duration.",
                )
            ],
            copyright_note=(
                "Проверьте права на исходное видео. AI-оценка не заменяет юридическую проверку."
            ),
        )


class OpenAIContentAssistant(ContentAssistant):
    _schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hooks": {"type": "array", "items": {"type": "string"}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "clip_suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "start_time": {"type": "number"},
                        "end_time": {"type": "number"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["title", "start_time", "end_time", "score", "reason"],
                },
            },
            "copyright_note": {"type": "string"},
        },
        "required": [
            "title",
            "description",
            "hooks",
            "hashtags",
            "clip_suggestions",
            "copyright_note",
        ],
    }

    def __init__(self, client: httpx.Client | None = None):
        if not settings.openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        self._client = client

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return str(content["text"])
        raise RuntimeError("OpenAI response did not contain output_text")

    def generate(self, source_text: str, duration: float | None = None) -> ContentPack:
        prompt = (
            "Create a Russian-language content pack for a vertical short. "
            "Suggest only time ranges inside the supplied duration and explicitly warn about "
            "copyright uncertainty. Source transcript or idea:\n"
            f"{source_text}\nDuration: {duration if duration is not None else 'unknown'} seconds."
        )
        request = {
            "model": settings.openai_model,
            "instructions": (
                "You are a short-form video producer. Be concise, avoid unsupported factual "
                "claims, and never claim that copyrighted footage is safe to reuse."
            ),
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "content_pack",
                    "strict": True,
                    "schema": self._schema,
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post("/responses", headers=headers, json=request)
        else:
            with httpx.Client(base_url=settings.openai_base_url, timeout=90.0) as client:
                response = client.post("/responses", headers=headers, json=request)
        response.raise_for_status()
        return ContentPack.model_validate_json(self._output_text(response.json()))


def get_content_assistant() -> ContentAssistant:
    provider = settings.ai_provider.strip().lower()
    if provider == "mock":
        return MockContentAssistant()
    if provider == "openai":
        return OpenAIContentAssistant()
    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")


def content_pack_to_json(pack: ContentPack) -> str:
    return json.dumps(pack.model_dump(), ensure_ascii=False, indent=2)
