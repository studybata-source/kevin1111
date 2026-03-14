from bot.constants import BUTTON_SETTINGS
from bot.keyboards.inline import settings_keyboard, welcome_shortcuts_keyboard
from bot.keyboards.reply import main_menu_keyboard


def test_main_menu_includes_settings_button() -> None:
    keyboard = main_menu_keyboard()
    button_texts = [button.text for row in keyboard.keyboard for button in row]

    assert BUTTON_SETTINGS in button_texts


def test_main_menu_hidden_outside_private_chat() -> None:
    assert main_menu_keyboard("supergroup") is None


def test_welcome_shortcuts_use_settings_label() -> None:
    keyboard = welcome_shortcuts_keyboard("kevin11musicbot")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "Settings" in labels
    assert "Group Setup" in labels
    assert "Audio Mode" not in labels


def test_welcome_shortcuts_do_not_show_group_add_buttons() -> None:
    keyboard = welcome_shortcuts_keyboard("kevin11musicbot")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "Add to Group" not in labels
    assert "Add as Admin" not in labels


def test_settings_keyboard_only_shows_quality_choices() -> None:
    keyboard = settings_keyboard("best", "mp3", "kevin11musicbot")
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert any(callback == "settings:quality:best" for callback in callbacks)
    assert all(not callback.startswith("settings:format:") for callback in callbacks if callback)
