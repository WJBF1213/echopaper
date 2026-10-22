"""Experimental full paper API (exploration branch).

Read-only: generates an IELTS paper on demand and returns it as JSON.
Nothing is persisted, so this cannot disturb existing sets/attempts.

This router exists only on the ``explore/llm-exam-generation`` branch.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app import i18n
from app.schemas import ExamGenerateIn
from app.services import exam_gen
from app.services.exam_presets import (
    QUESTION_TYPES,
    PRESETS,
    default_preset,
    get_preset,
    localized,
    presets_for_part,
)
from app.services.llm import LlmError
from app.routers.settings import effective_settings, llm_cfg_or_none

router = APIRouter()


@router.get("/exam/types")
def list_question_types(request: Request):
    """Every supported IELTS question type plus the paper presets."""
    lang = i18n.get_locale()
    return {
        "types": [
            {
                "key": qt.key,
                "label": localized(qt.label, lang),
                "parts": list(qt.parts),
                "answer_kind": qt.answer_kind,
                "needs_visual": qt.needs_visual,
                "word_limit": qt.word_limit,
                "instruction": qt.instruction,
            }
            for qt in QUESTION_TYPES.values()
        ],
        "presets": [
            {
                "key": p.key,
                "part": p.part,
                "label": localized(p.label, lang),
                "total_items": p.total_items,
                "groups": [
                    {"type": g.type_key, "count": g.count} for g in p.groups
                ],
            }
            for p in PRESETS.values()
        ],
    }


@router.post("/materials/{material_id}/exam")
async def generate_exam(
    material_id: str, body: ExamGenerateIn, request: Request
):
    """Generate a full paper for one part; returns JSON, persists nothing."""
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT * FROM materials WHERE id=?", (material_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=i18n.t("common.material_not_found"))
    words = json.loads(row["words_json"] or "[]")
    sentences = json.loads(row["sentences_json"] or "[]")
    if not words:
        raise HTTPException(
            status_code=400, detail=i18n.t("common.material_no_words")
        )

    if body.part not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="part must be 1-4")
    preset = body.preset or default_preset(body.part)
    try:
        spec = get_preset(preset)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if spec.part != body.part:
        raise HTTPException(
            status_code=400,
            detail=(
                f"preset {preset} is for part {spec.part}, "
                f"not part {body.part}"
            ),
        )

    cfg = llm_cfg_or_none(effective_settings(conn))
    if cfg is None:
        raise HTTPException(status_code=400, detail=i18n.t("llm.no_key"))
    try:
        paper = await exam_gen.generate_paper(
            words,
            sentences,
            part=body.part,
            preset=preset,
            llm_cfg=cfg,
            material_id=material_id,
            lang=i18n.get_locale(),
        )
    except exam_gen.ExamGenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        **paper.to_dict(),
        "available_presets": [
            {
                "key": p.key,
                "label": localized(p.label, i18n.get_locale()),
            }
            for p in presets_for_part(body.part)
        ],
    }
