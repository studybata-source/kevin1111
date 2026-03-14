from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants import QUALITY_LABELS


def welcome_shortcuts_keyboard(bot_username: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Settings",
                    callback_data="show:settings",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Group Setup",
                    callback_data="show:search_tips",
                ),
            ],
        ]
    )


def settings_keyboard(
    current_preset: str,
    current_format: str,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    quality_row: list[InlineKeyboardButton] = []
    for preset in ("best", "balanced", "small"):
        label = QUALITY_LABELS[preset]
        prefix = "Active: " if preset == current_preset else ""
        quality_row.append(
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=f"settings:quality:{preset}",
            )
        )

    return InlineKeyboardMarkup(inline_keyboard=[quality_row])


def search_results_keyboard(
    token: str,
    page: int,
    total_pages: int,
    page_count: int,
    start_index: int,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for offset in range(page_count):
        absolute_index = start_index + offset
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{absolute_index + 1}. Get Audio",
                    callback_data=f"search:download:{token}:{absolute_index}",
                ),
                InlineKeyboardButton(
                    text="Lyrics",
                    callback_data=f"search:lyrics:{token}:{absolute_index}",
                ),
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="Prev",
                callback_data=f"search:page:{token}:{page - 1}",
            )
        )
    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Next",
                callback_data=f"search:page:{token}:{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def download_actions_keyboard(
    query_token: str | None = None,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if query_token:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Lyrics",
                    callback_data=f"query:lyrics:{query_token}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lyrics_actions_keyboard(
    query_token: str | None = None,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup | None:
    if not query_token:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Get Audio",
                    callback_data=f"query:download:{query_token}",
                ),
            ]
        ]
    )
