"""
notifier/telegram.py — Telegram notification delivery.

Supports sending to one or multiple recipients. In settings.json,
chat_ids accepts either a single string or a list of strings:

    "chat_ids": "123456789"                          # one person
    "chat_ids": ["123456789", "987654321"]           # two people

A failure delivering to one recipient is logged but does not prevent
delivery to the others, and never crashes the main loop.
"""

import logging
import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Sends HTML-formatted messages to one or more Telegram chats.

    Usage:
        notifier = TelegramNotifier(bot_token="...", chat_ids=["123", "456"])
        notifier.send("Hello <b>world</b>")
    """

    def __init__(self, bot_token: str, chat_ids: list[str] | str, timeout: int = 15):
        if bot_token == "YOUR_BOT_TOKEN_HERE":
            raise ValueError(
                "Telegram bot_token is not configured. "
                "Edit config/settings.json and set your bot token."
            )

        # Accept both a bare string and a list for flexibility
        if isinstance(chat_ids, str):
            self._chat_ids = [chat_ids]
        else:
            self._chat_ids = list(chat_ids)

        if not self._chat_ids:
            raise ValueError("At least one chat_id must be provided in chat_ids.")

        self._url     = _API_BASE.format(token=bot_token)
        self._timeout = timeout
        logger.info(f"TelegramNotifier ready — {len(self._chat_ids)} recipient(s)")

    def send(self, text: str) -> bool:
        """
        Send `text` to all configured recipients.

        Attempts delivery to every chat_id regardless of individual failures.
        Returns True only if all deliveries succeeded.
        """
        results = [self._send_one(chat_id, text) for chat_id in self._chat_ids]
        return all(results)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _send_one(self, chat_id: str, text: str) -> bool:
        """Deliver one message to one chat_id. Logs but never raises on failure."""
        payload = {
            "chat_id":                  chat_id,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(self._url, json=payload, timeout=self._timeout)
            if resp.ok:
                logger.debug(f"Message delivered to chat_id {chat_id}")
                return True
            else:
                logger.error(
                    f"Telegram API error for chat_id {chat_id}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
                return False
        except requests.RequestException as e:
            logger.error(f"Telegram request failed for chat_id {chat_id}: {e}")
            return False
