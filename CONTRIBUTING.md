# Contributing

Thanks for helping improve EchoPaper. This guide covers local setup,
tests, conventions, and adding a UI language. For a step-by-step language guide
with full snippets, see [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md).

## Development setup

Requirements: Python 3.10+, Node.js 18+ (only for frontend development/building),
and ffmpeg for audio decoding.

```bash
# from the repository root
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (cmd/PowerShell)
.venv\Scripts\activate

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Optional but recommended: improve the rule-based candidate pool
python -m spacy download en_core_web_sm
```

Run the backend:

```bash
cd backend
python -m app.main          # http://127.0.0.1:8300
```

Run the frontend in dev mode (Vite proxies `/api` to port 8300):

```bash
cd frontend
npm install
npm run dev                 # http://127.0.0.1:5173
```

`frontend/dist/` is not tracked by Git. The backend serves it when it exists;
after changing frontend code, build it locally so the bundled app appears:

```bash
cd frontend
npm run build               # runs vue-tsc --noEmit && vite build
```

## Tests

The backend suite mocks ASR engines, the LLM, and network access, so it runs on
any OS (no model download, no Apple Silicon required).

```bash
# from the repository root, with the venv active
python -m pytest backend/tests -q

# or from backend/ (pytest.ini sets testpaths=tests)
cd backend && python -m pytest -q
```

Frontend tests use Vitest + jsdom:

```bash
cd frontend
npm test                    # vitest run
npm run test:watch          # watch mode
```

Please run both suites (and `npm run build`) before opening a pull request.

## Code conventions

### Backend layering

- `backend/app/routers/` owns HTTP concerns (FastAPI, request/response models).
- `backend/app/services/` is the portable domain layer and **must not import
  FastAPI** (or other web frameworks). Keep it usable from scripts and tests.
- User-facing backend text goes through `app.i18n.t(...)`, not hardcoded
  strings, so it follows `Accept-Language`.

### LLM calls

- Every LLM call is a **stateless single request** with a stable message
  prefix (exam generation sends `system -> stable frame -> task frame`).
  Never accumulate cross-call or cross-material history.
- Message order is deliberate: the stable parts come first so provider
  prefix caching works, and responses are additionally served from the
  local `llm_cache` table (stable prefix + temperature 0 makes hits
  likely). Editing a prompt in Settings invalidates related cache entries.
- The 256k-token (262144) context cap is a hard limit; configuration may lower
  it but never raise it.
- A retry embeds the previous failure reason in the **last** message, keeping
  the prefix (and therefore the cache key) stable.
- LLM output is JSON-schema validated; a response that fails validation is
  retried once with the reason appended, then rejected.

### Question correctness

- **Answers and evidence must be verbatim spans of the transcript.** Code,
  not the model, is the authority: item evidence word indices, answers,
  order, and option/blank consistency are all validated; invalid output is
  rejected (or the block refused), never "fixed up".
- When the transcript cannot support a question type, the generator returns
  a refusal with a one-line reason instead of forcing items (shown in the
  UI as a skipped block).
- Map scenes are hard-validated too (canvas bounds, unique node ids,
  continuous blank-slot numbering, node spacing) before rendering.

### Frontend / i18n

- The i18n layer is dependency-free (`frontend/src/i18n/`). Use `t('key')` for
  all user-visible strings; add keys to both `locales/zh.ts` and
  `locales/en.ts`.
- The key sets must stay identical and no value may be empty; `npm test`
  enforces this. Keep `{placeholders}` identical across locales.
- The backend catalog lives in `backend/app/i18n.py`; `backend/tests/test_i18n.py`
  enforces catalog/key parity and non-empty values.
- When adding user-facing backend messages, add them to every catalog.

### Repository hygiene

- Never commit `data/`, `.env`, `.models/`, virtual environments, or audio from
  `test_sound/` (copyrighted IELTS material).
- Do not weaken the launchers' defaults (loopback-only binding, local key
  storage) or commit secrets.

## Adding a UI language

Short version:

1. **Frontend catalog** — copy `frontend/src/i18n/locales/en.ts` to
   `frontend/src/i18n/locales/<code>.ts` and translate the values. Keep every
   key and every `{placeholder}` unchanged.
2. **Register it** in `frontend/src/i18n/index.ts`:
   - add the import,
   - add the code to `SUPPORTED_LOCALES`,
   - add the catalog to `catalogs`,
   - add a label to `LOCALE_LABELS`.
3. **Backend catalog** — in `backend/app/i18n.py`, copy the `"en"` block in
   `MESSAGES` to `"<code>"`, translate the values, and add the code to
   `SUPPORTED`. Keys must match exactly.
4. **LLM prompts (optional)** — the `translate.*` entries in the backend
   catalog are prompts themselves; translating them localizes the fallback
   translation requests. The exam-generation prompts live in the prompt
   registry (`backend/app/services/prompts.py`) and are edited per key in
   Settings, not via the catalogs.
5. **Test**:
   ```bash
   cd frontend && npm test
   cd backend && python -m pytest -q
   ```
   The frontend test asserts key parity and non-empty values for every declared
   locale; the backend test asserts the same for its catalogs.

Full snippets and manual verification steps: [`docs/ADDING_A_LANGUAGE.md`](docs/ADDING_A_LANGUAGE.md).

## Pull request checklist

- [ ] Backend tests pass: `python -m pytest backend/tests -q`
- [ ] Frontend tests pass: `cd frontend && npm test`
- [ ] Frontend builds: `cd frontend && npm run build` (dist is not
      committed; build locally to see the bundled UI)
- [ ] New user-visible strings added to all locale catalogs, keys/placeholders identical
- [ ] Backend services layer still has no FastAPI imports
- [ ] Answers/evidence are still verbatim transcript spans; validation intact
- [ ] No secrets, `.env`, `data/`, model caches, or `test_sound/` audio committed
- [ ] Docs updated when behavior, configuration, or setup changes
- [ ] Launchers still work on their platform (or the change is documented)
