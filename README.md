# Inavoice

Voice to invoice using a Telegram bot. Get back a PDF, optionally emailed to the client.

## Why this exists

Doing invoices manually always kept slipping my mind. I run a small operation out of Hong Kong (Zaraffa) and I invoice the same pool of clients regularly. The same invoice template, just different details. The repetition was annoying enough that I decided that in 2026, this should be as easy as sending a voice note.

So I built it for myself. Voice in, PDF out, sent to the client if I want it sent. It's a tool I actually use, and I will keep improving it along the way. 

## How it works

```
Telegram message (text or voice)
      ↓
  Claude parses → client, line items, dates
      ↓
  Confirm / Edit / Cancel
      ↓
  WeasyPrint renders PDF
      ↓
  Email via Resend  •or•  send PDF back in Telegram
```

## Stack

Python 3.13 · [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) · [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) · [WeasyPrint](https://weasyprint.org/) · [Supabase](https://supabase.com) · [Resend](https://resend.com) · Docker · Railway.

## Running it yourself

You will need accounts with Telegram (BotFather), Anthropic, Supabase, and Resend, plus a domain verified in Resend for outbound email. Create **two** Telegram bots — one for local development and one for production — and never run both against the same token. See [docs/deployment.md](docs/deployment.md#dev-and-production-bots) for the why and the setup steps.

```bash
git clone https://github.com/VinBes/Inavoice.git
cd Inavoice
cp .env.example .env   # then fill in credentials and sender/bank details
docker compose up
```

Set `ALLOWED_CHAT_IDS` to your own Telegram chat ID — the bot rejects everything else.

See [docs/spec.md](docs/spec.md) for the full system spec and [docs/deployment.md](docs/deployment.md) for environment variables and Railway deployment.

## Repository layout

```
src/         bot handlers, services, models, DB layer, PDF template
docs/        spec documents (system, LLM parsing, template, email, deployment, testing)
tests/       pytest suite with Claude response fixtures
hooks/       git pre-push hook (tests + pip-audit) and a Claude Code read-block hook
```

## Logos

The invoice header has two logo slots, controlled by `LOGO_LEFT_PATH` and `LOGO_RIGHT_PATH`. Both are optional and resolved relative to `src/`.

- Default: `LOGO_RIGHT_PATH` points at `assets/example-logo.png`, a generic placeholder shipped with the repo. Left slot is empty.
- To use your own logo, drop the image into `src/assets/` and override the env var: `LOGO_RIGHT_PATH=assets/my-logo.png`.
- Set neither var for a header with no logo. Set both to render two logos side by side.
- `src/assets/vence-zaraffa-logo.png` is my (the original author's) brand logo, kept in the repo so my own deploys work without an extra setup step. Forkers should ignore it and use their own image.

## Notes for forkers

- The PDF template ([src/templates/invoice.html](src/templates/invoice.html)) is hardcoded to a Hong Kong–style layout (HKD, FPS, business registration). Adapt as needed.
- Database schema is not bundled; you'll create tables in your own Supabase project. See [src/db/](src/db/) for the queries each table needs to support.
- This is a single-user tool. There is no multi-tenant auth, no UI beyond Telegram, and no plan to add either.

## License

MIT.
