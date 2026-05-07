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
