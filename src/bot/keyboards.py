from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_keyboard(has_email: bool) -> InlineKeyboardMarkup:
    """Single-step confirm + delivery selection.

    has_email=True: row 1 picks delivery method (email always implies a Telegram
    copy too); row 2 has Edit/Cancel.
    has_email=False: a single Confirm tap delivers via Telegram; no email choice
    is presented.
    """
    if has_email:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm + Email", callback_data="confirm_email"),
                InlineKeyboardButton("Confirm (Telegram)", callback_data="confirm_telegram"),
            ],
            [
                InlineKeyboardButton("Edit", callback_data="edit"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ],
        ])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data="confirm"),
        InlineKeyboardButton("Edit", callback_data="edit"),
        InlineKeyboardButton("Cancel", callback_data="cancel"),
    ]])


def contact_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirm/Cancel buttons for the /contacts add summary step."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data="contact_confirm"),
        InlineKeyboardButton("Cancel", callback_data="contact_cancel"),
    ]])


def contact_delete_confirm_keyboard(client_id: str) -> InlineKeyboardMarkup:
    """Confirm/Cancel buttons for /contacts delete. The client_id is embedded
    in the Delete callback data so the handler can verify against the session
    target (stale callbacks are ignored)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Delete", callback_data=f"contact_delete_confirm:{client_id}"),
        InlineKeyboardButton("Cancel", callback_data="contact_delete_cancel"),
    ]])


def pick_client_keyboard(contacts: list) -> InlineKeyboardMarkup:
    """One button per known contact for the "Did you mean X?" prompt.

    Callback data format: ``pick_client:<client_id>``. The trailing
    ``pick_client:__none__`` button lets the user dismiss the prompt and
    re-state the invoice from scratch.
    """
    buttons = [
        [InlineKeyboardButton(
            f"{c.display_name} ({c.client_id})",
            callback_data=f"pick_client:{c.client_id}",
        )]
        for c in contacts
    ]
    buttons.append([
        InlineKeyboardButton("None of these", callback_data="pick_client:__none__"),
    ])
    return InlineKeyboardMarkup(buttons)


def contact_field_picker_keyboard() -> InlineKeyboardMarkup:
    """Field picker for /contacts edit. One button per editable field, plus Done.

    `client_id` is intentionally omitted — it's the primary key. To rename a
    contact, the user must delete and re-add. The email button is always shown
    so the user can ADD an email if one is missing.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Display name", callback_data="contact_edit_field:display_name"),
            InlineKeyboardButton("Address", callback_data="contact_edit_field:address"),
        ],
        [
            InlineKeyboardButton("Contact person", callback_data="contact_edit_field:contact_person"),
            InlineKeyboardButton("Email", callback_data="contact_edit_field:email"),
        ],
        [
            InlineKeyboardButton(
                "Default description",
                callback_data="contact_edit_field:default_description",
            ),
            InlineKeyboardButton(
                "Default service",
                callback_data="contact_edit_field:default_service_description",
            ),
        ],
        [
            InlineKeyboardButton(
                "Default rate", callback_data="contact_edit_field:default_rate"
            ),
        ],
        [
            InlineKeyboardButton("Aliases", callback_data="contact_edit_field:aliases"),
        ],
        [
            InlineKeyboardButton("Done", callback_data="contact_edit_done"),
        ],
    ])
