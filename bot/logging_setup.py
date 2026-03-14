from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


class TelegramLogHandler(logging.Handler):
    def __init__(self, bot_token: str, chat_id: int, level: int) -> None:
        super().__init__(level=level)
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.dumps(
                {
                    "chat_id": self._chat_id,
                    "text": self.format(record)[:3900],
                    "disable_web_page_preview": True,
                }
            ).encode("utf-8")
            request = Request(
                self._url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=6):
                return
        except (OSError, URLError, ValueError):
            return


def configure_logging(
    level: str,
    *,
    log_to_file: bool = False,
    bot_token: str | None = None,
    ops_chat_id: int | None = None,
    ops_alert_level: str = "ERROR",
) -> None:
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_to_file:
        log_path = Path("data") / "bot.runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        handlers.append(file_handler)

    if bot_token and ops_chat_id:
        telegram_level = getattr(logging, ops_alert_level.upper(), logging.ERROR)
        handlers.append(TelegramLogHandler(bot_token=bot_token, chat_id=ops_chat_id, level=telegram_level))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(resolved_level)

    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
