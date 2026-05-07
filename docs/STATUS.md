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
