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
