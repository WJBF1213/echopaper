# Adding a UI Language

This project has two independent message catalogs:

- **Frontend UI** — `frontend/src/i18n/` (dependency-free layer).
- **Backend messages** — `backend/app/i18n.py` (job/error messages and LLM prompts).

A complete language addition usually touches both. The examples below add French
(`fr`); substitute your own ISO 639-1 code. Use a primary language code (`fr`,
`de`, `ja`) because browser detection matches the part before the hyphen.

---

## 1. Frontend catalog

### 1.1 Copy the English catalog

```bash
cp frontend/src/i18n/locales/en.ts frontend/src/i18n/locales/fr.ts
```

Edit the new file and translate **values only**:

```ts
// frontend/src/i18n/locales/fr.ts
const fr: Record<string, string> = {
  'app.brand': 'IELTS Listening Cloze',
  'common.cancel': 'Annuler',
  'common.words': '{n} mots',
  // ...every other key
}

export default fr
```

Rules:

- Keep every key exactly as in `en.ts` (same punctuation, same order is nice but
  not required).
- Keep interpolation placeholders (`{n}`, `{name}`, `{error}`, …) exactly as they
  are — same name, same braces.
- Do not leave empty or whitespace-only values.
- Do not translate the `app.brand` product name unless you intend to.

### 1.2 Register the catalog

Open `frontend/src/i18n/index.ts`. The current top of the file is:

```ts
import { computed, ref, watch } from 'vue'
import zh from './locales/zh'
import en from './locales/en'

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export type Messages = Record<string, string>
export type MessageParams = Record<string, string | number>

export const catalogs: Record<Locale, Messages> = { zh, en }

export const DEFAULT_LOCALE: Locale = 'zh'
```

Change it to add the import, the supported code, and the catalog:

```ts
import { computed, ref, watch } from 'vue'
import zh from './locales/zh'
import en from './locales/en'
import fr from './locales/fr'                       // 1) import

export const SUPPORTED_LOCALES = ['zh', 'en', 'fr'] as const  // 2) add code
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export type Messages = Record<string, string>
export type MessageParams = Record<string, string | number>

export const catalogs: Record<Locale, Messages> = { zh, en, fr }  // 3) catalog
```

Because `catalogs` is typed `Record<Locale, Messages>`, TypeScript fails if you
add a code without a catalog.

Then add the label shown in the header selector (a bit further down):

```ts
export const LOCALE_LABELS: Record<Locale, string> = {
  zh: '中文',
  en: 'English',
  fr: 'Français',                                   // 4) display label
}
```

That is all the wiring. `App.vue` already renders one `<option>` per entry in
`SUPPORTED_LOCALES` with `LOCALE_LABELS[code]`, so the new language appears in
the header automatically.

### 1.3 Behavior you get for free

- `detectLocale()` picks the first supported browser language (`fr-FR` → `fr`).
- The choice is persisted in `localStorage` under `ielts-cloze.locale`.
- `document.documentElement.lang` is updated (`zh` becomes `zh-CN`, other codes
  are used as-is).
- `frontend/src/api.ts` sends the selected locale as `Accept-Language`
  (`zh` → `zh-CN`), so backend messages follow the UI language.

If you need a special HTML `lang` value (for example `pt-BR`), extend the two
places in `index.ts` that set `document.documentElement.lang`; keep the catalog
code itself as the primary subtag.

### 1.4 Test the frontend

```bash
cd frontend
npm test
```

`src/i18n/i18n.test.ts` verifies, for every locale listed in
`SUPPORTED_LOCALES`:

- a catalog exists and has a label,
- the key set is identical to `DEFAULT_LOCALE` (`zh`),
- no value is empty.

Note: the placeholder-parity check in that file currently compares `zh` and
`en` only. For a newly added locale, keep placeholders identical manually (or
extend the test to loop over all locales).

You can also run `npm run build`; `vue-tsc --noEmit` catches missing catalog
entries and type errors.

---

## 2. Backend catalog

Backend messages (job progress, validation errors, engine/LLM failures) and the
LLM prompts live in `backend/app/i18n.py`.

### 2.1 Add the language code

Current declarations:

```python
DEFAULT_LOCALE = "zh"
SUPPORTED = ("zh", "en")
```

Change to:

```python
DEFAULT_LOCALE = "zh"
SUPPORTED = ("zh", "en", "fr")
```

`normalize_locale()` then accepts `fr`, `fr-FR`, `fr-CA`, etc. Unknown languages
still fall back to `DEFAULT_LOCALE`.

### 2.2 Add a catalog block

`MESSAGES` is a `dict[str, dict[str, str]]` with `"zh"` and `"en"` blocks. Copy
the **entire** `"en"` block, paste it after it, and translate every value while
keeping every key unchanged:

```python
MESSAGES: dict[str, dict[str, str]] = {
    "zh": { ... },
    "en": { ... },
    "fr": {                                      # new block
        "app.title": "IELTS Listening Cloze",
        "common.material_not_found": "Matériel introuvable",
        "job.transcribing": "Transcription locale en cours",
        "engine.unknown": "Moteur inconnu : {name}",
        # ...every remaining key from the "en" block, translated
    },
}
```

Rules:

- Same key set as the other catalogs — `backend/tests/test_i18n.py` asserts
  `set(MESSAGES) == set(SUPPORTED)` and that every catalog has exactly the same
  keys and no empty values.
- Keep placeholders (`{mode}`, `{limit}`, `{error}`, `{rate}`, …) and format
  specs (`{rate:.0%}`) identical.
- Python `.format()` is used, so literal braces in prompt templates are doubled
  (`{{` / `}}`). Preserve that escaping exactly when translating prompts.

### 2.3 LLM prompts are localizable too

These entries are not UI strings; they are the actual prompts sent to the LLM:

| Key | Purpose |
|---|---|
| `question_gen.system` | Item-writer rules for selecting blanks |
| `question_gen.user` | Per-chunk request with transcript indices and candidates |
| `question_gen.retry` | Retry request listing rejected candidates |
| `translate.system` | Translation system prompt |
| `translate.user` | Translation user prompt |

Translating them makes the model receive instructions in the new language, while
the transcript itself stays English. If you prefer to keep prompts in English,
simply copy the English values for these keys (they still must exist).

Be careful with `question_gen.user`: it contains placeholders (`{a}`, `{b}`,
`{lines}`, `{candidates}`, `{quota}`) and doubled braces for the JSON example.
Changing either breaks prompt formatting or the expected output shape.

### 2.4 Error and job messages

Entries such as `job.*`, `engine.*`, `llm.*`, `audio.*`, `manual.*`,
`translate.gtx_empty`, `translate.mymemory_empty`, and `common.*` surface
directly in the UI/API responses. Translate them normally.

### 2.5 Test the backend

```bash
cd backend
python -m pytest -q
```

The i18n test also checks the `Accept-Language` middleware and locale isolation
between requests. To verify manually, start the server and request a missing
material:

```bash
curl -H "Accept-Language: fr" http://127.0.0.1:8300/api/materials/missing
# -> {"detail": "<your French common.material_not_found value>"}
```

---

## 3. End-to-end check

1. Start the backend (`cd backend && python -m app.main`).
2. Start the frontend in dev mode (`cd frontend && npm run dev`) or rebuild
   `frontend/dist` (`npm run build`) and reload the backend page.
3. Pick the new language in the header. The UI should switch immediately.
4. Reload the page — the choice should persist.
5. Trigger a backend message (for example open a deleted material URL) and
   confirm it appears in the new language.
6. Run both test suites again.

## 4. Checklist

- [ ] `frontend/src/i18n/locales/<code>.ts` created, all values translated
- [ ] Import, `SUPPORTED_LOCALES`, `catalogs`, `LOCALE_LABELS` updated
- [ ] `backend/app/i18n.py`: `SUPPORTED` updated and full catalog block added
- [ ] Keys and placeholders identical across catalogs
- [ ] LLM prompt entries translated or intentionally copied from English
- [ ] `npm test` and `pytest` pass
- [ ] Manual UI + API check in the new language
