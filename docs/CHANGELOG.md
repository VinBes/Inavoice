# Changelog

Only log decisions that deviate from the spec, significant reversals, or non-obvious choices made during implementation. If you implemented exactly what the spec says, skip the entry.

Format: `YYYY-MM-DD — [area] description (reason if not obvious)`

---

## [Unreleased]

## 2026-05-07 — Atomic Confirm + /invoices + /resend

- **Confirm and delivery collapsed into one tap (spec §3 step 7 deviation).** The two-step flow (Confirm → choose Email/Telegram/Both) is now a single tap. New keyboard layout: contacts with email show `[Confirm + Email] [Confirm (Telegram)]` on row 1 and `[Edit] [Cancel]` on row 2; contacts without email show `[Confirm] [Edit] [Cancel]`. Reason: a Railway redeploy between Confirm and the delivery tap was burning the invoice number and stranding the PDF in storage with no recovery path. Collapsing the flow eliminates the in-memory `pdf_bytes` round-trip via `context.user_data` so a process restart cannot strand a partially delivered invoice. The "Both" option is dropped — `Confirm + Email` always also delivers the PDF via Telegram (matches the existing email-spec invariant). Spec §3 and email-spec §Delivery Rules updated.

- **`/invoices` command added (not in spec).** Lists the 10 most recent invoices in compact one-line format (`number · date · client · subtotal HKD`). Read-only against Supabase. Spec ranking: lowest priority of MVP polish batch 2, but cheap and high daily-utility once /resend is shipped.

- **`/resend <invoice_number> [email]` command added (not in spec).** Re-delivers a past invoice via Telegram by default; pass the literal `email` arg to also re-email through Resend. PDF bytes are fetched from Supabase Storage by `pdf_storage_path` — nothing is regenerated. Argument parsing rejects unknown second args explicitly. Email re-send to a contact that has been deleted or had its email removed degrades gracefully (PDF still delivered via Telegram, message names the missing client_id).

- **`last_resent_at TIMESTAMPTZ` column added to `invoices` table.** Set whenever `/resend ... email` succeeds; `email_sent_at` is left untouched so the original send time is preserved. Migration applied via Supabase MCP `apply_migration` tool, name `add_last_resent_at_to_invoices`. `docs/deployment.md` schema updated with both the new column and an `ALTER TABLE … IF NOT EXISTS` for idempotent re-application.

- **Spec state machine corrected.** `docs/spec.md` previously documented `PENDING → CONFIRMED → GENERATING → COMPLETE`, but the implementation never set `CONFIRMED` (dead state). The diagram now reads `PENDING → GENERATING → COMPLETE` to match the code. The unused `CONFIRMED` constant in `models/session.py` is left in place; removing it is more churn than value.

- **`download_pdf` placement decision.** Storage I/O for past-invoice retrieval lives in `db/invoices.py` rather than `services/invoice_service.py` (where existing storage ops sit). Reason: `download_pdf` is a pure fetch, paired with `get_invoice` metadata, and colocation reads more naturally. Existing storage ops in `invoice_service.py` are orchestration-coupled (upload + DB-row insert) so they stay where they are.

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
