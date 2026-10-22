"""faster-whisper (CTranslate2) engine adapter — Windows / macOS / Linux.

This is the universal fallback engine: CTranslate2 runs on NVIDIA CUDA when
the CUDA runtime is actually present and on plain CPU otherwise, so the same
code path works on every platform without MLX. ``faster_whisper`` is imported
lazily so this module (and its mapping function) stays importable even when
the package is absent.

Output follows the raw-word schema {"w","s","e","p"} used by the rest of the
pipeline; ``p`` is the word probability reported by the model.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

DEFAULT_MODEL = "large-v3-turbo"  # faster-whisper shorthand for the CT2 turbo model

# A driver can be installed while the CUDA runtime (cuBLAS/cuDNN) is not.
# These messages mean "the GPU path cannot work here", not "transcription
# failed", so they trigger the CPU fallback instead of surfacing an error.
_CUDA_RUNTIME_ERRORS = re.compile(
    r"cublas|cudnn|cuda|libdevice|no kernel image|out of memory", re.I
)


def result_to_words(segments: Iterable[Any]) -> list[dict]:
    """Flatten faster-whisper segments[*].words[] into raw word dicts."""
    words: list[dict] = []
    for seg in segments:
        for w in getattr(seg, "words", None) or []:
            text = str(getattr(w, "word", "") or "").strip()
            if not text:
                continue
            item = {
                "w": text,
                "s": float(getattr(w, "start", 0.0) or 0.0),
                "e": float(getattr(w, "end", 0.0) or 0.0),
            }
            probability = getattr(w, "probability", None)
            if probability is not None:
                item["p"] = float(probability)
            words.append(item)
    return words


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _probe_cuda(model: str):
    """Build a CUDA model and run one tiny inference.

    ``get_cuda_device_count()`` only proves a driver exists. The real failure
    (missing ``cublas64_12.dll`` / cuDNN) appears on the first encode, so a
    half-second warm-up is the only reliable check — and it costs ~1s once.
    """
    import numpy as np
    from faster_whisper import WhisperModel

    try:
        candidate = WhisperModel(model, device="cuda", compute_type="float16")
        segments, _ = candidate.transcribe(
            np.zeros(8000, dtype=np.float32), language="en", beam_size=1
        )
        for _ in segments:  # consume the lazy generator to force encoding
            break
        return candidate
    except Exception:
        return None


class FasterWhisperEngine:
    name = "faster_whisper"

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._model, self._device, self._resolved = self._load(model)

    @staticmethod
    def _load(model: str):
        from faster_whisper import WhisperModel

        from app.services.model_download import ensure_model

        resolved = ensure_model(model)
        if _cuda_available():
            cuda_model = _probe_cuda(resolved)
            if cuda_model is not None:
                return cuda_model, "cuda", resolved
        return WhisperModel(resolved, device="cpu", compute_type="int8"), "cpu", resolved
    def transcribe(self, path: str) -> list[dict]:
        try:
            return self._transcribe(path)
        except RuntimeError as exc:
            if self._device != "cuda" or not _CUDA_RUNTIME_ERRORS.search(str(exc)):
                raise
            # CUDA broke after load (OOM, runtime DLL evicted). One CPU retry
            # beats failing the whole ingestion job.
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._resolved, device="cpu", compute_type="int8"
            )
            self._device = "cpu"
            return self._transcribe(path)

    def _transcribe(self, path: str) -> list[dict]:
        segments, _info = self._model.transcribe(
            path,
            language="en",
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            # Long IELTS tracks invite repetition loops when each window is
            # conditioned on the previous one; the word list is authoritative.
            condition_on_previous_text=False,
        )
        return result_to_words(segments)
