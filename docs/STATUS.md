# Build Status

Track what has been built. Update checkboxes as modules are completed.

---

- [x] `config.py` — env var loading, constants
- [x] `models/session.py` — session dataclass (added `computed_data` field in M3)
- [x] `models/schemas.py` — pydantic models for LLM output validation
- [x] `db/client.py` — supabase client wrapper
- [x] `db/contacts.py` — contacts CRUD
- [x] `db/invoices.py` — invoices CRUD + atomic invoice number (RPC)
- [x] `bot/handlers.py` — full session state machine: message + callback handlers + session timeout
- [x] `bot/keyboards.py` — confirm + delivery keyboards (email/telegram/both)
- [x] `bot/formatting.py` — confirmation message formatting
- [x] `services/llm_parser.py` — claude API calls + prompt management (initial + correction modes)
- [x] `services/pdf_generator.py` — weasyprint + jinja2 (lazy import for macOS test compat)
- [x] `services/email_sender.py` — resend (MOCK_MODE logs to stdout)
- [x] `services/invoice_service.py` — `merge_and_compute` + `create_invoice` (number → PDF → storage → DB)
- [x] `templates/invoice.html` — jinja2 invoice template (matches Vence reference design)
- [x] `src/__main__.py` — entry point (run_polling)
- [x] Docker / Railway deployment
- [x] Polish batch 1: Claude retry, persistent daily cap, storage cleanup, `/healthz`, `/help` `/cancel` `/contacts`, improved `/start`, non-text fallback, dates on confirmation card

---

## MVP Polish Batch 2 — pending

- [x] **Move delivery choice before Confirm + add `/resend` and `/invoices`** — eliminates the post-Confirm RAM dependency on `pdf_bytes` (single-step pipeline) and provides a recovery path for past invoices. Closes the restart-during-active-use gap without persisting sessions. Includes a `/invoices` listing and `/resend <number>` to re-deliver from Supabase Storage.
- [x] **Guided `/contacts add` flow** — conversational onboarding so a new client can be added end-to-end from Telegram without SQL access. Reuses session state machine with a `mode` discriminator (`"invoice" | "add_contact"`).
- [x] **Resend webhook for delivery status** — `email.bounced` / `email.delivered` / `email.complained` events update the `invoices` row and notify via Telegram on failure. Extends the existing `/healthz` HTTP server.
- [x] **Pydantic-validate contact rows at the DB boundary** — introduce a `Contact` model, parse on read in `db/contacts.py` and on write in the `/contacts add` flow. Defense-in-depth; sequence alongside the guided contact-add flow so both paths share one schema.
- [x] **Guided `/contacts edit` and `/contacts delete` flows** — update or remove existing contacts from Telegram without SQL access. Reuses the same step machine as `/contacts add`.

---

## Polish Batch 3 — Contact Recognition & UX

- [x] **Add `aliases` field to Contact model** — comma-separated spoken variants (e.g. "AER, Aesthetic Radio, aesthetic") stored in DB and fed into the LLM prompt so Claude can match short nicknames and voice-transcription variants. Requires: DB migration to add `aliases` column, update `Contact` schema, update `_build_client_list` prompt format to show aliases, update `/contacts add` and `/contacts edit` flows to collect aliases.
- [x] **"Did you mean X?" fallback when client_id is null** — when the LLM returns `client_id: null` (unrecognized contact), show an inline list of known contacts as a quick-reply keyboard instead of a bare prompt. Lets the user tap the right contact rather than re-typing.
- [x] **Human-readable missing-field prompts, one at a time** — replace the flat `"I need a few more details: description, service_description, rate"` message with sequential per-field questions that name where each value appears on the invoice (e.g. "What's the header line for this invoice?").
- [x] **Greeting detection** — if the user's first message (no active session) looks like a greeting ("hello", "hi", "hey", etc.), respond with the `/start` welcome text instead of sending it to the LLM.

---

## Open bugs

- [x] **`description` null crashes invoice creation** — when the LLM doesn't extract a `description` and the contact has no `default_description`, `merge_and_compute` returned `description=None` and `save_invoice` crashed on the NOT NULL constraint (Postgres `23502`). Observed 2026-05-08 with a freshly-added `bounce_test` contact during webhook smoke-testing. Fixed in `fix/missing-description-and-reprompt-wedge`: handler-side `_augment_missing_fields` re-prompts for `description` / `service_description` / `rate` when the contact has no default, and `merge_and_compute` gained defensive `ValueError` guards.
- [x] **Re-prompt loop wedges after user answers** — when the bot re-prompted for a missing field (e.g. `description`) and the user supplied the value, the next message did not advance the session — the bot appeared stuck and the user had to `/cancel`. Root cause: the correction-mode LLM prompt had no instruction telling Claude that the user was answering the just-asked question, so plain replies like `"DJ services"` got mis-routed and the same field re-appeared in `missing_fields`. Fixed in `fix/missing-description-and-reprompt-wedge`: `parse_invoice_text` now switches to a targeted "fill-missing-field" prompt when `previous_data["missing_fields"]` is non-empty.
