# Changelog

Only log decisions that deviate from the spec, significant reversals, or non-obvious choices made during implementation. If you implemented exactly what the spec says, skip the entry.

Format: `YYYY-MM-DD — [area] description (reason if not obvious)`

---

## [Unreleased]

## 2026-05-06 — MVP Polish Batch 1

- **Claude API auto-retry implemented** in `services/llm_parser.py` per spec §7. Single retry after a 3-second delay on `anthropic.APIError`; second failure surfaces as `LLMAPIError`.

- **Daily Claude API call counter persisted in Supabase** via new `claude_daily_usage` table and `increment_claude_daily_calls(p_date)` RPC. Replaces the in-memory `_daily_calls` / `_daily_reset_date` (which reset on container restart). MOCK_MODE branches to an in-memory counter — not because mock mode skips Supabase (it doesn't; contacts/invoices/storage are still real), but because no real Claude call is made under MOCK_MODE so the counter shouldn't record one, and existing tests drive the cap by poking `_daily_calls` directly.

- **Storage cleanup on `save_invoice` failure** — `services/invoice_service.py` now removes the orphaned PDF from Supabase Storage if the DB row insert fails. Invoice number stays burned (per spec §5); only the orphan storage object is removed.

- **`/healthz` endpoint** added via stdlib `http.server` running in a daemon thread (`src/health.py`). Avoids adding aiohttp/Tornado as a dependency. Configurable via `HEALTH_PORT` (default 8080). Response body is `{"status":"ok"}` only; `Server:` header value suppressed so the runtime version is not advertised. Deployment guide updated to drop the "no HTTP server needed" note.

- **Bot UX commands** added: `/help`, `/cancel`, `/contacts`. `/start` now lists known clients and an example dictation.

- **Non-text fallback handler** added: voice notes, photos, documents, etc. now get a reply explaining the bot only handles text and pointing to Wispr Flow for on-device dictation, instead of being silently dropped.

- **Confirmation card shows invoice + due dates** (`bot/formatting.py`). Invoice number is still claimed only on Confirm so it's not on the preview.

<!-- Add entries here as you build -->

---

## 2026-05-05 — Milestone 3: Bot Handlers + PDF + Email

- **`create_invoice` returns `(invoice_number, pdf_bytes)` tuple** instead of just `invoice_number`. The handler needs the bytes to deliver via Telegram immediately without re-downloading from Supabase storage.

- **`Session.computed_data` field added** alongside `parsed_data`. `parsed_data` always stores the LLMOutput-shaped dict (used as `previous_data` in correction LLM calls). `computed_data` stores the flat merged+computed dict (used for format_confirmation and PDF generation). Keeps the correction path schema-correct when the user taps Edit after a successful parse.

- **`weasyprint` imported lazily** inside `generate_pdf._sync()` rather than at module top level. WeasyPrint requires native Pango/GObject libraries (present in Docker, absent on macOS). Lazy import lets the test suite run on macOS without the system libraries.

- **Callback auth checks `query.from_user.id`** (the user who pressed the button) instead of `query.message.chat_id` (the chat the message lives in). These differ in group chats; auth must validate the actor, not the chat.

- **Resend attachment `content` uses `pdf_bytes` directly** (not `list(pdf_bytes)`). The Python SDK v2 accepts bytes; converting to a list of ints produces a malformed payload.

- **Email address not logged** in `email_sender.py`. Client email is PII; only `invoice_number` is logged per CLAUDE.md security rules.

---

## 2026-04-11 — Project initialized

- Established project structure per spec
- Chose single changelog over full ADR system — solo learning project, git log covers the rest
