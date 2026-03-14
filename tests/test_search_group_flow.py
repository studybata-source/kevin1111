from types import SimpleNamespace

from bot.handlers.search import _extract_group_query, _is_reply_to_bot


def _message(text: str, *, reply_from_user: object | None = None, bot_id: int = 9001) -> SimpleNamespace:
    reply = None
    if reply_from_user is not None:
        reply = SimpleNamespace(from_user=reply_from_user)
    return SimpleNamespace(
        text=text,
        reply_to_message=reply,
        bot=SimpleNamespace(id=bot_id),
    )


def test_extract_group_query_from_mention() -> None:
    message = _message("@kevin11musicbot Coldplay Yellow")

    assert _extract_group_query(message, message.text, "kevin11musicbot") == "Coldplay Yellow"


def test_extract_group_query_from_mention_with_punctuation() -> None:
    message = _message("@kevin11musicbot, Coldplay Yellow")

    assert _extract_group_query(message, message.text, "kevin11musicbot") == "Coldplay Yellow"


def test_extract_group_query_from_reply_to_bot() -> None:
    message = _message(
        "Coldplay Yellow",
        reply_from_user=SimpleNamespace(is_bot=True, id=9001),
    )

    assert _is_reply_to_bot(message) is True
    assert _extract_group_query(message, message.text, "kevin11musicbot") == "Coldplay Yellow"


def test_extract_group_query_ignores_non_trigger_text() -> None:
    message = _message("Coldplay Yellow")

    assert _is_reply_to_bot(message) is False
    assert _extract_group_query(message, message.text, "kevin11musicbot") is None
