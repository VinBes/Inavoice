# Deployment Guide

> Docker setup, Railway deployment, environment variables, and operational procedures.

---

## Local Development

### Prerequisites

- Docker and Docker Compose installed
- Python 3.11+
- A Telegram bot token (from @BotFather)
- API keys for Claude (Anthropic), Resend
- A Supabase project (free tier)

### Docker Compose Setup

The local development environment runs two services:

1. **bot** — the Inavoice Telegram bot (Python)
2. **db** — local PostgreSQL (for development only; production uses Supabase)

```yaml
# docker-compose.yml (structure reference)
services:
  bot:
    build: .
    env_file: .env
    volumes:
      - ./src:/app/src  # hot reload
    depends_on:
      - db
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: inavoice
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev
    ports:
      - "5432:5432"
```

### Running Locally

```bash
# Start services
docker compose up

# Stop services
docker compose down

# Rebuild after dependency changes
docker compose build --no-cache
```

### Hot Reload

Mount the source directory as a volume so code changes take effect without rebuilding. The bot entry point should support auto-restart on file changes during development (e.g. using watchdog or a simple restart wrapper).

---

## Local Development Mock Mode

Most development and testing should happen locally without hitting paid APIs. This keeps dev-phase costs near zero.

### What runs locally at zero cost

- The Telegram bot (polling mode works from your machine)
- PostgreSQL via Docker Compose
- WeasyPrint PDF generation (local library, no API)
- All pytest tests (always use mocks, never real APIs)
- The full application logic: state machine, validation, default merging, time/date computation

### What still requires API calls

- Claude API parsing (~$0.01-0.03/call)
- Resend email sending (free tier)

### How to avoid those costs during development

**Mock mode (`MOCK_MODE=true`):**

Set `MOCK_MODE=true` in your `.env` to enable local mocks for all external APIs. The app checks this flag and swaps real API clients for mock implementations.

**Claude API mock:** Cache 5-10 real Claude API responses for typical text commands as JSON fixtures. In mock mode, the parser returns the cached response that best matches the input (simple keyword matching is fine). Only hit the real API when testing new prompt changes or edge cases.

**Email mock:** In mock mode, emails are logged to stdout instead of sent via Resend. The log shows the full email (to, subject, body) so you can verify correctness without spamming real clients. Alternatively, always choose "download in Telegram" during dev.

### Fixture files

```
tests/
  fixtures/
    claude_responses/
      client_a_hourly_full.json
      client_a_hourly_missing_rate.json
      client_b_flat_fee.json
      unknown_client.json
```

Each fixture is a real API response captured once and reused. To refresh fixtures after prompt changes, temporarily set `MOCK_MODE=false`, run the flow, save the response, then switch back.

### Development workflow

1. Run everything locally: `docker compose up`
2. Develop and test with `MOCK_MODE=true` (zero API costs)
3. When testing prompt changes or new edge cases, set `MOCK_MODE=false` briefly, capture new fixtures, then switch back
4. Run `pytest` (always uses mocks regardless of MOCK_MODE)
5. Only deploy to Railway for end-to-end integration testing from your phone
6. Railway costs $0 when not deployed — only spin it up for integration tests

### Cost impact

| Phase | Without mock mode | With mock mode |
|-------|------------------|---------------|
| Active development (daily) | ~$15-20/month | ~$1-3/month (occasional real API calls for fixture capture) |
| pytest runs | $0 (always mocked) | $0 (always mocked) |
| Integration testing (Railway) | Only when needed | Pause between sessions ($0 while paused) |

---

## Environment Variables

### .env.example

```bash
# === Telegram ===
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_IDS=  # comma-separated, e.g. 123456789

# === Anthropic (Claude) ===
ANTHROPIC_API_KEY=

# === Resend (Email) ===
RESEND_API_KEY=
EMAIL_FROM_ADDRESS=invoice@zaraffa.online

# === Supabase ===
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=

# === Database (local dev only) ===
DATABASE_URL=postgresql://dev:dev@db:5432/inavoice

# === Invoice Sender Details ===
SENDER_NAME=
SENDER_ADDRESS=
ACCOUNT_HOLDER=
BANK_NAME=
BANK_CODE=
BANK_ACCOUNT=
FPS_ID=
BUSINESS_REGISTRATION=

# === Template ===
LOGO_PATH=assets/vence-zaraffa-logo.png

# === Cost Guardrails ===
DAILY_CLAUDE_API_CAP=20
SESSION_LLM_CALL_CAP=5
MONTHLY_COST_ALERT_THRESHOLD=5

# === App Config ===
TIMEZONE=Asia/Hong_Kong
SESSION_TIMEOUT_MINUTES=30

# === Development ===
MOCK_MODE=true
```

### Security Rules

- `.env` is in `.gitignore` — never committed
- `.env.example` is committed — contains key names only, no values
- All PII (bank details, addresses) live exclusively in `.env`
- No secrets in Docker images — passed at runtime via env vars

---

## Production Deployment (Railway)

### Initial Setup

1. Create a Railway project
2. Connect your GitHub repository
3. Railway auto-detects the Dockerfile and builds
4. Set all environment variables in Railway dashboard (same keys as .env.example, but with Supabase production credentials instead of local DB)

### Deploy Process

```
Push to main → Railway builds Docker image → deploys automatically
```

- No separate CI/CD pipeline needed for MVP
- Run `pytest` locally before pushing
- Railway supports rollback to previous deploy via dashboard

### Dockerfile (structure reference)

```dockerfile
FROM python:3.11-slim

# Install WeasyPrint system dependencies
RUN apt-get update && apt-get install -y \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "-m", "src.main"]
```

### Health Check

The Telegram bot runs in polling mode — no HTTP server needed. Railway doesn't require a health check endpoint for worker processes. Configure the Railway service as a "Worker" type (not "Web") so it doesn't expect an HTTP port.

---

## Pause / Resume

### Pause (stop incurring costs)

**Option A — Railway dashboard:**
1. Go to your Railway project
2. Click on the service
3. Settings → scale to 0 replicas

**Option B — Railway CLI:**
```bash
railway down
```

**Cost while paused:** $0 for Railway. Supabase free tier continues running (no cost).

### Resume

**Option A — Railway dashboard:**
1. Scale back to 1 replica

**Option B — Railway CLI:**
```bash
railway up
```

The bot reconnects to Telegram automatically on startup. No manual intervention needed.

---

## Database Setup (Supabase)

### Tables

Create these tables in Supabase SQL editor:

```sql
-- Invoice counter (auto-incrementing per year)
CREATE TABLE invoice_counter (
  year INTEGER PRIMARY KEY,
  counter INTEGER NOT NULL DEFAULT 0
);

-- Contacts
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

-- Invoices (metadata + storage reference)
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

### Invoice Number Upsert

```sql
INSERT INTO invoice_counter (year, counter)
VALUES ($1, 1)
ON CONFLICT (year)
DO UPDATE SET counter = invoice_counter.counter + 1
RETURNING counter;
```

This atomically creates a new year's row (starting at 1) or increments the existing counter. The returned value is used to format the invoice number: `ZARAFFA{YY}-{counter}`.

### Storage

- PDF files stored in Supabase Storage bucket (e.g. "invoices")
- File path format: `{year}/{invoice_number}.pdf`
- Free tier: 1GB storage (sufficient for thousands of invoices)
- Cleanup: delete test invoices before going live. Review storage quarterly.

---

## Logging

- Library: `structlog` (JSON output to stdout)
- Railway captures stdout automatically; logs visible in Railway dashboard
- Log retention: 7 days on Railway hobby plan (auto-purged, no cleanup needed)
- Log levels: ERROR, WARNING, INFO
- Every log entry includes `session_id` (chat_id + session timestamp) for tracing
- Sensitive data (bank details, addresses) is NEVER logged. Only log: `client_id`, `invoice_number`, `session_id`, error messages.
