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

| Document | Location | Contents |
|----------|----------|----------|
| Spec | `docs/spec.md` | Full system spec |
| LLM Parsing Spec | `docs/llm-parsing-spec.md` | JSON schema, prompts, edge cases |
| Template Spec | `docs/template-spec.md` | Invoice layout, fields, styling |
| Email Spec | `docs/email-spec.md` | Email body, Resend config |
| Deployment Guide | `docs/deployment.md` | Docker, Railway, pause/resume, env vars |
| Testing | `docs/testing.md` | Test cases, pytest strategy |

## Development Rules

- Run `pytest` before every push
- Push to main triggers Railway auto-deploy
- All secrets in `.env` (never in code, always in .gitignore)
- No PII or bank details in any tracked file — use `{{VARIABLE}}` references
- Log to stdout with structlog (JSON format, session IDs)
- Railway auto-deploys from main; rollback via dashboard if needed

## Future Directions

See `docs/spec.md` for future directions.
