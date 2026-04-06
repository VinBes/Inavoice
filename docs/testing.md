# Testing Spec

> Test cases, pytest strategy, and quality gates for Inavoice MVP.

---

## Testing Strategy

- Framework: `pytest`
- Run tests locally before every push: `pytest`
- Claude Code should run tests after every significant change
- No CI/CD pipeline — tests are developer-enforced
- Push to main triggers Railway auto-deploy (tests must pass locally first)

---

## Test Categories

### 1. LLM Output Parsing Tests

Test that the backend correctly handles LLM output JSON — validation, default merging, computation. These do NOT call the real Claude API; they test the processing layer with mock LLM responses.

#### Happy Path Tests

**Test 1.1 — Full input, hourly rate**
```
Input (mock LLM output):
{
  "client_id": "aesthetic_radio",
  "description": "Invoice for AER Hong Kong, Art.berdeen booking",
  "line_items": [{
    "service_date": "26/03/2026",
    "service_description": "DJ set at AER (Aesthetic Radio) Hong Kong",
    "time_start": "22:00",
    "time_end": "00:00",
    "rate": 500,
    "rate_type": "hourly",
    "total": null
  }],
  "missing_fields": []
}

Expected backend computation:
- hours: 2
- total: 1000
- invoice_date: today (HKT)
- due_date: today + 14 days
- invoice_number: next in sequence
```

**Test 1.2 — Full input, flat rate**
```
Input (mock LLM output):
{
  "client_id": "surge_entertainment",
  "description": "Invoice for sound system services",
  "line_items": [{
    "service_date": "15/04/2026",
    "service_description": "Sound system setup at Watermark",
    "time_start": null,
    "time_end": null,
    "rate": 2000,
    "rate_type": "flat",
    "total": null
  }],
  "missing_fields": []
}

Expected backend computation:
- hours: null (not applicable)
- total: 2000 (equals rate for flat)
- time_start/time_end: null (displayed as "—" in template)
```

**Test 1.3 — Null fields filled from client defaults**
```
Input (mock LLM output):
{
  "client_id": "aesthetic_radio",
  "description": null,
  "line_items": [{
    "service_date": "26/03/2026",
    "service_description": null,
    "time_start": "22:00",
    "time_end": "00:00",
    "rate": null,
    "rate_type": "hourly",
    "total": null
  }],
  "missing_fields": []
}

Client defaults (aesthetic_radio):
- default_description: "Invoice for AER Hong Kong booking"
- default_service_description: "DJ set at AER (Aesthetic Radio) Hong Kong"
- default_rate: 500

Expected:
- description: "Invoice for AER Hong Kong booking" (from default)
- service_description: "DJ set at AER (Aesthetic Radio) Hong Kong" (from default)
- rate: 500 (from default)
- hours: 2
- total: 1000
```

#### Edge Case Tests

**Test 1.4 — Midnight crossing (time calculation)**
```
time_start: "22:00", time_end: "02:00"
Expected hours: 4
```

**Test 1.5 — Same start and end time**
```
time_start: "22:00", time_end: "22:00"
Expected: validation error — 0 hours is invalid
```

**Test 1.6 — Missing required field, no client default**
```
Input: client_id "aesthetic_radio" (which has default_rate: 500)
       but rate is null AND client has no default_rate (test with a different client)
Expected: "rate" flagged as missing, bot asks user
```

**Test 1.7 — Unknown client_id (LLM hallucinated)**
```
Input: client_id "nonexistent_client"
Expected: validation rejects, bot asks "I don't recognize that client"
```

**Test 1.8 — Service date > 90 days in future**
```
Input: service_date far in the future
Expected: validation warning, bot asks user to confirm date
```

**Test 1.9 — Negative rate**
```
Input: rate: -500
Expected: validation rejects, bot asks user to re-state rate
```

---

### 2. Invoice Number Tests

**Test 2.1 — Sequential numbering**
```
First invoice of 2026: ZARAFFA26-1
Second invoice of 2026: ZARAFFA26-2
Expected: counter increments atomically
```

**Test 2.2 — Year rollover**
```
Last invoice of 2026: ZARAFFA26-N
First invoice of 2027: ZARAFFA27-1
Expected: new year row created, counter starts at 1
```

**Test 2.3 — Concurrent requests (idempotency)**
```
Two simultaneous Confirm taps
Expected: only one invoice number is generated, second callback is ignored
```

---

### 3. Session State Machine Tests

**Test 3.1 — Happy path state transitions**
```
PENDING → [Confirm] → CONFIRMED → GENERATING → COMPLETE
Expected: each transition is valid, PDF is generated once
```

**Test 3.2 — Edit loop**
```
PENDING → [Edit] → PENDING (with updated data) → [Confirm] → CONFIRMED → COMPLETE
Expected: correction is merged, new confirmation shown
```

**Test 3.3 — Cancel from PENDING**
```
PENDING → [Cancel] → CANCELLED
Expected: session cleaned up, no invoice generated
```

**Test 3.4 — Cancel from CONFIRMED**
```
PENDING → [Confirm] → CONFIRMED → [Cancel] → CANCELLED
Expected: session cancelled before PDF generation starts
```

**Test 3.5 — Duplicate Confirm (idempotency)**
```
PENDING → [Confirm] → CONFIRMED → [Confirm again]
Expected: second Confirm ignored, bot replies "Already processing your invoice"
```

**Test 3.6 — Session timeout**
```
PENDING → 30 minutes pass → auto-CANCELLED
Expected: bot sends "Your invoice session has expired. Please start over."
```

**Test 3.7 — Max corrections reached**
```
5 Edit cycles (initial parse + 4 corrections)
6th attempt: bot says "Too many corrections — please cancel and start over."
Expected: no further LLM calls, session stays in PENDING
```

---

### 4. Email Tests

**Test 4.1 — Client with email, user chooses "email"**
```
Expected: email sent via Resend, PDF also sent via Telegram
```

**Test 4.2 — Client without email**
```
Expected: email option not presented, PDF sent via Telegram only
```

**Test 4.3 — Email send failure**
```
Mock Resend API failure
Expected: PDF sent via Telegram, user notified "email failed to send", error logged
```

---

### 5. Cost Guardrail Tests

**Test 5.1 — Daily Claude API cap**
```
Simulate 20 Claude API calls in one day
21st call: blocked, user notified "Daily limit reached"
Expected: counter resets at midnight HKT
```

**Test 5.2 — Per-session LLM call cap**
```
5 LLM calls in one session
6th call: blocked, user told to cancel and start over
```

---

## Test Data

### Mock Client Database

```json
{
  "aesthetic_radio": {
    "display_name": "OnAer Ltd.",
    "contact_person": null,
    "address": "UG/F, Soho, Ming Hing House,\n52-56 Staunton St, Central, Hong Kong",
    "email": "accounts@onaer.example.com",
    "default_description": "Invoice for AER Hong Kong booking",
    "default_service_description": "DJ set at AER (Aesthetic Radio) Hong Kong",
    "default_rate": 500
  },
  "surge_entertainment": {
    "display_name": "Surge Entertainment",
    "contact_person": "Tamoh Gamseh Sergius",
    "address": "68 Hing Fat St.\nCauseway Bay, Hong Kong SAR",
    "email": null,
    "default_description": "Invoice for sound system & equipment services",
    "default_service_description": "Sound system setup and operation",
    "default_rate": null
  }
}
```

Note: `surge_entertainment` has no email (tests email-not-available path) and no default_rate (tests missing field path).

---

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test category
pytest tests/test_parsing.py
pytest tests/test_session.py
pytest tests/test_invoice_number.py
pytest tests/test_email.py
pytest tests/test_guardrails.py
```
