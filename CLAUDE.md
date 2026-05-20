# CLAUDE.md — Inavoice

> Voice-to-invoice automation. Dictate an invoice via Telegram, get a PDF, optionally email it.

## Project Context

- **Type:** Personal tool + learning project. Not SaaS (yet).
- **Owner:** Vincent Besuyen, Zaraffa (Hong Kong)
- **Status:** MVP planning complete, pre-build

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python |
| Telegram bot | python-telegram-bot v20+ (async) |
| Command parsing | Claude API (Anthropic) |
| PDF generation | WeasyPrint (HTML/CSS → PDF) + Jinja2 (templating) |
| Database | Supabase (free tier PostgreSQL) |
| File storage | Supabase Storage |
| Email | Resend (from invoice@zaraffa.online) |
| Hosting | Railway (hobby tier, ~$5-7/month) |
| Containerization | Docker + Docker Compose |
| Version control | Git + GitHub |

## Project Structure

```
src/
  __main__.py           # entry point
  bot/
    handlers.py         # telegram command/message handlers
    keyboards.py        # inline keyboard builders
    formatting.py       # confirmation message formatting
  services/
    llm_parser.py       # claude API calls + prompt management
    pdf_generator.py    # weasyprint + jinja2
    email_sender.py     # resend
    invoice_service.py  # number generation, storage, orchestration
  models/
    session.py          # session dataclass
    schemas.py          # pydantic models for LLM output validation
  db/
    client.py           # supabase client wrapper
    contacts.py         # contacts CRUD
    invoices.py         # invoices CRUD
  config.py             # env var loading, constants
  templates/
    invoice.html        # jinja2 template
  assets/
    logo.png
```

## Key Decisions (override brainstorm.md)

- LLM parsing from day one (not structured commands)
- WeasyPrint for PDFs (not Google Docs API)
- Voice support in MVP (not deferred to V1)
- Telegram only (WhatsApp/Signal deferred)
- No FastAPI — bot runs directly, add framework in V1 if needed
- Line items stored as array (MVP uses one, schema supports many)

## MVP Flow (summary)

Text → Claude parses → Confirm/Edit/Cancel → PDF → Email or Telegram

## Spec Documents

| Document | Contents |
|----------|----------|
| [Spec](docs/spec.md) | Full system spec |
| [LLM Parsing Spec](docs/llm-parsing-spec.md) | JSON schema, prompts, edge cases |
| [Template Spec](docs/template-spec.md) | Invoice layout, fields, styling |
| [Email Spec](docs/email-spec.md) | Email body, Resend config |
| [Deployment Guide](docs/deployment.md) | Docker, Railway, pause/resume, env vars |
| [Testing](docs/testing.md) | Test cases, pytest strategy |
| [Changelog](docs/CHANGELOG.md) | Deviations from spec and significant decisions |
| [Status](docs/STATUS.md) | Build progress — what is done vs. pending |

## Development Rules


- At the start of every session, read `docs/STATUS.md` to understand what has been built and what is still pending.
- Before implementing any feature, read the relevant spec document first. Spec documents are listed in the Spec Documents table in this file.
- **Adding a Telegram command:** every new `CommandHandler` must also be registered in the `BOT_COMMANDS` list in `src/bot/handlers.py` (and a one-line entry added to the `_HELP_TEXT` block) so it appears in the Telegram client's `/` autocomplete menu. Sub-commands (e.g. `/contacts add`) are dispatched from the parent command's handler — list the sub-command in `_HELP_TEXT` and reflect it in the parent's `BotCommand` description.
- Push to main triggers Railway auto-deploy; rollback via dashboard if needed
- Two Telegram bots: `@inavoice_dev_bot` for local dev (token in `.env`), production bot on Railway (token in Railway env vars). The `DEPLOY_ENV` env var labels which is which in the `/start` and `/help` banner — set to `local` in `.env` and `prod` on Railway. Never run two pollers against the same token.
- All secrets in `.env` (never in code, always in .gitignore)
- No PII or bank details in any tracked file — use `{{VARIABLE}}` references
- Log to stdout with structlog (JSON format, session IDs)
- A pre-push hook at `hooks/pre-push` enforces the checklist below — do not skip it. After cloning, activate it once with `git config core.hooksPath hooks`
- **Changelog:** When implementing a feature that deviates from a spec document, or when a significant architectural decision is made, append an entry to `docs/CHANGELOG.md` in the same response. Skip entries for normal spec-compliant implementation, refactors, test additions, and bug fixes.

**Branching workflow:**
- ALWAYS create a feature branch before starting any major changes — never commit directly to `main`
- Branch naming: `feature/description` or `fix/description`
- Workflow: branch → develop → test locally (`pytest tests/`, `docker compose up`) → push → open PR → merge to `main`
- PRs must include a description of what changed and why
- NEVER force push to `main`

## Dependency Management

- **Always use the project virtual environment (`.venv`) — never install packages to the global or user Python.** Run all Python commands via `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/pip`, etc.
- Direct deps declared in `requirements.in` (prod) and `requirements-dev.in` (dev, starts with `-r requirements.in`)
- Generate lockfiles with `pip-compile --generate-hashes --allow-unsafe`; commit both `.in` and `.txt` files
- Never hand-edit lockfiles — always regenerate
- Upgrade via `pip-compile --upgrade`, review the diff, rerun tests
- Dockerfile installs with `pip install --require-hashes -r requirements.txt`

## Security Constraints

These are hard rules. Never violate them regardless of context.

- **No PII/secrets in logs** — never log or echo bank details, API keys, addresses, or any secret value. Log only `client_id`, `invoice_number`, `session_id`, and error messages.
- **Auth gate first** — the first line of every Telegram handler must check `ALLOWED_CHAT_IDS`. No work happens before this check passes.
- **Validate every external input with Pydantic, not dicts** — treat all Claude API responses, user input, and external data as untrusted. Always validate with Pydantic models before the data touches the DB or file system.
- **Secrets via config.py only** — env vars are loaded once in `config.py`. No other module may call `os.environ` or `os.getenv` directly.
- **Supabase least privilege** — Use SUPABASE_SERVICE_KEY for all database and storage operations. The anon key is not used in this project — do not introduce it.
- **Dependency audit before push** — run `pip-audit -r requirements.txt` and `pip-audit -r requirements-dev.txt`; no push if known vulnerabilities are found.

## Commands

| Task | Command |
|------|---------|
| Run locally (prod-shaped, no test fixtures mounted) | `docker compose up` |
| Run locally for MOCK_MODE smoke testing | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` |
| Recompile prod lockfile | `docker run --rm -v "$(pwd):/app" -w /app python:3.13-slim sh -c "pip install pip-tools && pip-compile --generate-hashes --allow-unsafe --output-file=requirements.txt requirements.in"` |
| Recompile dev lockfile | `docker run --rm -v "$(pwd):/app" -w /app python:3.13-slim sh -c "pip install pip-tools && pip-compile --generate-hashes --allow-unsafe --output-file=requirements-dev.txt requirements-dev.in"` |
| Security audit (required before push) | `pip-audit -r requirements.txt && pip-audit -r requirements-dev.txt` |
| Run tests | `pytest tests/` |
| Build + smoke test | `docker build -t inavoice-test . && docker run --rm inavoice-test python -c "import anthropic, telegram, weasyprint, supabase; print('ok')"` |

## Future Directions

See `docs/spec.md` for future directions.
