"""Paper API (redesign §5.2).

``GET /api/exam/types`` exposes the six-key question type registry
without ``parts`` -- Part is no longer an input (design §4.2).
``POST /api/materials/{id}/exam`` generates a whole paper from free
``blocks=[{type, count}]`` in user order, with an optional forced
completion ``layout_hint`` and a ``regenerate`` cache-busting marker
(design §4.4, §8.3). Since Task 14 every generation persists one
``papers`` row (spec + paper + usage JSON, design §5.1) and the
response is ``{paper_id, paper, skipped}``.

Suitability refusals (design §4.5): a partial refusal returns 200 with
``skipped: [{type, reason}]`` listing each refused block; when every
requested block is refused the endpoint answers 400 with
``{"detail": {"skipped": [...]}}`` so the caller sees each reason.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app import db, i18n
from app.schemas import ExamGenerateIn
from app.services import exam_gen
from app.services.exam_presets import QUESTION_TYPES
from app.services.jobs import _now, _uid
from app.services.llm import LlmError
from app.routers.settings import effective_settings, llm_cfg_or_none

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


@router.post("/materials/{material_id}/exam")
async def generate_exam(
    material_id: str, body: ExamGenerateIn, request: Request
):
    """Generate a blocks-based paper, persist it, answer with its id."""
    conn = request.app.state.conn
    row = conn.execute(
        "SELECT id, words_json, sentences_json FROM materials WHERE id=?",
        (material_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=i18n.t("common.material_not_found")
        )

    cfg = llm_cfg_or_none(effective_settings(conn))
    if cfg is None:
        raise HTTPException(status_code=400, detail=i18n.t("llm.no_key"))

    blocks = [{"type": b.type, "count": b.count} for b in body.blocks]
    try:
        result = await exam_gen.generate_paper(
            conn,
            {"id": row["id"], "words_json": row["words_json"],
             "sentences_json": row["sentences_json"]},
            blocks,
            cfg,
            lang=i18n.get_locale(),
            layout_hint=body.layout_hint,
            regenerate=body.regenerate,
        )
    except exam_gen.ExamAllRefusedError as exc:
        # Every block refused (§4.5): 400 with the structured skipped
        # body instead of a flat message. Must precede the generic
        # ExamGenError handler (it subclasses it).
        raise HTTPException(
            status_code=400, detail={"skipped": exc.skipped}
        ) from exc
    except exam_gen.ExamGenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Persist the generation (§5.1): what was asked (spec), what came
    # back (paper incl. visual scene), and the per-call usage ledger.
    paper_id = _uid()
    with db._write_lock:
        with conn:
            conn.execute(
                "INSERT INTO papers(id, material_id, spec_json, paper_json,"
                " generation_json, stale, created_at) VALUES(?,?,?,?,?,0,?)",
                (
                    paper_id,
                    material_id,
                    json.dumps(
                        {
                            "blocks": blocks,
                            "layout_hint": body.layout_hint,
                            "regenerate": body.regenerate,
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(result.paper, ensure_ascii=False),
                    json.dumps(result.usage, ensure_ascii=False),
                    _now(),
                ),
            )
    return {"paper_id": paper_id, "paper": result.paper, "skipped": result.skipped}
