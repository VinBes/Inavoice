# Changelog

Only log decisions that deviate from the spec, significant reversals, or non-obvious choices made during implementation. If you implemented exactly what the spec says, skip the entry.

Format: `YYYY-MM-DD — [area] description (reason if not obvious)`

---

## [Unreleased]

## 2026-05-20 — Contacts gain `aliases` column (Polish Batch 3 part 1)

- **`contacts.aliases TEXT NOT NULL DEFAULT ''`** added. Stored as a
  comma-separated string in Supabase; exposed as `list[str]` in `Contact`
  via a `@field_validator("aliases", mode="before")` that splits on comma +
  strips whitespace + drops empties, and a `@field_serializer("aliases")`
  that joins back to a string on write. Migration name:
  `add_aliases_to_contacts`. Applied in Wave 3 of Polish Batch 3.
- **Fed into the LLM prompt.** `_build_client_list` in
  `src/services/llm_parser.py` renders a contact with aliases as
  `"client_a" → Client A Ltd. (also: AER, aesthetic)` so Claude can map
  nicknames and voice-transcription variants. No `(also: …)` suffix when
  the alias list is empty.
- **Fed into the MOCK_MODE fixture matcher.** `_load_mock_response` now
  also matches when any alias substring (case-insensitive) appears in the
  input text, alongside the existing `client_id` / `display_name`
  matching. New fixture `aesthetic_radio_hourly_full.json` exercises the
  alias path against a real contact.
- **Surfaced in the `/contacts` add/edit flow.** New optional step in
  `bot/contact_flow.py` after `default_rate`; new Aliases button on the
  edit picker keyboard. `format_contact_summary` renders an `Aliases:`
  line (joined with commas, or `(none)`).

## 2026-05-20 — Sequential missing-field collection (deviation from spec §3 step 4)

- Missing-field collection switched from a single flat message ("I need a
  few more details: description, rate. Please provide them.") to a
  sequential per-field flow. The bot first sends a rich OVERVIEW message
  mapping each missing field to where it appears on the invoice plus an
  example, then asks ONE field per message.
- Answers are validated locally (no LLM call per answer): positive Decimal
  for `rate`, contacts existence for `client_id`. Extra information typed
  alongside the value is ignored — the user can refine further via [Edit]
  on the confirmation card.
- New `Session.mode = "fill_missing"`; logic lives in
  `src/bot/missing_field_flow.py`. The LLM correction loop now applies only
  to [Edit] taps and unknown-client recovery.

## 2026-05-08 — Startup guard: MOCK_MODE forbidden when DEPLOY_ENV=prod

- `src/config.py` now raises `RuntimeError` at import time if
  `MOCK_MODE=true` and `DEPLOY_ENV=prod`. MOCK_MODE skips Svix signature
  verification on the Resend webhook (`src/health.py:148`); accidentally
  setting it in Railway would let anyone on the internet spoof delivery
  events and trigger Telegram broadcasts + DB writes. Fail-closed at startup
  rather than silently degrading webhook auth in production.
- Comparison is lowercase to catch `Prod`/`PROD` typos. Local dev
  (`DEPLOY_ENV=local`) and tests (`DEPLOY_ENV=test`, set in `conftest.py`)
  remain unaffected.

## 2026-05-08 — Missing-field detection moved to handler (deviation from llm-parsing-spec §3)

- `docs/llm-parsing-spec.md` (§"Missing fields") assigns detection of missing
  `description` / `service_description` / `rate` to the LLM. In practice
  Claude Haiku occasionally omits the entry from `missing_fields` even when
  the field is null and the contact has no default — flowing a NULL through
  to `invoice_service.merge_and_compute` and on to the `invoices` table where
  Postgres rejects with NOT NULL violation 23502. Authority for "is this
  field missing?" now lives in `bot/handlers.py:_augment_missing_fields`,
  which uses the LLM's list as a hint and corrects it against the resolved
  contact's defaults. The handler can also drop fields the LLM over-reports.
- `merge_and_compute` gains symmetric `ValueError` guards for `description`
  and `service_description` (matching the existing rate guard) — defensive
  net so any future caller that bypasses the handler gets a clear error
  instead of a Postgres NULL violation.
- `parse_invoice_text` gains a third "fill-missing-field" prompt branch.
  Selected when `previous_data["missing_fields"]` is non-empty. Tells Claude
  the user's input is the answer to the just-asked question, instead of a
  free-form edit. Without it, plain replies like "DJ services" got
  mis-routed by the general correction prompt and the same field re-appeared
  in `missing_fields`, wedging the loop until `/cancel`.

## 2026-05-08 — Resend delivery webhook + /contacts edit & delete

- **Resend webhook receiver added (`/webhooks/resend`)**, extending the existing
  `/healthz` stdlib HTTP server (`src/health.py`). Subscribes to
  `email.delivered`, `email.bounced`, `email.complained`. Verifies Svix
  signatures via the `svix` Python package. The webhook handler runs in the
  health server's daemon thread and dispatches async DB / Telegram calls back
  to the bot's asyncio loop via `asyncio.run_coroutine_threadsafe`. The HTTP
  thread → asyncio bridge is set up from an `Application.post_init` hook that
  captures the running loop. `build_application(extra_post_init=...)` chains
  the existing command-registration hook with the new one.
- **`MOCK_MODE` skips webhook signature verification** so local dev / tests
  can hit the endpoint with `curl` without forging Svix signatures. Production
  always verifies.
- **`RESEND_WEBHOOK_SECRET` is required at startup** (raises if missing,
  matching `TELEGRAM_BOT_TOKEN`). Documented in `docs/deployment.md`.
- **Three new columns on `invoices`** (`email_id`, `email_delivery_status`,
  `email_delivery_event_at`) plus index `invoices_email_id_idx`. Migration
  `add_email_delivery_columns_to_invoices` is idempotent (`ADD COLUMN IF NOT
  EXISTS`). `email_sender.py` now returns the Resend message id and
  `_execute_confirm` persists it via the new `update_email_id` so the webhook
  can find the invoice. **Pre-existing invoices without `email_id` are
  unmatched** if their delivery events arrive — by design (acceptable for the
  small invoice volume).
- **Bounce / complaint events broadcast a Telegram alert to every chat in
  `ALLOWED_CHAT_IDS`.** Idempotency: only broadcast if the persisted
  `email_delivery_status` differs from the new one (Resend retries
  duplicates). **Multi-user TODO** in `docs/email-spec.md` — when more than
  one chat is allowed, store `sent_by_chat_id` on the invoice row and route
  alerts to that chat instead of broadcasting.
- **Guided `/contacts edit <client_id>` flow** (`bot/contact_flow.py`).
  Inline keyboard with one button per editable field plus Done; tapping a
  field prompts with the current value, validates via the same `_STEPS`
  validators as `add`, and `upsert_contact`s on success. The contact is
  re-read each cycle so the picker always shows the persisted state.
  `client_id` is NOT editable (PK — user must delete and re-add to rename).
  New session mode `"edit_contact"`.
- **Guided `/contacts delete <client_id>` flow** (`bot/contact_flow.py`).
  No new session mode — uses transient `Session.delete_target`. Pre-checks
  `count_invoices_for_contact`; refuses with a friendly message naming the
  count if any invoices reference the contact (the FK constraint is the
  safety net but the pre-check gives a friendlier error). Re-checks the count
  at confirm time (TOCTOU defense). Stale callback whose embedded client_id
  doesn't match `session.delete_target` is silently ignored.

## 2026-05-07 — Contact model + guided /contacts add

- **`Contact` Pydantic model added (`models/schemas.py`).** Validates `client_id`
  against a slug regex (`^[a-z0-9_]{1,64}$`), `email` against a deliberately
  lenient regex (no `email-validator` dependency — Resend re-validates at send
  time), and `default_rate > 0`. `db/contacts.py` now returns `Contact`/`list[Contact]`
  on read and accepts a `Contact` on write. **Read validation is strict**: if a
  Supabase row fails `Contact.model_validate`, the `ValidationError` propagates
  and the existing handler `try/except` surfaces a generic error. This is
  intentional — a malformed contact row is a data-integrity problem, not a
  recoverable user error.

- **`Contact` plumbed through services and handlers, not just the DB boundary.**
  `merge_and_compute` and `resend_invoice` (`services/invoice_service.py`) now
  take a `Contact` and use attribute access; the `/start` and `/contacts` listings
  in `bot/handlers.py` follow suit. `services/llm_parser.py` accepts either
  `Contact` instances or dicts via `getattr(... or ...["..."])` so existing test
  fixtures don't need to wrap rows.

- **`Session.mode` discriminator added** (`"invoice" | "add_contact"`, default
  `"invoice"`). Additive: existing `Session()` constructions are unchanged.
  `contact_draft: Optional[dict]` field added to hold partial collection state.

- **Guided `/contacts add` flow added (`bot/contact_flow.py`).** Step-by-step
  prompts for the eight Contact fields; `skip` accepted on optional fields
  (`contact_person`, `email`, `default_description`, `default_service_description`,
  `default_rate`). Validation per step routes through the `Contact` model so the
  rule lives in one place. Final step shows a summary with `[Confirm] [Cancel]`;
  Confirm validates the draft and calls `upsert_contact`.

- **Conflict rule for `/contacts add` (not in spec):** if an invoice session is
  in `GENERATING`, the command is blocked with "An invoice is being generated.
  Please wait." Any session in `PENDING` is silently replaced with a notice
  ("Pending draft cancelled. Starting contact setup…"). Single-user MVP — no
  persisted draft, no safety win in forcing `/cancel` first.

- **`/contacts` command extended** — `context.args == ["add"]` starts the guided
  flow; no args lists contacts as before. No new Telegram command registered;
  argument-style sub-command keeps the surface minimal.

## 2026-05-07 — Atomic Confirm + /invoices + /resend

- **Confirm and delivery collapsed into one tap (spec §3 step 7 deviation).** The two-step flow (Confirm → choose Email/Telegram/Both) is now a single tap. New keyboard layout: contacts with email show `[Confirm + Email] [Confirm (Telegram)]` on row 1 and `[Edit] [Cancel]` on row 2; contacts without email show `[Confirm] [Edit] [Cancel]`. Reason: a Railway redeploy between Confirm and the delivery tap was burning the invoice number and stranding the PDF in storage with no recovery path. Collapsing the flow eliminates the in-memory `pdf_bytes` round-trip via `context.user_data` so a process restart cannot strand a partially delivered invoice. The "Both" option is dropped — `Confirm + Email` always also delivers the PDF via Telegram (matches the existing email-spec invariant). Spec §3 and email-spec §Delivery Rules updated.

- **`/invoices` command added (not in spec).** Lists the 10 most recent invoices in compact one-line format (`number · date · client · subtotal HKD`). Read-only against Supabase. Spec ranking: lowest priority of MVP polish batch 2, but cheap and high daily-utility once /resend is shipped.

- **`/resend <invoice_number> [email]` command added (not in spec).** Re-delivers a past invoice via Telegram by default; pass the literal `email` arg to also re-email through Resend. PDF bytes are fetched from Supabase Storage by `pdf_storage_path` — nothing is regenerated. Argument parsing rejects unknown second args explicitly. Email re-send to a contact that has been deleted or had its email removed degrades gracefully (PDF still delivered via Telegram, message names the missing client_id).

- **`last_resent_at TIMESTAMPTZ` column added to `invoices` table.** Set whenever `/resend ... email` succeeds; `email_sent_at` is left untouched so the original send time is preserved. Migration applied via Supabase MCP `apply_migration` tool, name `add_last_resent_at_to_invoices`. `docs/deployment.md` schema updated with both the new column and an `ALTER TABLE … IF NOT EXISTS` for idempotent re-application.

- **Spec state machine corrected.** `docs/spec.md` previously documented `PENDING → CONFIRMED → GENERATING → COMPLETE`, but the implementation never set `CONFIRMED` (dead state). The diagram now reads `PENDING → GENERATING → COMPLETE` to match the code. The unused `CONFIRMED` constant in `models/session.py` is left in place; removing it is more churn than value.

- **`download_pdf` placement decision.** Storage I/O for past-invoice retrieval lives in `db/invoices.py` rather than `services/invoice_service.py` (where existing storage ops sit). Reason: `download_pdf` is a pure fetch, paired with `get_invoice` metadata, and colocation reads more naturally. Existing storage ops in `invoice_service.py` are orchestration-coupled (upload + DB-row insert) so they stay where they are.

## 2026-05-06 — MVP Polish Batch 1

- **Claude API auto-retry implemented** in `services/llm_parser.py` per spec §7. Single retry after a 3-second delay on `anthropic.APIError`; second failure surfaces as `LLMAPIError`.

- **Daily Claude API call counter persisted in Supabase** via new `claude_daily_usage` table and `increment_claude_daily_calls(p_date)` RPC. Replaces the in-memory `_daily_calls` / `_daily_reset_date` (which reset on container restart). MOCK_MODE branches to an in-memory counter — not because mock mode skips Supabase (it doesn't; contacts/invoices/storage are still real), but because no real Claude call is made under MOCK_MODE so the counter shouldn't record one, and existing tests drive the cap by poking `_daily_calls` directly.

- **Storage cleanup on `save_invoice` failure** — `services/invoice_service.py` now removes the orphaned PDF from Supabase Storage if the DB row insert fails. Invoice number stays burned (per spec §5); only the orphan storage object is removed.

- **`/healthz` endpoint** added via stdlib `http.server` running in a daemon thread (`src/health.py`). Avoids adding aiohttp/Tornado as a dependency. Configurable via `HEALTH_PORT` (default 8080). Response body is `{"status":"ok"}` only; `Server:` header value suppressed so the runtime version is not advertised. Deployment guide updated to drop the "no HTTP server needed" note.

- **Bot UX commands** added: `/help`, `/cancel`, `/contacts`. `/start` now lists known clients and an example dictation.

- **Non-text fallback handler** added: voice notes, photos, documents, etc. now get a reply explaining the bot only handles text and pointing to Wispr Flow for on-device dictation, instead of being silently dropped.

- **Confirmation card shows invoice + due dates** (`bot/formatting.py`). Invoice number is still claimed only on Confirm so it's not on the preview.

<!-- Add entries here as you build -->

---

## 2026-05-05 — Milestone 3: Bot Handlers + PDF + Email

- **`create_invoice` returns `(invoice_number, pdf_bytes)` tuple** instead of just `invoice_number`. The handler needs the bytes to deliver via Telegram immediately without re-downloading from Supabase storage.

- **`Session.computed_data` field added** alongside `parsed_data`. `parsed_data` always stores the LLMOutput-shaped dict (used as `previous_data` in correction LLM calls). `computed_data` stores the flat merged+computed dict (used for format_confirmation and PDF generation). Keeps the correction path schema-correct when the user taps Edit after a successful parse.

- **`weasyprint` imported lazily** inside `generate_pdf._sync()` rather than at module top level. WeasyPrint requires native Pango/GObject libraries (present in Docker, absent on macOS). Lazy import lets the test suite run on macOS without the system libraries.

- **Callback auth checks `query.from_user.id`** (the user who pressed the button) instead of `query.message.chat_id` (the chat the message lives in). These differ in group chats; auth must validate the actor, not the chat.

- **Resend attachment `content` uses `pdf_bytes` directly** (not `list(pdf_bytes)`). The Python SDK v2 accepts bytes; converting to a list of ints produces a malformed payload.

- **Email address not logged** in `email_sender.py`. Client email is PII; only `invoice_number` is logged per CLAUDE.md security rules.

---

## 2026-04-11 — Project initialized

- Established project structure per spec
- Chose single changelog over full ADR system — solo learning project, git log covers the rest
