from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.constants import (
    BUTTON_DOWNLOAD,
    BUTTON_HELP,
    BUTTON_HISTORY,
    BUTTON_LYRICS,
    BUTTON_SEARCH,
    BUTTON_SETTINGS,
)


def main_menu_keyboard(chat_type: str | None = "private") -> ReplyKeyboardMarkup | None:
    if chat_type != "private":
        return None
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BUTTON_SEARCH),
                KeyboardButton(text=BUTTON_DOWNLOAD),
                KeyboardButton(text=BUTTON_LYRICS),
            ],
            [
                KeyboardButton(text=BUTTON_SETTINGS),
                KeyboardButton(text=BUTTON_HISTORY),
                KeyboardButton(text=BUTTON_HELP),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Drop a song name or paste a link",
    )
