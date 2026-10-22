"""Prompts API (Task 6): browse the prompt registry and manage per-prompt
overrides on top of the Task 5 service (``app.services.prompts``).

GET /api/prompts  -> the full catalogue; ``title`` follows the request's
Accept-Language (zh default), so the same registry renders in either UI
language. PUT /api/prompts sets or clears one override.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app import i18n
from app.schemas import PromptPutIn
from app.services import prompts

router = APIRouter()


def _localized(entry: dict) -> dict:
    """One catalogue entry with ``title`` picked for the request locale."""
    out = {
        k: v for k, v in entry.items() if k not in ("title", "title_zh", "title_en")
    }
    if i18n.get_locale() == "en":
        out["title"] = entry["title_en"]
    else:
        out["title"] = entry["title_zh"]
    return out


@router.get("/prompts")
def list_prompts(request: Request):
    conn = request.app.state.conn
    return [_localized(e) for e in prompts.list_prompts(conn)]


@router.put("/prompts")
def put_prompt(body: PromptPutIn, request: Request):
    # SEMANTICS (plan Review Focus #3): an empty-string / null / blank
    # ``text`` RESETS this prompt to its default — the OPPOSITE of the
    # settings PUT convention, where a blank api_key means "keep the stored
    # value". Do not "fix" this to match settings; the prompts UI relies on
    # empty-means-reset as its "restore default" action.
    conn = request.app.state.conn
    spec = next(
        (s for s in prompts.ALL_PROMPTS if s.key == body.key), None
    )
    if spec is None:
        raise HTTPException(
            status_code=404, detail=i18n.t("prompts.not_found", name=body.key)
        )

    text = body.text
    if text is not None and text.strip():
        # A custom prompt must keep every placeholder the renderer needs;
        # otherwise rendering would silently emit a raw ``{{var}}``.
        missing = [
            "{{" + name + "}}"
            for name in spec.variables
            if "{{" + name + "}}" not in text
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=i18n.t(
                    "prompts.missing_placeholders",
                    name=body.key,
                    missing=", ".join(missing),
                ),
            )
        prompts.set_override(conn, body.key, text)
    else:
        # Reset: set_override treats None as "clear the override".
        prompts.set_override(conn, body.key, None)

    entry = next(
        e for e in prompts.list_prompts(conn) if e["key"] == body.key
    )
    return _localized(entry)
