# Email Spec

> Defines the email sending configuration, body template, and delivery rules.

---

## Sending Configuration

| Setting | Value |
|---------|-------|
| Service | Resend API |
| From address | invoice@zaraffa.online |
| Domain | zaraffa.online |
| Free tier limit | 3,000 emails/month |

### Environment Variables

```
RESEND_API_KEY=
EMAIL_FROM_ADDRESS=invoice@zaraffa.online
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
Zaraffa
```

### Template Variables

| Variable | Source |
|----------|--------|
| `{{INVOICE_NUMBER}}` | Generated invoice number (e.g. ZARAFFA26-3) |
| `{{SENDER_NAME}}` | From env var |
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
| Email sent successfully | "Invoice sent to {client_email} and delivered to you here." | Log success with timestamp. Update `email_sent` and `email_sent_at` in invoices table. |
| Resend API fails | "Invoice generated but email failed to send. Here's your PDF." | Send PDF via Telegram. Log error with Resend response. Do NOT retry automatically. |
| Invalid client email format | "The email address for {client_name} looks invalid. Sending PDF here instead." | Send PDF via Telegram. Log warning. |
