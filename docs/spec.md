# PRD — Inavoice MVP

> Product Requirements Document for Inavoice MVP. References detailed specs in sibling documents.

---

## 1. Product Overview

**Inavoice** is a personal voice-to-invoice automation tool. The user dictates invoice details using Wispr Flow (on-device voice-to-text) and sends the transcribed text via Telegram. The system parses, confirms, generates a PDF invoice, and optionally emails it to the client.

This is a personal tool and learning project. Multi-user SaaS is a possible future direction, not a current goal.

### Problem Statement

Creating invoices manually requires: duplicating a template, opening it, editing multiple fields (dates, amounts, addresses, descriptions), exporting to PDF, and emailing. This process is tedious and error-prone for a small number of recurring clients.

### Solution

A Telegram bot that reduces invoicing to a single voice command with a confirmation step.

---

## 2. MVP Scope

### In Scope

- Single user (Vincent)
- Single invoice template (Vence — see `docs/template-spec.md`)
- Telegram bot interface (text only — voice-to-text handled by Wispr Flow on device)
- Natural language parsing via Claude API (see `docs/llm-parsing-spec.md`)
- Confirmation flow with Confirm / Edit / Cancel buttons
- Correction loop via voice or text (after tapping Edit)
- PDF generation matching existing invoice design
- Email delivery via Resend (see `docs/email-spec.md`)
- PDF delivery via Telegram
- 3-5 saved client contacts with default values
- Auto-incrementing invoice numbers (ZARAFFA[YY]-[N])
- Invoice storage (PDF + metadata in Supabase)
- Cost guardrails (daily API caps, per-session limits)

### Out of Scope

- Multiple users or user accounts
- Multiple invoice templates
- Dashboard or web UI
- Multiple currencies (HKD only)
- Multiple line items per invoice (single line item, but schema supports array)
- WhatsApp or Signal integration
- Payments, subscriptions, expense tracking, bookkeeping
- Tax calculations

---

## 3. User Flow

### Primary Flow

```
1. User dictates using Wispr Flow → transcribed text sent as Telegram message
2. Claude API parses text → structured JSON (see llm-parsing-spec.md)
3. Backend validates output, merges client defaults, computes derived fields
4. If missing required fields → bot asks for all missing fields in a single message.
   User responds via text. Response goes through correction-mode LLM parsing
   with previous data as context. Session remains in PENDING throughout — this is a
   sub-loop, not a new state.
6. Bot sends confirmation message:

   ```
   📋 Invoice Preview

   Client: {display_name}
   Description: {description}
   Date: {service_date}
   Service: {service_description}
   Time: {time_start} – {time_end} ({hours} hrs)
   Rate: {rate} HKD/hr
   Total: {total} HKD

   [Confirm] [Edit] [Cancel]
   ```

   Flat fee variant: drop the Time and Rate lines, show "Flat fee: {total} HKD" instead.
7a. [Confirm] → claim invoice number → generate PDF → delivery:
    - Client has email: inline keyboard [Email] [Download] [Both]
    - Client has no email: skip question, send PDF via Telegram immediately
    → Execute chosen delivery → store PDF + metadata → session COMPLETE
7b. [Edit] → bot asks "What would you like to change?"
    → User sends correction (text)
    → LLM re-parses with previous data as context
    → Back to step 6 with updated fields
7c. [Cancel] → session CANCELLED, user starts over
```

### Session Rules

- One active session per user at a time
- Session expires after 30 minutes of inactivity (auto-cancel)
- Maximum 5 LLM calls per session (initial + 4 corrections)
- Edit mode only entered via [Edit] button tap

### State Machine

```
PENDING → CONFIRMED → GENERATING → COMPLETE
   ↓         ↓
CANCELLED  CANCELLED
```

- Duplicate Confirm callbacks are ignored; bot replies "Already processing your invoice"
- State is stored in memory (Python dict keyed by chat ID)
- Server restart loses active sessions (acceptable for single-user MVP)

---

## 4. Data Model

### Contacts Table

```sql
CREATE TABLE contacts (
  client_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  contact_person TEXT,
  address TEXT NOT NULL,
  email TEXT,
  default_description TEXT,
  default_service_description TEXT,
  default_rate NUMERIC
);
```

- `client_id`: speech-friendly alias (e.g. "aesthetic_radio", not "aer")
- `email`: if null, email delivery option is hidden for this client
- `default_description`: header line above invoice table (separate from line item description)
- `default_service_description`: text in the table's Service column
- `default_rate`: if null, user must provide rate every time

Client data to be populated during the build phase.

### Invoices Table

```sql
CREATE TABLE invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_number TEXT NOT NULL UNIQUE,
  client_id TEXT NOT NULL REFERENCES contacts(client_id),
  invoice_date DATE NOT NULL,
  due_date DATE NOT NULL,
  description TEXT NOT NULL,
  line_items JSONB NOT NULL,
  subtotal NUMERIC NOT NULL,
  pdf_storage_path TEXT NOT NULL,
  email_sent BOOLEAN NOT NULL DEFAULT FALSE,
  email_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- `line_items` stores the full array as JSONB (future-proof for multi-line)
- `subtotal` is the sum of all line item totals

### Invoice Counter Table

```sql
CREATE TABLE invoice_counter (
  year INTEGER PRIMARY KEY,
  counter INTEGER NOT NULL DEFAULT 0
);
```

Upsert pattern for atomic increment — see `docs/deployment.md`.

### Session Object (in-memory)

Keyed by `chat_id` in a module-level dict. Not persisted — server restart loses active sessions (acceptable for single-user MVP).

```python
@dataclass
class Session:
    state: str          # PENDING | CONFIRMED | GENERATING | COMPLETE | CANCELLED
    parsed_data: dict | None
    llm_call_count: int
    created_at: datetime
    last_active: datetime
    invoice_number: str | None  # claimed on Confirm, before PDF generation
    message_id: int | None      # Telegram message ID of the confirmation message (for editing)
```

---

## 5. Invoice Number Scheme

- Format: `ZARAFFA[YY]-[N]` (e.g. ZARAFFA26-1, ZARAFFA26-2)
- Prefix "ZARAFFA" is universal regardless of template
- Counter resets to 1 each calendar year
- Voided/cancelled invoices: number is skipped, not reused
- Number is claimed at the moment of Confirm (before PDF generation)
- If PDF generation fails after number is claimed, the number is burned

---

## 6. Date, Time, and Currency

- All dates: DD/MM/YYYY (European format) in invoice, DD Month YYYY in display
- Timezone: HKT (Asia/Hong_Kong, UTC+8)
- Invoice date: always today (HKT)
- Due date: invoice date + 14 days
- Time: 24-hour format (22:00, not 10 PM)
- Currency: HKD only (system-wide constant, not configurable)
- Payment terms: 14 days (system-wide constant)

---

## 7. Error Handling

| Failure | User Message | System Behavior |
|---------|-------------|-----------------|
| Claude API fails | "Something went wrong processing your request. Try again in a minute." | Auto-retry once (3s delay). Log error. |
| Validation fails | Bot names the problematic field, asks to re-state or restart | Checks: client exists, amounts > 0, date ≤ 90 days future |
| PDF generation fails | "Failed to generate the PDF. This is a system error — try again." | Log stack trace. This is a bug signal. |
| Email fails | "Invoice generated but email failed to send. Here's your PDF." | Send PDF via Telegram. Log error. No auto-retry. |
| Unknown client | "I don't recognize that client. Which client should this be for?" | LLM sets client_id null; backend confirms non-existence. |
| Session timeout | "Your invoice session has expired. Please start over." | Auto-cancel after 30 min. Clean up session. |
| Daily API cap | "Daily limit reached, try again tomorrow." | Block until midnight HKT. |
| Session LLM cap | "Too many corrections — please cancel and start over." | No further LLM calls for this session. |
| Duplicate Confirm | "Already processing your invoice." | Ignore callback. No duplicate work. |

---

## 8. Cost Guardrails

| Guardrail | Default | Env Variable |
|-----------|---------|-------------|
| Claude API calls/day | 20 | `DAILY_CLAUDE_API_CAP` |
| LLM calls/session | 5 | `SESSION_LLM_CALL_CAP` |
| Monthly cost alert | $5 | `MONTHLY_COST_ALERT_THRESHOLD` |

- All configurable via environment variables
- Monthly alert: Telegram notification when estimated spend exceeds threshold
- API calls logged with timestamp and estimated cost

### Cost Estimates

| Scenario | Monthly Cost |
|----------|-------------|
| Realistic (2-3 invoices/month) | ~$2-3 |
| Development (heavy testing) | ~$10-15 |
| Worst case (Claude cap maxed daily) | ~$15-18 |

---

## 9. Security

- Bot rejects messages from chat IDs not in `ALLOWED_CHAT_IDS`. Unauthorized users receive no response.
- All secrets in environment variables (never in code or tracked files)
- No PII or bank details in source code — `{{VARIABLE}}` references only
- Telegram bot token: scoped to this bot
- Email credentials: scoped to invoice@zaraffa.online
- Docker container isolation
- HTTPS for all external API calls
- Structured logging redacts sensitive data (no addresses or bank details in logs)
- Supabase RLS not needed for MVP but schema doesn't block it

---

## 10. Infrastructure

See `docs/deployment.md` for full details.

- **Local dev:** Docker Compose (bot + local PostgreSQL)
- **Production:** Railway (single Docker container) + Supabase (managed PostgreSQL + storage)
- **Deploy:** push to main → Railway auto-deploys
- **Pause:** Railway scale to 0 ($0 while paused)
- **Logging:** structlog to stdout, Railway captures (7-day retention, auto-purged)
- **Rollback:** via Railway dashboard

---

## 11. Testing

See `docs/testing.md` for full test cases.

- Run `pytest` before every push
- Test categories: LLM output processing, invoice numbering, session state machine, email delivery, cost guardrails
- Mock LLM responses (no real API calls in tests)
- Mock client database for test isolation

---

## 12. Future Directions

These are possible expansions, not commitments. Revisit after 3 months of MVP use.

- **Voice transcription (V1):** Add server-side transcription so raw Telegram voice notes are supported without requiring Wispr Flow. Evaluate alternatives to Whisper API (e.g. Groq Whisper, local Whisper, Deepgram) before committing to a provider.
- **Dashboard:** Next.js web app (separate service) for managing templates and contacts
- **Multiple templates:** user uploads PDF/image reference → LLM extracts layout → HTML/CSS template generated
- **Multi-user:** Supabase RLS, user accounts, login
- **WhatsApp / Signal:** additional messaging platform integrations
- **Multiple line items:** schema already supports this; UI/parsing needs extension

If none of these have started after 3 months, consider simplifying the stack (e.g. drop Supabase for SQLite).
