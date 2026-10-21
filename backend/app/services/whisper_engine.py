"""mlx-whisper engine adapter (Task B9).

Maps ``word_timestamps=True`` segment output onto raw word dicts
{"w","s","e","p"} (p = word probability). ``mlx_whisper`` is imported
ONLY inside transcribe() so this module stays importable anywhere.
"""
from __future__ import annotations

from typing import Any

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def result_to_words(result: Any) -> list[dict]:
    """Flatten mlx-whisper segments[*].words[] into raw word dicts."""
    segments = []
    if isinstance(result, dict):
        segments = result.get("segments", []) or []
    words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []) or []:
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            item = {
                "w": text,
                "s": float(w.get("start", 0.0)),
                "e": float(w.get("end", 0.0)),
            }
            if w.get("probability") is not None:
                item["p"] = float(w["probability"])
            words.append(item)
    return words


class WhisperEngine:
    name = "whisper"

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model  # mlx_whisper needs no eager construction

    def transcribe(self, path: str) -> list[dict]:
        import mlx_whisper  # lazy: darwin only

        result = mlx_whisper.transcribe(
            path, path_or_hf_repo=self.model, word_timestamps=True
        )
        return result_to_words(result)
