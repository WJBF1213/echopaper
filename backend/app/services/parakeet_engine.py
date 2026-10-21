"""parakeet-mlx engine adapter (Task B9).

Maps AlignedToken/AlignedSentence structures onto the raw-word schema
{"w","s","e"} — timestamps are native (TDT duration prediction), so no
confidence field. ``parakeet_mlx`` is imported ONLY inside __init__ so
this module (and its mapping function) stays importable on any platform.
"""
from __future__ import annotations

from typing import Any

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


def result_to_words(result: Any) -> list[dict]:
    """Flatten a parakeet AlignedResult into raw word dicts.

    Handles both shapes seen across parakeet-mlx versions: a flat
    ``result.tokens`` list and ``result.segments[*].tokens``.
    """
    tokens: list[Any] = []
    flat = getattr(result, "tokens", None)
    segments = getattr(result, "segments", None)
    if flat:
        tokens.extend(flat)
    elif segments:
        for seg in segments:
            tokens.extend(getattr(seg, "tokens", None) or [])
    words: list[dict] = []
    for tok in tokens:
        text = getattr(tok, "text", None)
        if text is None:
            continue
        words.append(
            {
                "w": str(text),
                "s": float(getattr(tok, "start", 0.0)),
                "e": float(getattr(tok, "end", 0.0)),
            }
        )
    return words


class ParakeetEngine:
    name = "parakeet"

    def __init__(self, model: str = DEFAULT_MODEL):
        from parakeet_mlx import from_pretrained  # lazy: darwin only

        self.model = model
        self._model = from_pretrained(model)

    def transcribe(self, path: str) -> list[dict]:
        result = self._model.transcribe(path)
        return result_to_words(result)
