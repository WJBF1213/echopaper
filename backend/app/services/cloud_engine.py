"""Cloud transcription engine (Task 3): OpenAI-compatible
``POST {base_url}/audio/transcriptions`` with word timestamps.

Design facts (verified):
- multipart fields: ``file``, ``model``, ``response_format=verbose_json``,
  ``timestamp_granularities[]=word``, ``language=en``; the response's
  ``segments[*].words[*]`` entries carry ``{word, start, end}``.
- Providers cap uploads (~24 MB): :func:`app.services.audio.
  prepare_upload_audio` recompresses to 16 kHz mono ~48 kbps MP3 and
  splits into ~10-minute chunks when needed; each chunk's word times
  are offset by the chunk start, then concatenated.

The engine reads its configuration (``cloud_base_url`` /
``cloud_model`` / ``cloud_api_key``) from the effective ASR settings at
EVERY call (the manager passes its settings_fn), so a key saved
mid-flight applies to the next job. 2 retries with 2 s/5 s backoff on
429/5xx/transport errors; the final failure raises ``RuntimeError``
including the provider status/body — jobs.py turns that into the job
error state with the message. Stdlib + httpx; PyAV only via audio.py.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

from app import i18n
from app.services import audio as audio_mod

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "whisper-large-v3-turbo"
REQUEST_TIMEOUT_S = 600.0
TEST_TIMEOUT_S = 10.0
RETRY_BACKOFF_S = (2.0, 5.0)  # 1 try + 2 retries

#: multipart content types per upload extension (deterministic, no
#: registry-dependent mimetypes guessing)
_UPLOAD_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


def resolve_cloud_cfg(cfg: Mapping | None) -> tuple[str, str, str]:
    """(base_url, model, api_key) from an effective-asr-style dict."""
    s = dict(cfg or {})
    base_url = (s.get("cloud_base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    model = (s.get("cloud_model") or DEFAULT_MODEL).strip()
    api_key = (s.get("cloud_api_key") or "").strip()
    return base_url, model, api_key


def _expand_segment(segment: Mapping) -> list[dict]:
    """Segment-level fallback: spread text tokens evenly across
    [start, end] so timestamps stay usable when a provider omits words."""
    tokens = str(segment.get("text", "") or "").split()
    if not tokens:
        return []
    start = float(segment.get("start", 0.0) or 0.0)
    end = float(segment.get("end", start) or start)
    if end < start:
        end = start
    step = (end - start) / len(tokens)
    return [
        {"w": token, "s": start + i * step, "e": start + (i + 1) * step}
        for i, token in enumerate(tokens)
    ]


def words_from_verbose_json(payload: Any) -> list[dict]:
    """``segments[*].words[*]`` -> raw word dicts ``{"w","s","e"}``.

    A segment without per-word timing falls back to :func:`_expand_segment`.
    """
    if not isinstance(payload, Mapping):
        return []
    words: list[dict] = []
    for segment in payload.get("segments") or []:
        if not isinstance(segment, Mapping):
            continue
        seg_words = segment.get("words") or []
        if seg_words:
            for item in seg_words:
                if not isinstance(item, Mapping):
                    continue
                text = str(item.get("word", "") or "").strip()
                if not text:
                    continue
                words.append(
                    {
                        "w": text,
                        "s": float(item.get("start", 0.0) or 0.0),
                        "e": float(item.get("end", 0.0) or 0.0),
                    }
                )
        else:
            words.extend(_expand_segment(segment))
    return words


def _offset_words(words: list[dict], offset: float) -> list[dict]:
    if not offset:
        return words
    return [
        {"w": w["w"], "s": w["s"] + offset, "e": w["e"] + offset}
        for w in words
    ]


def _upload_mime(path: str) -> str:
    return _UPLOAD_MIME.get(Path(path).suffix.lower(), "application/octet-stream")


class CloudEngine:
    """AsrEngine implementation backed by a cloud transcription API."""

    name = "cloud"

    def __init__(
        self,
        settings_fn: Callable[[], Mapping] | None = None,
        backoff_s: tuple[float, ...] | None = None,
    ):
        self._settings_fn = settings_fn
        self._backoff = tuple(backoff_s) if backoff_s else RETRY_BACKOFF_S

    # ------------------------------------------------------------- AsrEngine
    def transcribe(self, path: str, *, client=None) -> list[dict]:
        base_url, model, api_key = resolve_cloud_cfg(
            self._settings_fn() if self._settings_fn is not None else None
        )
        if not api_key:
            raise RuntimeError(i18n.t("asr.no_key"))
        parts = audio_mod.prepare_upload_audio(path)
        own = client is None
        http = client if client is not None else httpx.Client(
            timeout=REQUEST_TIMEOUT_S
        )
        try:
            words: list[dict] = []
            for chunk_path, offset in parts:
                payload = self._post_with_retries(
                    http, chunk_path, base_url, model, api_key
                )
                words.extend(_offset_words(words_from_verbose_json(payload), offset))
            return words
        finally:
            if own:
                http.close()
            for chunk_path, _offset in parts:
                if chunk_path != str(path):  # temps only, never the original
                    Path(chunk_path).unlink(missing_ok=True)

    # ------------------------------------------------------------- internals
    def _post_with_retries(
        self,
        client,
        path: str,
        base_url: str,
        model: str,
        api_key: str,
    ) -> Any:
        """One multipart POST with up to 2 retries (429/5xx/transport).

        The final failure raises RuntimeError whose message includes the
        provider status and body.
        """
        url = f"{base_url}/audio/transcriptions"
        attempts = len(self._backoff) + 1
        last_error = ""
        for attempt in range(attempts):
            if attempt:
                time.sleep(self._backoff[min(attempt - 1, len(self._backoff) - 1)])
            try:
                with open(path, "rb") as fh:
                    resp = client.post(
                        url,
                        files={"file": (Path(path).name, fh, _upload_mime(path))},
                        data={
                            "model": model,
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "word",
                            "language": "en",
                        },
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise RuntimeError(
                        i18n.t("asr.request_failed", error=f"invalid JSON: {exc}")
                    ) from exc
            last_error = f"HTTP {resp.status_code}: {(resp.text or '')[:500]}"
            if resp.status_code != 429 and resp.status_code < 500:
                break  # client error: retrying cannot help
        raise RuntimeError(i18n.t("asr.request_failed", error=last_error))


async def test_cloud_connection(
    cfg: Mapping | None, client=None
) -> tuple[bool, str]:
    """Probe ``GET {base_url}/models`` with the Bearer key (10 s).

    Mirrors ``llm.test_connection``: 200 -> ok (with a note when the
    configured model is missing from a parseable list), 401/403 ->
    localized "key invalid", transport/timeout -> localized "unreachable".
    """
    base_url, model, api_key = resolve_cloud_cfg(cfg)
    if not api_key:
        return False, i18n.t("asr.no_key")
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=TEST_TIMEOUT_S)
    try:
        resp = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError:
        return False, i18n.t("asr.test_unreachable")
    finally:
        if own:
            await client.aclose()
    if resp.status_code in (401, 403):
        return False, i18n.t("asr.test_key_invalid")
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}: {(resp.text or '')[:300]}"
    try:
        listed = [
            item.get("id")
            for item in (resp.json().get("data") or [])
            if isinstance(item, dict)
        ]
    except Exception:
        return True, i18n.t("asr.test_ok")  # list unparseable: skip the check
    if model and listed and model not in listed:
        return True, i18n.t("asr.test_model_missing", model=model)
    return True, i18n.t("asr.test_ok")
