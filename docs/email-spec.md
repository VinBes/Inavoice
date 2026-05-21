# Email Spec

> Defines the email sending configuration, body template, and delivery rules.

---

## Sending Configuration

| Setting | Value |
|---------|-------|
| Service | Resend API |
| From address | `EMAIL_FROM_ADDRESS` env var, e.g. `invoice@yourdomain.com` |
| Domain | Verified in Resend |
| Free tier limit | 3,000 emails/month |

### Environment Variables

```
RESEND_API_KEY=
EMAIL_FROM_ADDRESS=    # required; must be a verified Resend sender, e.g. invoice@yourdomain.com
SENDER_COMPANY=        # optional; appended below SENDER_NAME in the signature
```

---

## Email Body Template

**Subject:** `Invoice {{INVOICE_NUMBER}} — {{SENDER_NAME}}`

**Body:**

```
Dear {{CONTACT_PERSON or DISPLAY_NAME}},

Please find attached invoice {{INVOICE_NUMBER}} for services rendered.

Payment is due by {{DUE_DATE}}. Payment details are included in the invoice.

Kind regards,
{{SENDER_NAME}}
{{SENDER_COMPANY}}
```

If `SENDER_COMPANY` is empty or unset, the company line is omitted and the
signature is just `{{SENDER_NAME}}`.

### Template Variables

| Variable | Source |
|----------|--------|
| `{{INVOICE_NUMBER}}` | Generated invoice number (e.g. ZARAFFA26-3) |
| `{{SENDER_NAME}}` | From env var |
| `{{SENDER_COMPANY}}` | From env var; optional, omitted when empty |
| `{{CONTACT_PERSON}}` | From client database (may be null) |
| `{{DISPLAY_NAME}}` | From client database (fallback if no contact_person) |
| `{{DUE_DATE}}` | Computed: invoice_date + 14 days, formatted as "DD Month YYYY" |

### Greeting Logic

- If client has `contact_person`: "Dear {contact_person},"
- If client has no `contact_person`: "Dear {display_name},"

---

## Attachment

- The generated invoice PDF is attached to the email
- Filename format: `Invoice_{{INVOICE_NUMBER}}.pdf` (e.g. `Invoice_ZARAFFA26-3.pdf`)

---

## Delivery Rules

1. Email is only sent when the user explicitly taps `Confirm + Email`. Tapping
   `Confirm + Email` always also delivers the PDF via Telegram in the same
   callback — there is no separate "Both" option.
2. If the client has no email address in the contacts database, the email option
   is not presented. The user sees a single `Confirm` button that delivers the
   PDF via Telegram.
3. The PDF is always sent back via Telegram regardless of whether email is also
   sent. This invariant also applies to `/resend`: the PDF is always returned to
   Telegram; the `email` flag is opt-in for re-emailing.

---

## Error Handling

| Scenario | User-facing message | System behavior |
|----------|--------------------|-----------------| 
| Email sent successfully | "Invoice sent to {client_email} and delivered to you here." | Log success with timestamp. The Resend message id is captured and persisted on the `invoices.email_id` column so the delivery webhook can match the row. `email_sent` / `email_sent_at` are flipped only when the Resend `email.delivered` webhook arrives (the synchronous send only confirms acceptance by Resend, not by the recipient's mail server). |
| Resend API fails | "Invoice generated but email failed to send. Here's your PDF." | Send PDF via Telegram. Log error with Resend response. Do NOT retry automatically. |
| Invalid client email format | "The email address for {client_name} looks invalid. Sending PDF here instead." | Send PDF via Telegram. Log warning. |

---

## Delivery Webhooks

The Resend webhook endpoint at `/webhooks/resend` (served by the same
stdlib HTTP listener as `/healthz`) handles three event types:

| Event | DB update | Telegram alert |
|-------|-----------|----------------|
| `email.delivered` | `email_delivery_status="delivered"`, `email_sent=true`, `email_sent_at=<event time>` | None |
| `email.bounced` | `email_delivery_status="bounced"` | `⚠️ Invoice {N} bounced. {reason}` to every chat in `ALLOWED_CHAT_IDS` |
| `email.complained` | `email_delivery_status="complained"` | `⚠️ Invoice {N} marked as spam by recipient.` to every chat in `ALLOWED_CHAT_IDS` |

### Verification

- Webhook bodies are signed by Resend via the [Svix](https://www.svix.com)
  scheme (`svix-id`, `svix-timestamp`, `svix-signature` headers). The bot
  verifies every request with the `svix` Python package against
  `RESEND_WEBHOOK_SECRET` (required at startup).
- `MOCK_MODE=true` skips signature verification so local dev / tests can hit
  the endpoint with plain `curl`.

### Idempotency

Resend retries webhooks on 5xx and timeouts. The bot only broadcasts a
Telegram alert if the new status differs from the persisted
`email_delivery_status` — a duplicate `email.bounced` for an already-bounced
invoice is silently acked.

### Unknown payloads

- Unknown `email_id` (no row matches) → 200 ack, INFO log, no DB write,
  no broadcast. Could be a stray retry or a pre-existing invoice issued
  before `email_id` was being persisted.
- Unknown event type (e.g. `email.opened`) → 200 ack, no DB write. Resend
  may add new event types and the endpoint must not flap.

### Multi-user TODO

The bounce / complaint broadcast currently goes to **every** chat in
`ALLOWED_CHAT_IDS`. When the bot is extended beyond a single user, the
`invoices` table must gain a `sent_by_chat_id` column and the webhook must
route alerts to that chat only. Tracked here so the rule isn't lost when
multi-user is revisited.
