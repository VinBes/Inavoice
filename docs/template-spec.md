# Template Spec — Vence Invoice

> Defines the invoice template layout, fields, and styling for the MVP.

---

## Template Overview

The MVP uses a single template: the Vence invoice (dual logo: VENCE + ZARAFFA). This template is hardcoded in HTML/CSS and rendered to PDF via WeasyPrint.

---

## Template Engine

Variables are injected using Jinja2 with `FileSystemLoader`. The template is a single HTML file at `src/templates/invoice.html`. The environment is initialized with `autoescape=True` so any client-supplied strings (names, addresses, descriptions) are HTML-escaped before rendering.

```python
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("src/templates"),
    autoescape=True
)
```

---

## Layout Structure

```
┌──────────────────────────────────────────────────┐
│                              [VENCE + ZARAFFA    │
│                                        LOGO]     │
│                              Invoice Date        │
│                              {{INVOICE_DATE}}     │
│                              Invoice Number       │
│                              {{INVOICE_NUMBER}}   │
│                                                   │
│  INVOICE                                          │
│                                                   │
│  {{SENDER_NAME}}                                  │
│  {{SENDER_ADDRESS}}                               │
│                                                   │
│  {{DESCRIPTION}}                                  │
│                                                   │
│  {{RECIPIENT_NAME}}                               │
│  {{RECIPIENT_ADDRESS}}                            │
│                                                   │
│  ┌────────┬───────────┬───────┬──────┬─────┬────┐│
│  │ Date   │ Service   │ Time  │Hours │Rate │Total││
│  ├────────┼───────────┼───────┼──────┼─────┼────┤│
│  │{{DATE}}│{{SERVICE}}│{{TIME}}│{{H}} │{{R}}│{{T}}││
│  ├────────┴───────────┴───────┴──────┼─────┼────┤│
│  │                     total (HKD)   │     │{{T}}││
│  └───────────────────────────────────┴─────┴────┘│
│                                                   │
│  Due Date                                         │
│  {{DUE_DATE}}                                     │
│                                                   │
│  Account Details                                  │
│  {{BANK_DETAILS}}                                 │
│                                                   │
│  {{BUSINESS_REGISTRATION}}                        │
└──────────────────────────────────────────────────┘
```

---

## Static Fields

These values are stored in environment variables or a config file (never hardcoded in source code). They are the same on every invoice.

| Field | Env Variable | Description |
|-------|-------------|-------------|
| Sender name | `{{SENDER_NAME}}` | Invoice issuer's full name |
| Sender address | `{{SENDER_ADDRESS}}` | Multi-line postal address |
| Left logo | `{{LOGO_LEFT_PATH}}` | Optional. Path to left-header logo image, relative to `src/`. Empty → slot renders empty. |
| Right logo | `{{LOGO_RIGHT_PATH}}` | Optional. Path to right-header logo image, relative to `src/`. Empty → slot renders empty. Defaults to `assets/example-logo.png`. |
| Bank name | `{{BANK_NAME}}` | Full bank name |
| Bank code | `{{BANK_CODE}}` | Bank institution code |
| Branch-account number | `{{BANK_ACCOUNT}}` | Branch code + account number |
| Account holder | `{{ACCOUNT_HOLDER}}` | Name on bank account |
| FPS ID | `{{FPS_ID}}` | Faster Payment System identifier |
| Business registration | `{{BUSINESS_REGISTRATION}}` | Business name + registration number |
| Currency | HKD | System-wide constant (not env var) |
| Payment terms | 14 days | System-wide constant (not env var) |

### .env.example

```
SENDER_NAME=
SENDER_ADDRESS=
LOGO_LEFT_PATH=
LOGO_RIGHT_PATH=assets/example-logo.png
BANK_NAME=
BANK_CODE=
BANK_ACCOUNT=
ACCOUNT_HOLDER=
FPS_ID=
BUSINESS_REGISTRATION=
```

---

## Variable Fields

These change per invoice and come from the LLM parser output, backend computation, or client defaults.

| Field | Source | Format |
|-------|--------|--------|
| Invoice date | Auto (today, HKT) | DD Month YYYY (e.g. "31 March 2026") |
| Invoice number | Auto (database counter) | ZARAFFA[YY]-[N] (e.g. "ZARAFFA26-3") |
| Description | LLM or client default | Free text (e.g. "Invoice for AER Hong Kong, Art.berdeen booking") |
| Recipient name | Client database | Full legal name |
| Recipient address | Client database | Multi-line address |
| Service date | LLM output | DD/MM/YYYY in table cell |
| Service description | LLM or client default | Free text in table cell |
| Time range | LLM output | "HH:MM - HH:MM" (e.g. "22:00 - 0:00") |
| Hours | Backend computed | Integer or decimal |
| Rate | LLM or client default | Number + " HKD" (e.g. "500 HKD") |
| Total | Backend computed | Number + " HKD" (e.g. "1000 HKD") |
| Due date | Backend computed | DD Month YYYY |

---

## Table Columns

The invoice table always shows these columns for the Vence template:

| Column | Width (approx) | Content |
|--------|---------------|---------|
| Date | 15% | Service date (DD/MM/YYYY) |
| Service | 30% | Service description text |
| Time | 15% | Time range (HH:MM - HH:MM) |
| Hours | 10% | Computed hours |
| Rate | 15% | Rate + currency |
| Total | 15% | Line total + currency |

### Flat Fee Handling

When `rate_type` is "flat":
- Time column: empty or "—"
- Hours column: empty or "—"
- Rate column: shows the flat fee amount
- Total column: same as rate

---

## Styling Requirements

The PDF must match the existing Vence invoice design as closely as possible.

### Typography
- Heading "INVOICE": large, bold, sans-serif
- Body text: standard sans-serif (match Google Docs default — Arial or similar)
- Table headers: bold
- "Due Date" and "Account Details" labels: bold, red/dark accent color

### Layout
- Logo: top-right corner
- Invoice date and number: right-aligned, below logo
- Sender info: left-aligned, below "INVOICE" heading
- Description and recipient: left-aligned, below sender
- Table: full width, bordered cells
- Due date section: below table, left-aligned
- Account details: below due date
- Business registration: bottom of page

### Table Styling
- Header row: bold text, top/bottom borders
- Data rows: bordered cells
- Totals row: bold, right-aligned label "total (HKD)"
- Borders: thin solid lines

### Page Size
- A4 (210mm × 297mm)
- Margins: standard (approximately 25mm all sides)

---

## Subtotal vs. Total

- For single line items (MVP): "total (HKD)" row shows the line total
- For multiple line items (future): "Subtotal (HKD)" row shows the sum of all line totals
- No tax calculations in scope

---

## Logo Assets

The invoice header has two logo slots — left and right — controlled by `LOGO_LEFT_PATH` and `LOGO_RIGHT_PATH`. Both are optional. Each path is resolved relative to `src/` (WeasyPrint's `base_url`).

- Empty / unset → that slot renders nothing (no `<img>` tag, no broken-image icon).
- Set one → only that slot renders.
- Set both → they render side by side.

The repo ships with `src/assets/example-logo.png` as the default for the right slot so a fresh clone renders a visible placeholder. Drop your own image into `src/assets/` and point the env var at it to override.
