"""
tests/test_telegram.py — Tests for notifier/telegram.py

Uses unittest.mock to simulate Telegram API responses so no real HTTP
requests are made and no valid token is needed.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

from notifier.telegram import TelegramNotifier


def _notifier(chat_ids=None) -> TelegramNotifier:
    if chat_ids is None:
        chat_ids = ["111", "222"]
    return TelegramNotifier(bot_token="valid-token-123", chat_ids=chat_ids)


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    return resp


def _err_response(status_code=400, text="Bad Request") -> MagicMock:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status_code
    resp.text = text
    return resp


class TestInit(unittest.TestCase):

    def test_raises_on_placeholder_token(self):
        with self.assertRaises(ValueError):
            TelegramNotifier(bot_token="YOUR_BOT_TOKEN_HERE", chat_ids=["123"])

    def test_raises_on_empty_chat_ids(self):
        with self.assertRaises(ValueError):
            TelegramNotifier(bot_token="valid-token", chat_ids=[])

    def test_single_string_chat_id_accepted(self):
        """Backwards-compatible: a bare string is wrapped in a list."""
        n = TelegramNotifier(bot_token="valid-token", chat_ids="123456")
        self.assertEqual(n._chat_ids, ["123456"])

    def test_list_chat_ids_accepted(self):
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111", "222"])
        self.assertEqual(n._chat_ids, ["111", "222"])

    def test_recipient_count_logged(self):
        # No assertion needed — just verify it doesn't crash with multiple IDs
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111", "222", "333"])
        self.assertEqual(len(n._chat_ids), 3)


class TestSendSingleRecipient(unittest.TestCase):

    @patch("notifier.telegram.requests.post")
    def test_sends_to_one_recipient(self, mock_post):
        mock_post.return_value = _ok_response()
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        result = n.send("hello")
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("notifier.telegram.requests.post")
    def test_payload_contains_chat_id(self, mock_post):
        mock_post.return_value = _ok_response()
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["999"])
        n.send("test message")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "999")

    @patch("notifier.telegram.requests.post")
    def test_payload_contains_text(self, mock_post):
        mock_post.return_value = _ok_response()
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        n.send("my listing message")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["text"], "my listing message")

    @patch("notifier.telegram.requests.post")
    def test_html_parse_mode_set(self, mock_post):
        mock_post.return_value = _ok_response()
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        n.send("<b>bold</b>")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parse_mode"], "HTML")

    @patch("notifier.telegram.requests.post")
    def test_returns_false_on_api_error(self, mock_post):
        mock_post.return_value = _err_response(400, "Bad Request")
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        result = n.send("test")
        self.assertFalse(result)

    @patch("notifier.telegram.requests.post")
    def test_returns_false_on_network_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.RequestException("connection refused")
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        result = n.send("test")
        self.assertFalse(result)

    @patch("notifier.telegram.requests.post")
    def test_network_error_does_not_raise(self, mock_post):
        import requests as req
        mock_post.side_effect = req.RequestException("timeout")
        n = TelegramNotifier(bot_token="valid-token", chat_ids=["111"])
        # Must not raise — scraper loop must continue
        try:
            n.send("test")
        except Exception as e:
            self.fail(f"send() raised unexpectedly: {e}")


class TestSendMultipleRecipients(unittest.TestCase):

    @patch("notifier.telegram.requests.post")
    def test_sends_to_all_recipients(self, mock_post):
        mock_post.return_value = _ok_response()
        n = _notifier(["111", "222", "333"])
        n.send("hello everyone")
        self.assertEqual(mock_post.call_count, 3)

    @patch("notifier.telegram.requests.post")
    def test_each_recipient_gets_correct_chat_id(self, mock_post):
        mock_post.return_value = _ok_response()
        n = _notifier(["111", "222"])
        n.send("test")
        sent_chat_ids = [
            c.kwargs["json"]["chat_id"] for c in mock_post.call_args_list
        ]
        self.assertIn("111", sent_chat_ids)
        self.assertIn("222", sent_chat_ids)

    @patch("notifier.telegram.requests.post")
    def test_returns_true_when_all_succeed(self, mock_post):
        mock_post.return_value = _ok_response()
        result = _notifier(["111", "222"]).send("test")
        self.assertTrue(result)

    @patch("notifier.telegram.requests.post")
    def test_returns_false_when_one_fails(self, mock_post):
        """One failure → False, but the other recipient still gets the message."""
        mock_post.side_effect = [_ok_response(), _err_response()]
        result = _notifier(["111", "222"]).send("test")
        self.assertFalse(result)
        # Both were still attempted
        self.assertEqual(mock_post.call_count, 2)

    @patch("notifier.telegram.requests.post")
    def test_second_recipient_still_notified_after_first_fails(self, mock_post):
        """A failure on recipient 1 must not skip recipient 2."""
        import requests as req
        mock_post.side_effect = [req.RequestException("timeout"), _ok_response()]
        n = _notifier(["111", "222"])
        n.send("important listing")
        # Second call must have happened with chat_id 222
        second_call_payload = mock_post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_call_payload["chat_id"], "222")

    @patch("notifier.telegram.requests.post")
    def test_all_failures_returns_false(self, mock_post):
        mock_post.return_value = _err_response()
        result = _notifier(["111", "222"]).send("test")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
