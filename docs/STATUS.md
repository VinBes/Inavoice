# Build Status

Track what has been built. Update checkboxes as modules are completed.

---

- [x] `config.py` — env var loading, constants
- [x] `models/session.py` — session dataclass
- [x] `models/schemas.py` — pydantic models for LLM output validation
- [x] `db/client.py` — supabase client wrapper
- [ ] `db/contacts.py` — contacts CRUD
- [ ] `db/invoices.py` — invoices CRUD
- [ ] `bot/handlers.py` — telegram command/message handlers
- [ ] `bot/keyboards.py` — inline keyboard builders
- [ ] `bot/formatting.py` — confirmation message formatting
- [ ] `services/llm_parser.py` — claude API calls + prompt management
- [ ] `services/pdf_generator.py` — weasyprint + jinja2
- [ ] `services/email_sender.py` — resend
- [ ] `services/invoice_service.py` — number generation, storage, orchestration
- [ ] `templates/invoice.html` — jinja2 invoice template
- [ ] `src/__main__.py` — entry point
- [ ] Docker / Railway deployment
