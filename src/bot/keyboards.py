from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm", callback_data="confirm"),
            InlineKeyboardButton("Edit", callback_data="edit"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ]
    ])


def delivery_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Email", callback_data="deliver_email"),
            InlineKeyboardButton("Download in Telegram", callback_data="deliver_telegram"),
        ]
    ])
