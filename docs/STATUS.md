# Build Status

Track what has been built. Update checkboxes as modules are completed.

---

- [x] `config.py` — env var loading, constants
- [x] `models/session.py` — session dataclass
- [x] `models/schemas.py` — pydantic models for LLM output validation
- [x] `db/client.py` — supabase client wrapper
- [x] `db/contacts.py` — contacts CRUD
- [x] `db/invoices.py` — invoices CRUD + atomic invoice number (RPC)
- [ ] `bot/handlers.py` — telegram command/message handlers
- [ ] `bot/keyboards.py` — inline keyboard builders
- [x] `bot/formatting.py` — confirmation message formatting
- [x] `services/llm_parser.py` — claude API calls + prompt management (initial + correction modes)
- [ ] `services/pdf_generator.py` — weasyprint + jinja2
- [ ] `services/email_sender.py` — resend
- [x] `services/invoice_service.py` — `merge_and_compute` done; `create_invoice` pending (PDF/email)
- [ ] `templates/invoice.html` — jinja2 invoice template
- [ ] `src/__main__.py` — entry point
- [ ] Docker / Railway deployment
