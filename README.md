# EchoPaper

English | [中文](README.zh-CN.md)

EchoPaper is a local-first IELTS-style listening practice app for Windows and
macOS: import listening audio, transcribe it with word-level timestamps
(locally by default, or through a cloud provider), optionally translate it
with an LLM, generate a full exam paper from the transcript (six question
types, including LLM-reconstructed map scenes rendered as SVG), grade it on
the server, review per-item accuracy and a wrong-word book, and drill
sentences in a bilingual intensive-listening view. Everything runs on your
machine; API keys are only needed for paper generation, LLM translation,
and (optional) cloud transcription.

```
audio upload ──► ASR: local or cloud (word timestamps) ──► optional LLM translation
                                                        │
              intensive listening ◄── review ◄── grading ◄── full-paper generation (six types)
```

The backend is FastAPI; the frontend is a Vue 3 SPA that the backend serves
from `frontend/dist/` when that directory exists. `dist` is not tracked by
Git — running from source requires one `npm run build`
(see [Manual setup](#manual-setup)).

## Features

- **Local and cloud transcription, word-level timestamps either way**
  - Local mode (default): one fixed engine per platform — `parakeet`
    (MLX/Metal, Apple Silicon) or `faster_whisper` with `large-v3-turbo`
    (CTranslate2; CUDA when available, CPU otherwise). The first
    transcription downloads roughly 1.5 GB of model weights; the model loads
    lazily and is unloaded after an idle period (or manually), freeing
    memory.
  - Cloud mode: any OpenAI-compatible transcription endpoint — Groq preset
    (default), OpenAI preset, or a custom base URL + model — with word-level
    timestamps and no local model download. Audio is uploaded to the
    provider; see [Transcription](#transcription) for the privacy note and
    rough costs.
- **Full-paper generation.** Pick question types and counts on the material
  page — multiple choice (single / two answers), matching, completion (with
  form/table/notes/sentence/summary/flow-chart layouts), short answer, and map
  labelling — and the LLM writes a complete paper. Code, not the model, is the
  authority: answers and evidence must be verbatim transcript spans, and
  anything the transcript cannot support comes back as a refused block with a
  one-line reason instead of a forced question.
- **Map scenes.** For map labelling the LLM reconstructs the scene (nodes,
  paths, numbered blanks) from the spatial language; the backend hard-validates
  it (canvas bounds, unique ids, continuous blank numbering, node spacing) and
  the paper renders it as an interactive SVG.
- **Server-side grading.** Submitting a paper grades every item on the server,
  accepting reasonable answer variants (case, spacing, number forms, curated
  alternatives). Attempts and per-item results persist in SQLite — no score is
  kept, only per-item correctness.
- **Review.** Per-item accuracy grouped by paper, by-type accuracy across all
  papers, and a wrong-word book aggregated by answer text with a jump back to
  the paper containing the item.
- **Bilingual intensive listening.** A dedicated view lists every sentence
  with its Chinese translation (produced during import, with gtx → MyMemory
  fallbacks when no LLM is configured): click a sentence to play it, loop it
  with A/B (shortcut `L`), and scrub word by word.
- **Editable prompts.** Every LLM prompt lives in a registry and can be edited
  in Settings (设置 → 提示词) — global system prompt, task frames, per-type
  rules, map-scene reconstruction, batch translation. Saving empty text
  restores the built-in default. Editing a prompt invalidates related LLM
  cache entries.
- **LLM cache and prefix discipline.** Requests are assembled with a stable
  message prefix and temperature 0, so provider-side prefix caching works and
  responses are additionally served from the persistent local `llm_cache`
  table. Settings has a "Clear LLM cache" button. The context is hard-capped
  at 256k tokens (262144).
- **Batch import.** Select up to 50 audio files at once with per-file progress;
  failures do not affect the rest. Papers are generated later from the
  material page.
- **Materials, timestamps, replay.** Materials store audio, transcript, and
  word-level timing. The transcript displays a timestamp at each sentence start
  (hideable); click a timestamp to play from that sentence (with A/B looping), or
  click any word to play from that word with live highlighting.
- **Transcript alignment.** Paste the official transcript together with audio and
  the app maps timestamps onto the official words (difflib word alignment,
  interpolating inserted words). Editing the transcript later re-anchors it and
  marks old papers stale instead of deleting history.
- **Bilingual UI.** Chinese and English are built in, with a header language
  selector, browser-language detection, and per-request `Accept-Language` for
  backend messages. The visible audio-pick buttons are the app's own
  translated controls; the native file-open dialog itself follows your
  OS/browser language. See [Adding a language](#adding-a-language).
- **Write-only API keys.** LLM and cloud-transcription keys are stored in the
  local SQLite database and never returned by the API (only a masked hint).
  They can optionally be seeded from `.env`.

Without an LLM key the app still imports, transcribes, aligns, and replays
material; paper generation needs a key (the exam endpoint answers `400` with a
hint).

## Platform support

Windows and macOS are the supported platforms. Intel Macs and Linux can run
the app and use the `faster_whisper` CPU path for local recognition
(a Linux launcher is on the [roadmap](#roadmap)).

| Platform | Local engine (fixed per platform) | Notes |
|---|---|---|
| macOS on Apple Silicon (M1/M2/M3/M4) | `parakeet` (MLX/Metal) | |
| Windows 10/11 | `faster_whisper` | CUDA when available, CPU otherwise |
| Linux | `faster_whisper` | CUDA when available, CPU otherwise |
| Intel Mac | `faster_whisper` | CPU fallback |

The local engine is derived from the platform — there is nothing to choose.
Cloud transcription (an HTTP client) is available on every platform; see
[Transcription](#transcription).

Common requirements:

- **Python 3.10+**
- **ffmpeg** on `PATH` (audio decoding for all ASR engines)
- **Node.js 24+ (required by jsdom 30 / undici 8 zstd support)** when you build the frontend from source
  (Vite 7 requirement)

## Quick start

### Windows

Double-click **`start-windows.bat`**. The first run creates the virtual
environment, installs dependencies, sets up the spaCy model, writes a default
`.env`, starts the server, and opens <http://127.0.0.1:8300>. Double-click
**`stop-windows.bat`** to stop the server and release model memory.

### macOS

Double-click **`start-macos.command`**. On the first run it creates `.venv`,
installs dependencies (including `parakeet-mlx`), tries to
install the spaCy English model, writes a default `.env`, starts the server, and
opens <http://127.0.0.1:8300>. Double-click **`stop-macos.command`** to stop
the server; all model memory is released immediately.

If macOS blocks the script, right-click it and choose **Open**, or run
`chmod +x start-macos.command stop-macos.command` once in Terminal.

### First run notes

- The **first local transcription downloads the ASR model** (roughly 1.5 GB;
  see [Transcription](#transcription)). Progress shows in the
  task bar; keep the launcher window open.
- Both launchers install from the Tsinghua PyPI mirror and use
  `HF_ENDPOINT=https://hf-mirror.com` for model downloads by default.
- **Keys are optional at start**: configure the LLM key later in Settings
  (needed for paper generation and LLM translation); local transcription
  works without any key, and cloud transcription needs its own key only if
  you switch to that mode.

## Manual setup

From the repository root:

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows (cmd/PowerShell)
.venv\Scripts\activate

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Optional: better lemma/POS support for grading; without it a heuristic is used
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

- `parakeet-mlx` is marked `sys_platform == "darwin"`, so it is skipped on
  Windows/Linux. Engine modules import their dependencies lazily, so tests
  and the API work on any platform.
- On an Intel Mac the MLX package is unusable. If pip cannot resolve it,
  install the remaining runtime dependencies explicitly:
  `pip install fastapi uvicorn httpx python-multipart spacy faster-whisper`,
  then run with the `faster_whisper` engine.
- Windows: install ffmpeg with `winget install Gyan.FFmpeg` (or from
  <https://www.gyan.dev/ffmpeg/builds/>) and make sure it is on `PATH`.
  macOS: `brew install ffmpeg`. Debian/Ubuntu: `sudo apt install ffmpeg`.

## Configuration

Copy `.env.example` to `.env` (the launchers create one on first run). Process
environment variables take precedence over `.env`. The Settings page persists
LLM/ASR values in `data/app.db`, and those stored values override the
file defaults for those sections.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8300` | HTTP port (always bound to `127.0.0.1`) |
| `DATA_DIR` | `<repo>/data` | SQLite DB and audio storage |
| `HF_HOME` | `<repo>/.models` | Hugging Face model cache |
| `HF_ENDPOINT` | `https://hf-mirror.com` | Model download mirror |
| `PIP_INDEX_URL` | Tsinghua mirror | Injected for pip subprocesses |
| `ASR_MODE` | `local` | Transcription mode: `local` (default) or `cloud` |
| `ASR_CLOUD_BASE_URL` | `https://api.groq.com/openai/v1` | Cloud endpoint (OpenAI-compatible) |
| `ASR_CLOUD_MODEL` | `whisper-large-v3-turbo` | Cloud model name |
| `ASR_CLOUD_API_KEY` | empty | Optional cloud key seed; the Settings page is the normal path |
| `ASR_IDLE_UNLOAD_MIN` | `10` | Idle minutes before unloading the local model (`0` = keep loaded) |
| `LLM_PROVIDER` | `zhipu` | `zhipu`, `dashscope`, `deepseek`, or `custom` |
| `LLM_BASE_URL` | provider preset | OpenAI-compatible base URL |
| `LLM_MODEL` | provider preset | Model name |
| `LLM_API_KEY` | empty | Optional key seed; the Settings page is the normal path |
| `LLM_MAX_CONTEXT_TOKENS` | `262144` | May be lowered, never raised above 256k |

The local engine and model are fixed per platform — there is no env key for
them. The cloud values are normally configured in Settings; see
[Transcription](#transcription).

### LLM providers and caching

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
`/v1`, insufficient balance, or a proxy/network problem.

**Cache behavior.** LLM requests are assembled with a stable message prefix
(system → stable frame → task frame) and temperature 0, so providers can reuse
prefix caches, and every JSON response is additionally cached in the local
`llm_cache` table — regenerating the same paper, or reopening it on another
day, costs nothing. Editing a prompt in Settings invalidates the related
entries, and **Clear LLM cache** wipes the table on demand.

### Editing prompts

Settings → **Prompts** lists every LLM prompt (global system, task frames,
per-type rules, map-scene reconstruction, batch translation) with its
variables. Edit the text and save, or press **Reset to default** (which sends
empty text). Keep every listed `{{variable}}` — the backend rejects a prompt
that drops a required one.

> Upgrading from a pre-0.1.0 experiment build where you had customized the
> **map labelling rules** prompt? Reset that override once in Settings →
> Prompts — v0.1.0 added a required blank-slot numbering rule that old
> overrides do not contain.

## Transcription

Transcription runs in one of two modes, chosen in Settings
(设置 → 语音识别) or via `ASR_MODE`. Both produce **word-level
timestamps** — the basis for clickable transcripts, per-word replay, and
evidence-anchored questions.

### Local (default, offline)

One engine + model is fixed per platform — there is nothing to choose:

| Platform | Engine | Model |
|---|---|---|
| macOS on Apple Silicon | `parakeet` (MLX/Metal) | `mlx-community/parakeet-tdt-0.6b-v3` |
| Windows / Linux / Intel Mac | `faster_whisper` (CTranslate2) | `large-v3-turbo` |

- The **first transcription downloads the model (roughly 1.5 GB)**; after
  that the app works offline. Weights are cached under `HF_HOME` (default
  `.models/`) and fetched through `HF_ENDPOINT` (default `hf-mirror.com`).
- `faster_whisper` runs `float16` on CUDA and `int8` on CPU; a missing CUDA
  runtime falls back to CPU automatically instead of failing the
  transcription.
- **Hugging Face unreachable?** `app/services/model_download.py` probes HF
  first and falls back to the ModelScope mirror of the same CTranslate2
  files when `huggingface.co` / `hf-mirror.com` time out. For fully offline
  use, place `config.json`, `model.bin`, `tokenizer.json`, and
  `vocabulary.json` in `.models/faster-whisper/large-v3-turbo/`.
- The local model loads lazily on first use and unloads after
  `ASR_IDLE_UNLOAD_MIN` idle minutes (default 10, `0` = keep loaded);
  `POST /api/asr/unload` unloads immediately, and switching modes unloads
  the local model right away.

### Cloud (audio leaves your machine)

Cloud mode sends your audio to any **OpenAI-compatible**
`/audio/transcriptions` endpoint and needs no local model or download.
Configure base URL, model, and API key in Settings — presets included:

| Provider | Base URL | Default model | Rough cost |
|---|---|---|---|
| Groq (default) | `https://api.groq.com/openai/v1` | `whisper-large-v3-turbo` | ≈ $0.04/h — a 30-min IELTS tape ≈ $0.02 |
| OpenAI | `https://api.openai.com/v1` | `whisper-1` | ≈ $0.36/h — a 30-min tape ≈ $0.18 |
| Custom | any OpenAI-compatible URL | your model | provider-dependent |

- **Privacy:** in cloud mode **the audio file is uploaded to the provider
  you configure** (along with your API key). Nothing else leaves the
  machine, and local mode uploads nothing.
- Word timestamps come from the provider's `verbose_json` response; when a
  provider omits per-word timing, segment times are spread evenly so the
  word-anchored features keep working.
- Providers cap uploads (~24 MB): larger files are automatically
  recompressed to 16 kHz mono MP3 and split into ~10-minute chunks, and
  chunk timestamps are stitched back with the correct offsets.
- The cloud key is write-only like the LLM key (Settings shows only a
  masked hint), and **Test connection** checks the endpoint before you
  rely on it.

## Adding a language

The frontend uses a small dependency-free i18n layer
(`frontend/src/i18n/index.ts`) with a reactive `locale` ref, `t()`,
`localStorage` persistence, and a language selector in the header. The backend
has its own catalogs in `backend/app/i18n.py` and localizes job/error messages
from the request's `Accept-Language` (the frontend sends the selected UI locale).

- Short guide: [`CONTRIBUTING.md`](CONTRIBUTING.md#adding-a-ui-language)
- Detailed step-by-step with code snippets:
  [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md)

Both test suites assert catalog key parity and non-empty values. The
`translate.*` fallback prompts are localizable in the backend catalog; the
exam-generation prompts live in the prompt registry
(`backend/app/services/prompts.py`) and are edited in Settings, not via the
catalogs.

## API overview

The interactive docs at `/docs` are authoritative. The v0.2.0 surface:

```
GET  /api/health                      Health check + app version
GET  /api/asr/status | POST /api/asr/load | POST /api/asr/unload
POST /api/asr/test-cloud              Probe the cloud ASR endpoint
GET|PUT /api/settings                 LLM/ASR settings (key write-only)
POST /api/settings/test-llm           Probe the LLM with the form's values
GET|PUT /api/prompts                  List prompt registry / save or reset one
DELETE /api/llm-cache                 Clear the local LLM cache

POST /api/materials                   Create a material (multipart) -> {job_id}
POST /api/materials/batch             Batch import audio -> {batch_id, jobs[]}
GET  /api/batches | /api/batches/{id} Batch history / per-file progress
GET  /api/jobs/{id}                   Job progress (queued -> downloading ->
                                      transcribing -> translating -> done|error)
GET  /api/materials[/{id}]            List / detail (words + sentence spans)
DELETE /api/materials/{id}
GET  /api/materials/{id}/audio        Audio stream (HTTP Range supported)
PUT  /api/materials/{id}/transcript   Edit transcript and re-align timestamps
GET  /api/materials/{id}/translations Sentence translation snapshot (listen view)

GET  /api/exam/types                  The six registered question types
POST /api/materials/{id}/exam         Generate + persist a full paper
                                      -> {paper_id, skipped[]}
GET  /api/materials/{id}/papers       The material's papers
GET|DELETE /api/papers/{id}           Paper detail (spec + paper JSON) / delete
POST /api/papers/{id}/attempts        Submit answers -> server-side per-item
                                      grading -> {attempt_id, items[]}
GET  /api/papers/{id}/attempts        Attempt history (newest first)
GET  /api/attempts/{id}               One attempt's per-item detail
GET  /api/papers/{id}/stats           Per-item accuracy for one paper
GET  /api/stats                       By-type accuracy across all papers

GET  /api/review/wrong-words          Wrong-word book (aggregated by answer)
POST /api/translate                   Sentence EN -> ZH (cache + fallbacks)
```

## Smoke test checklist

After installation, confirm:

1. The launcher starts the server and opens <http://127.0.0.1:8300>;
   `GET /api/health` returns `{"ok": true, "version": "0.2.0"}`.
2. `GET /api/asr/status` reports `unloaded`; idle memory stays low.
3. Import an audio file: the job moves through `transcribing` →
   (`translating`) → `done` (the first run downloads the model), and the
   material's `words` carry `s`/`e` timestamps.
4. Open the material: sentence-start timestamps are shown; clicking a word plays
   from that word and highlights it.
5. Batch-import 2–3 files: progress updates per file and one failure does not
   stop the others.
6. Save an LLM key, pick question types, and generate a paper: every answer can
   be found verbatim in the transcript; a map block renders as an SVG scene or
   is skipped with a reason.
7. Submit answers: grading is immediate and per-item; the review page shows
   per-item accuracy and the wrong-word book.
8. Wait for the idle timeout (or use `POST /api/asr/unload`): status returns to
   `unloaded` and memory drops.
9. Restart the app: materials, papers, attempts, and wrong-word records persist
   in `data/`. Stop the app: the port-8300 process exits and memory is released.

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
    exam_gen.py         Full-paper generation (six types, refusal handling)
    exam_scene.py       LLM map-scene reconstruction + hard validation
    exam_grade.py       Server-side grading with answer equivalence
    prompts.py          Prompt registry + per-key overrides (Settings)
    llm.py              OpenAI-compatible client + persistent llm_cache
    translate_svc.py    LLM-first batch translation with gtx/MyMemory fallback
  i18n.py               Backend message catalogs (zh/en)
  config.py             .env / environment settings
backend/tests/          pytest suite (engines/LLM/network mocked)
frontend/src/           Vue 3 SPA
  i18n/                 Dependency-free i18n layer and zh/en catalogs
  views/                Library, Material, Paper, Review, Listen, Settings
  components/           MapScene (SVG), TranscriptView, PlayerBar, ...
  composables/ lib/     player, polling, helpers
frontend/dist/          Build output served by the backend when present
                        (not tracked; build with npm run build)
data/                   Runtime: app.db (schema v3), audio/ (ignored by Git)
.models/                Hugging Face model cache (ignored by Git)
docs/                   Design and reference docs (mostly Chinese)
start-windows.bat / stop-windows.bat             Windows launchers
start-macos.command / stop-macos.command         macOS launchers
LICENSE                 GPL-3.0
```

## Documentation

- [`README.zh-CN.md`](README.zh-CN.md) — Chinese version of this README
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, conventions, PR checklist
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting and key handling
- [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md) — step-by-step
  localization guide
- [`docs/reference/ielts-listening-rules.md`](docs/reference/ielts-listening-rules.md) —
  official IELTS part/type reference (backup reference; not yet wired into the
  LLM prompts)

## Roadmap

- **Linux deployment** — a first-class launcher and packaged build for Linux.
- **Multi-user server edition** — deployment mode with authentication and
  per-user data instead of the single-user local app.
- **Batch API pre-generation** — offline paper generation via batch (async)
  LLM endpoints for lower cost.
- **Anthropic explicit cache params** — pass explicit prompt-caching parameters
  on top of the current stable-prefix strategy.
- **Official Part combination quick-picks** — one-click paper presets matching
  real IELTS part shapes (e.g. Part 1 form + Part 2 map + Part 3 matching).

## License

[GPL-3.0](LICENSE) © 2026 EchoPaper contributors.

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Please do not
commit API keys, `data/`, or copyrighted audio (`test_sound/`); see
[SECURITY.md](SECURITY.md).
