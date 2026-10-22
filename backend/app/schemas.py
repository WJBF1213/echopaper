"""Pydantic request models for the API layer (Task B12, spec §8)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
    engine: Optional[str] = None
    parakeet_model: Optional[str] = None
    whisper_model: Optional[str] = None
    faster_whisper_model: Optional[str] = None
    idle_unload_min: Optional[int] = None


class GenSettingsIn(BaseModel):
    blank_count: Optional[int] = Field(default=None, ge=1, le=40)


class SettingsIn(BaseModel):
    llm: Optional[LlmSettingsIn] = None
    asr: Optional[AsrSettingsIn] = None
    gen: Optional[GenSettingsIn] = None


class TranscriptIn(BaseModel):
    transcript: str


class SetCreateIn(BaseModel):
    mode: str = "llm"  # 'llm' | 'nouns' | 'manual'
    blank_count: int = Field(default=10, ge=0, le=40)
    transcript_override: Optional[str] = None


class ExamGenerateIn(BaseModel):
    """Exploration branch: request a full typed paper for one part."""

    part: int = Field(default=1, ge=1, le=4)
    preset: Optional[str] = None


class AnswerIn(BaseModel):
    blank_id: str
    text: str = ""


class AttemptIn(BaseModel):
    answers: list[AnswerIn]
    duration_s: Optional[float] = None


class DictationItemIn(BaseModel):
    word_index: int
    text: str = ""


class DictationIn(BaseModel):
    mode: str = "dictation"
    items: list[DictationItemIn]
    duration_s: Optional[float] = None


class TranslateIn(BaseModel):
    text: str
