# Changelog

Only log decisions that deviate from the spec, significant reversals, or non-obvious choices made during implementation. If you implemented exactly what the spec says, skip the entry.

Format: `YYYY-MM-DD — [area] description (reason if not obvious)`

---

## [Unreleased]

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
