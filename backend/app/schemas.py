"""Pydantic request models for the API layer (Task B12, spec §8)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class LlmSettingsIn(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None  # write-only
    max_context_tokens: Optional[int] = None


class LlmTestIn(BaseModel):
    """Optional overrides: test exactly what the settings form shows."""

    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None  # blank keeps the stored key


class AsrSettingsIn(BaseModel):
    # Validated then ignored: the engine is always derived from the
    # platform (services.engines.local_engine), never stored or switched.
    engine: Optional[str] = None
    idle_unload_min: Optional[int] = None


class SettingsIn(BaseModel):
    llm: Optional[LlmSettingsIn] = None
    asr: Optional[AsrSettingsIn] = None


class TranscriptIn(BaseModel):
    transcript: str


# T10: the paper-generation request body (design §5.2): free blocks in user
# order, an optional forced completion layout, and the regenerate marker.
class ExamBlockIn(BaseModel):
    """One ``{type, count}`` block; count is capped by the type registry."""

    type: str
    count: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def _check_registry(self) -> "ExamBlockIn":
        from app.services.exam_presets import QUESTION_TYPES

        qtype = QUESTION_TYPES.get(self.type)
        if qtype is None:
            raise ValueError(
                f"unknown question type: {self.type!r}; "
                f"available: {', '.join(sorted(QUESTION_TYPES))}"
            )
        if self.count > qtype.max_count:
            raise ValueError(
                f"count for {self.type} must be 1-{qtype.max_count}"
            )
        return self


class ExamGenerateIn(BaseModel):
    """POST /api/materials/{id}/exam body (design §5.2)."""

    blocks: list[ExamBlockIn] = Field(min_length=1)
    layout_hint: Optional[str] = None
    regenerate: bool = False

    @field_validator("layout_hint")
    @classmethod
    def _check_layout_hint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        from app.services.exam_presets import QUESTION_TYPES

        allowed = QUESTION_TYPES["completion"].layouts
        if value not in allowed:
            raise ValueError(
                f"layout_hint must be one of {list(allowed)}, got {value!r}"
            )
        return value


class PaperAttemptIn(BaseModel):
    """POST /api/papers/{id}/attempts body (design §5.2, Task 15).

    ``answers`` maps the item number (a JSON object key, hence a string)
    to the candidate's answer string: a letter, comma-joined letters for
    multi-answer items, or free text for span items. Keys matching no
    item number of the paper are ignored; missing items grade wrong.
    """

    answers: dict[str, str] = Field(default_factory=dict)


class TranslateIn(BaseModel):
    text: str


class PromptPutIn(BaseModel):
    """PUT /api/prompts body (Task 6).

    ``text`` that is null/empty/whitespace RESETS the prompt to its default
    — the opposite of the settings ``api_key`` convention (blank keeps the
    stored value). Non-empty text must contain every ``{{placeholder}}`` the
    registry spec declares; the router validates that.
    """

    key: str
    text: Optional[str] = None
