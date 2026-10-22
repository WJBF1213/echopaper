# Security Policy

## Reporting a vulnerability

Please report security issues **privately**. Do not open a public issue, and do
not include exploit details, API keys, or personal data in a public discussion.

Use GitHub's private vulnerability reporting for this repository when it is
hosted there (**Security** tab → **Report a vulnerability**). Otherwise, contact
the maintainers through the repository's private contact channel and include:

- a short description of the issue and its impact,
- steps to reproduce (proof of concept if possible),
- affected version/commit and platform.

You can expect an acknowledgement as soon as maintainers are available. Please
allow time for a fix before any public disclosure.

## Scope and design notes

This is a single-user, local-first application:

- The backend binds to `127.0.0.1` only and has no authentication by design.
  Do not expose the port to untrusted networks or reverse-proxy it publicly.
- Uploaded audio, transcripts, attempts, and settings are stored locally under
  `data/` (`data/app.db` plus `data/audio/`).
- LLM API keys are stored write-only in the local SQLite database
  (`data/app.db`) or supplied through `.env` / environment variables. Both the
  database directory and `.env` files are ignored by Git.
- The LLM provider is user-configured; transcripts and prompts are sent to that
  provider only when LLM-backed generation or translation is used.

## Never commit secrets

- Do not commit `.env`, `data/`, `test_sound/`, model caches, or virtual
  environments.
- If a key is committed by mistake, revoke/rotate it immediately at the
  provider, then remove it from the repository and its history.
- Test fixtures may use obvious dummy values (for example `sk-test-...`); never
  replace them with real credentials.
