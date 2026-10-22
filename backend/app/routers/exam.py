"""Paper API (exploration branch).

Task 9 (six-key registry): GET /api/exam/types exposes the question type
registry without ``parts`` — Part is no longer an input (design §4.2).
The part/preset-based generation endpoint went away with the preset
registry; Task 10 reintroduces generation as the blocks API
(``{blocks: [{type, count}], layout_hint?, ...}``, design §5.2).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import i18n
from app.services.exam_presets import QUESTION_TYPES

router = APIRouter()


@router.get("/exam/types")
def list_question_types(request: Request):
    """The six question types in registry shape (layouts, visual, caps)."""
    lang = i18n.get_locale()
    return {
        "types": [
            {
                "key": qt.key,
                "name": qt.name_zh if lang == "zh" else qt.name_en,
                "name_zh": qt.name_zh,
                "name_en": qt.name_en,
                "answer_kind": qt.answer_kind,
                "layouts": list(qt.layouts),
                "generates_visual": qt.generates_visual,
                "max_count": qt.max_count,
                "min_words": qt.min_words,
            }
            for qt in QUESTION_TYPES.values()
        ]
    }
