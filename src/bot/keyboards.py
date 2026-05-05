from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm", callback_data="confirm"),
            InlineKeyboardButton("Edit", callback_data="edit"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]
    ])


def delivery_keyboard(has_email: bool) -> InlineKeyboardMarkup:
    if not has_email:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("Download in Telegram", callback_data="deliver_telegram"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Email", callback_data="deliver_email"),
        InlineKeyboardButton("Download in Telegram", callback_data="deliver_telegram"),
        InlineKeyboardButton("Both", callback_data="deliver_both"),
    ]])
