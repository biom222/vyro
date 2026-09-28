from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


@dataclass(frozen=True, slots=True)
class CopyrightAssessment:
    level: Literal["low", "medium", "high", "unknown"]
    reason: str


_HIGH_RISK_MARKERS = {
    "full movie",
    "movie clip",
    "film scene",
    "episode",
    "season",
    "серия",
    "сезон",
    "фрагмент фильма",
    "сцена из фильма",
    "без перевода",
}

_LOWER_RISK_MARKERS = {
    "review",
    "analysis",
    "commentary",
    "обзор",
    "разбор",
    "критика",
    "reaction",
    "реакция",
}

_LOW_RISK_MARKERS = {
    "original footage",
    "licensed footage",
    "public domain",
    "собственная съёмка",
    "лицензированный материал",
    "общественное достояние",
}


def _contains_marker(text: str, marker: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text, flags=re.IGNORECASE) is not None


def assess_copyright_risk(
    title: str,
    description: str = "",
    source_channel: str = "",
) -> CopyrightAssessment:
    text = f"{title} {description}".casefold()
    if any(_contains_marker(text, marker) for marker in _HIGH_RISK_MARKERS):
        return CopyrightAssessment(
            level="high",
            reason="Похоже на повторную публикацию сцены или эпизода из защищённого произведения.",
        )
    if any(_contains_marker(text, marker) for marker in _LOW_RISK_MARKERS):
        return CopyrightAssessment(
            level="low",
            reason=(
                "Источник заявляет оригинальный или лицензированный материал; подтверждающие "
                "документы всё равно нужно сохранить."
            ),
        )
    if any(_contains_marker(text, marker) for marker in _LOWER_RISK_MARKERS):
        return CopyrightAssessment(
            level="medium",
            reason=(
                "Комментарий или разбор может быть трансформативным, но права и допустимость "
                "использования всё равно нужно проверить вручную."
            ),
        )
    source_note = f" Канал-источник: {source_channel}." if source_channel.strip() else ""
    return CopyrightAssessment(
        level="unknown",
        reason=(
            "Недостаточно данных для оценки; автоматическая проверка не является юридическим советом."
            + source_note
        ),
    )
