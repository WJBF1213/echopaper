# EchoPaper

English | [中文](README.zh-CN.md)

A local-first IELTS-style listening practice app: upload listening audio,
transcribe it locally with word-level timestamps, generate cloze
(fill-in-the-blank) questions, and practise in the browser with synchronized
playback.

```
audio upload ──► local ASR (word timestamps) ──► hybrid question generation ──► browser practice
                                                  ├─ spaCy candidate pool
                                                  ├─ LLM picks word spans (optional)
                                                  └─ code validates verbatim anchors
```

The backend is FastAPI; the frontend is a Vue 3 SPA served by the backend
from `frontend/dist/`. That directory is not tracked by Git — prebuilt
bundles ship via GitHub Releases, and running from source requires one
`npm run build` (see [Manual setup](#manual-setup)).

## Features

- **Three local ASR engines, one interface**
  - `parakeet` — NVIDIA Parakeet TDT via `parakeet-mlx` (Apple Silicon)
  - `whisper` — Whisper large-v3-turbo via `mlx-whisper` (Apple Silicon)
  - `faster_whisper` — CTranslate2 (CUDA on Windows/Linux when available, CPU
    otherwise); the default outside Apple Silicon
  All engines produce word-level timestamps. The active model is loaded lazily on
  the first transcription and unloaded after an idle period (or manually), which
  frees roughly 1.2–2 GB of memory.
- **Hybrid question generation.** A spaCy candidate pool proposes nouns, numbers,
  names, etc.; the LLM selects word-index spans; code enforces the hard rules:
  answers must be verbatim contiguous transcript spans, at most 3 words, in
  transcript order, at least 5 words apart, not sentence-initial, and (when the
  engine reports probabilities) not low-confidence. The code fills any shortfall.
  Without an LLM key, the app falls back to the purely local `nouns` mode.
- **LLM context discipline.** One stateless `[system, user]` call per request,
  never any cross-material history. The total context is hard-capped at 256k
  tokens (262144); over-budget material is split at sentence boundaries into
  independent calls.
- **Batch import.** Select up to 50 audio files at once with per-file progress;
  failures do not affect the rest. Optionally generate question sets during
  import, or transcribe now and generate later.
- **Materials, timestamps, replay.** Materials store audio, transcript, and
  word-level timing. The transcript displays a timestamp at each sentence start
  (hideable); click a timestamp to play from that sentence (with A/B looping), or
  click any word to play from that word with live highlighting.
- **Transcript alignment.** Paste the official transcript together with audio and
  the app maps timestamps onto the official words (difflib word alignment,
  interpolating inserted words). Editing the transcript later re-anchors it and
  marks old question sets stale instead of deleting history.
- **Practice and review.** Question sets, per-attempt scoring, full-dictation
  attempts, a cross-material wrong-word book with timestamps, and overall stats
  are persisted in SQLite.
- **Sentence translation.** `POST /api/translate` provides cached English →
  Chinese sentence translation with gtx → MyMemory → LLM fallbacks.
- **Bilingual UI.** Chinese and English are built in, with a header language
  selector, browser-language detection, and per-request `Accept-Language` for
  backend messages. See [Adding a language](#adding-a-language).
- **Write-only API keys.** LLM keys are stored in the local SQLite database and
  never returned by the API (only a masked hint). They can optionally be seeded
  from `.env`.

## Platform support

Windows and macOS are both supported. Intel Macs and Linux can run the app and
use the `faster_whisper` CPU fallback for local recognition.

| Platform | Available ASR engines | Notes |
|---|---|---|
| macOS on Apple Silicon (M1/M2/M3/M4) | `parakeet` (default), `whisper`, `faster_whisper` | MLX/Metal for parakeet/whisper |
| Windows 10/11 | `faster_whisper` | CUDA when available, CPU otherwise |
| Linux | `faster_whisper` | CUDA when available, CPU otherwise |
| Intel Mac | `faster_whisper` | CPU fallback |

Common requirements:

- **Python 3.10+**
- **ffmpeg** on `PATH` (audio decoding for all ASR engines)
- **Node.js 20.19+ (or 22.12+)** when you build the frontend from source
  (Vite 7 requirement); a prebuilt bundle from the Releases page runs the
  app without Node.js.

## Quick start

### macOS

Double-click **`start-macos.command`**. On the first run it creates `.venv`,
installs dependencies (including `mlx-whisper` / `parakeet-mlx`), tries to
install the spaCy English model, writes a default `.env`, starts the server, and
opens <http://127.0.0.1:8300>. Double-click **`stop-macos.command`** to stop the
server; all model memory is released immediately.

If macOS blocks the script, right-click it and choose **Open**, or run
`chmod +x start-macos.command stop-macos.command` once in Terminal.

### Windows

Double-click **`start-windows.bat`**. The first run creates the virtual environment,
installs dependencies, sets up the spaCy model, writes a default `.env`, starts the
server, and opens <http://127.0.0.1:8300>. Double-click **`stop-windows.bat`** to
stop the server and release model memory.

Both launchers install from the Tsinghua PyPI mirror and use the
`HF_ENDPOINT=https://hf-mirror.com` mirror for model downloads by default. The
LLM is optional; the app is usable without any API key.

## Manual setup

From the repository root:

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows (cmd/PowerShell)
.venv\Scripts\activate

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Optional: better candidate selection; without it a heuristic word list is used
python -m spacy download en_core_web_sm
```

Start the backend:

```bash
cd backend
python -m app.main
# -> http://127.0.0.1:8300 (API docs at /docs)
```

The backend serves `frontend/dist` automatically when it exists. For frontend
development:

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173, /api proxied to :8300
npm run build      # vue-tsc --noEmit && vite build -> frontend/dist
```

Platform notes:

- `mlx-whisper` and `parakeet-mlx` are marked `sys_platform == "darwin"`, so they
  are skipped on Windows/Linux. Engine modules import their dependencies lazily,
  so tests and the API work on any platform.
- On an Intel Mac the MLX packages are unusable. If pip cannot resolve them,
  install the remaining runtime dependencies explicitly:
  `pip install fastapi uvicorn httpx python-multipart jsonschema spacy faster-whisper`,
  then run with the `faster_whisper` engine.
- Windows: install ffmpeg with `winget install Gyan.FFmpeg` (or from
  <https://www.gyan.dev/ffmpeg/builds/>) and make sure it is on `PATH`.
  macOS: `brew install ffmpeg`. Debian/Ubuntu: `sudo apt install ffmpeg`.

## Configuration

Copy `.env.example` to `.env` (the launchers create one on first run). Process
environment variables take precedence over `.env`. The Settings page persists
LLM/ASR/generation values in `data/app.db`, and those stored values override the
file defaults for those sections.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8300` | HTTP port (always bound to `127.0.0.1`) |
| `DATA_DIR` | `<repo>/data` | SQLite DB and audio storage |
| `HF_HOME` | `<repo>/.models` | Hugging Face model cache |
| `HF_ENDPOINT` | `https://hf-mirror.com` | Model download mirror |
| `PIP_INDEX_URL` | Tsinghua mirror | Injected for pip subprocesses |
| `ASR_ENGINE` | `parakeet` on Apple Silicon, `faster_whisper` elsewhere | Active engine |
| `ASR_PARAKEET_MODEL` | `mlx-community/parakeet-tdt-0.6b-v3` | Parakeet model |
| `ASR_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | MLX Whisper model |
| `ASR_FASTER_WHISPER_MODEL` | `large-v3-turbo` | CTranslate2 model (alias: `FASTER_WHISPER_MODEL`) |
| `ASR_IDLE_UNLOAD_MIN` | `10` | Idle minutes before unloading the model (`0` = keep loaded) |
| `LLM_PROVIDER` | `zhipu` | `zhipu`, `dashscope`, `deepseek`, or `custom` |
| `LLM_BASE_URL` | provider preset | OpenAI-compatible base URL |
| `LLM_MODEL` | provider preset | Model name |
| `LLM_API_KEY` | empty | Optional key seed; the Settings page is the normal path |
| `LLM_MAX_CONTEXT_TOKENS` | `262144` | May be lowered, never raised above 256k |
| `GEN_BLANK_COUNT` | `10` | Blank-count setting exposed in the Settings page (requests carry an explicit count) |

A `.env` naming an MLX engine on a non-Apple-Silicon machine is detected at
runtime and automatically falls back to `faster_whisper` instead of failing every
job.

### LLM providers

The Settings page offers presets for OpenAI-compatible providers:

| Provider | Base URL | Default model |
|---|---|---|
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.7-flash` |
| `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-flash` |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `custom` | your URL | your model |

Enter the key and click **Save & test**: the key is written first, then a real
request is sent with the form's current values. The key is write-only — the API
returns only `has_key` and a masked hint. Leaving the key field blank keeps the
stored key. Test failures show the provider's raw reason (HTTP 401, model not
found, etc.).

Common causes of a failed test: a nonexistent model name (for DeepSeek use
`deepseek-chat` or `deepseek-reasoner`), a base URL with a missing or extra
`/v1`, insufficient balance, or a proxy/network problem. A key typed but not
saved is not visible to the backend, so the panel tests the form's current values
instead of only the stored ones.

Without a key the app still works: question generation uses the local `nouns`
mode. With a key it uses `llm` mode, which is the higher-quality hybrid pipeline.

## Models and downloads

- Model weights are cached under `HF_HOME` (default `.models/`). Downloads go
  through `HF_ENDPOINT` (default `hf-mirror.com`); after the first download the
  app works offline.
- `parakeet` (`mlx-community/parakeet-tdt-0.6b-v3`) and `whisper`
  (`mlx-community/whisper-large-v3-turbo`) download roughly 1.2–1.6 GB on first
  transcription on Apple Silicon.
- `faster_whisper` uses the CTranslate2 `large-v3-turbo` model — the same Whisper
  weights as the MLX engine, converted for CTranslate2. It runs in `float16` on
  CUDA and `int8` on CPU; a missing CUDA runtime falls back to CPU automatically
  instead of failing the transcription.
- **Hugging Face unreachable?** `app/services/model_download.py` probes HF first
  and falls back to the ModelScope mirror of the same CTranslate2 files when
  `huggingface.co` / `hf-mirror.com` time out. You can also point the model
  setting at a local directory containing `config.json`, `model.bin`,
  `tokenizer.json`, and `vocabulary.json` for fully offline use.
- Switching engines in Settings unloads the current model immediately. Idle
  unload (`ASR_IDLE_UNLOAD_MIN`, default 10 minutes) frees memory automatically;
  `POST /api/asr/unload` unloads immediately.

## Adding a language

The frontend uses a small dependency-free i18n layer
(`frontend/src/i18n/index.ts`) with a reactive `locale` ref, `t()`,
`localStorage` persistence, and a language selector in the header. The backend
has its own catalogs in `backend/app/i18n.py` and localizes job/error messages
from the request's `Accept-Language` (the frontend sends the selected UI locale).

- Short guide: [`CONTRIBUTING.md`](CONTRIBUTING.md#adding-a-ui-language)
- Detailed step-by-step with code snippets:
  [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md)

Both test suites assert catalog key parity and non-empty values. LLM prompt
entries (`question_gen.*`, `translate.*`) are localizable in the backend catalog
as well.

## API overview

The complete contract lives in the design document (§8) and the interactive docs
at `/docs`.

```
GET  /api/health                      Health check
GET  /api/asr/status | POST /api/asr/load | POST /api/asr/unload
GET|PUT /api/settings                 LLM/ASR/generation settings (key write-only)
POST /api/settings/test-llm           Probe the LLM with the form's current values
POST /api/materials                   Create a material (multipart) -> {job_id}
POST /api/materials/batch             Batch import audio files -> {batch_id, jobs[]}
GET  /api/batches[/{id}]              Batch history / per-file progress
GET  /api/jobs/{id}                   Job progress (queued -> transcribing -> generating -> done|error)
GET  /api/materials[/{id}]            List / detail
DELETE /api/materials/{id}
GET  /api/materials/{id}/audio        Audio stream (HTTP Range supported)
PUT  /api/materials/{id}/transcript   Edit transcript and re-anchor timestamps
POST /api/materials/{id}/sets         Generate a set (llm | nouns | manual)
GET|DELETE /api/sets/{id}             Set detail (t_start/t_end/word_limit per blank)
POST /api/sets/{id}/attempts          Submit and score an attempt
POST /api/materials/{id}/attempts     Full-dictation attempt
GET  /api/materials/{id}/attempts     Attempt history for a material
GET  /api/review/wrong-words          Cross-material wrong-word book
GET  /api/stats                       Overview statistics
POST /api/translate                   Sentence EN -> ZH with cache and fallbacks
```

## Smoke test checklist

After installation, confirm:

1. The launcher starts the server and opens <http://127.0.0.1:8300>;
   `GET /api/health` returns `{"ok": true, ...}`.
2. `GET /api/asr/status` reports `unloaded`; idle memory stays low.
3. Import an audio file: the job moves through `transcribing` → `generating` →
   `done` (the first run downloads the model), and the material's `words` carry
   `s`/`e` timestamps.
4. Open the material: sentence-start timestamps are shown; clicking a word plays
   from that word and highlights it.
5. Batch-import 2–3 files: progress updates per file and one failure does not
   stop the others.
6. Save an LLM key and generate an `llm` set: every answer can be found verbatim
   in the transcript. Without a key, `nouns` mode still works.
7. Wait for the idle timeout (or use `POST /api/asr/unload`): status returns to
   `unloaded` and memory drops.
8. Switch engines in Settings: the current model unloads and the next job uses
   the new engine.
9. Restart the app: materials, sets, attempts, and wrong-word records persist in
   `data/`. Stop the app: the port-8300 process exits and memory is released.

## Testing

```bash
# Backend: all ASR engines, the LLM, and network access are mocked,
# so this runs on any OS without model downloads.
python -m pytest backend/tests -q

# Frontend: Vitest + jsdom
cd frontend
npm install
npm test

# Type-check and build the SPA served by the backend
npm run build
```

## Project layout

```
backend/app/            FastAPI app
  routers/              HTTP endpoints
  services/             Domain layer (no FastAPI imports; portable)
  i18n.py               Backend message + LLM prompt catalogs
  config.py             .env / environment settings
backend/tests/          pytest suite (engines/LLM/network mocked)
frontend/src/           Vue 3 SPA
  i18n/                 Dependency-free i18n layer and zh/en catalogs
  views/ components/    UI
  composables/ lib/     player, polling, helpers
frontend/dist/          Build output served by the backend (not tracked;
                        build with npm run build or unpack a Release bundle)
data/                   Runtime: app.db, audio/, incoming/ (ignored by Git)
.models/                Hugging Face model cache (ignored by Git)
docs/                   Design and implementation docs (mostly Chinese)
docs/ADDING_A_LANGUAGE.md  Step-by-step localization guide
start-macos.command / stop-macos.command         macOS launchers
start-windows.bat / stop-windows.bat             Windows launchers
LICENSE                 MIT
SECURITY.md             Vulnerability reporting and key handling
CONTRIBUTING.md         Setup, conventions, language guide
README.zh-CN.md         Chinese translation of this README
```

## License

[MIT](LICENSE) © 2026 EchoPaper contributors.

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Please do not
commit API keys, `data/`, or copyrighted audio (`test_sound/`); see
[SECURITY.md](SECURITY.md).
