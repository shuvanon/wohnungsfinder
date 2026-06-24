"""
tests/test_llm.py — Tests for enrich/llm.py

Mocks the OpenAI-compatible HTTP endpoint so no real LLM server is needed.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from enrich.llm import LLMExtractor, _parse_json_object

_CFG = {
    "enabled": True,
    "base_url": "http://localhost:8000/v1",
    "model": "gemma-2-2b-it",
    "api_key_env": "",
    "timeout": 10,
    "max_detail_chars": 8000,
}

_LISTING = {"url": "https://example.de/x", "title": "Wohnung mit WBS"}


def _chat_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


class TestDisabled(unittest.TestCase):

    def test_disabled_config_returns_empty(self):
        ext = LLMExtractor({**_CFG, "enabled": False})
        self.assertFalse(ext.enabled)
        self.assertEqual(ext.extract(_LISTING, "some text"), {})

    def test_none_config_returns_empty(self):
        ext = LLMExtractor(None)
        self.assertFalse(ext.enabled)
        self.assertEqual(ext.extract(_LISTING, "some text"), {})

    def test_missing_base_url_disables(self):
        ext = LLMExtractor({**_CFG, "base_url": ""})
        self.assertFalse(ext.enabled)

    def test_missing_model_disables(self):
        ext = LLMExtractor({**_CFG, "model": ""})
        self.assertFalse(ext.enabled)


class TestExtract(unittest.TestCase):

    @patch("enrich.llm.requests.post")
    def test_parses_fields(self, mock_post):
        payload = {
            "wbs_required": True,
            "wbs_tier": "WBS 140",
            "heizkosten": 60.72,
            "deposit": 1407.81,
            "energy_class": "C",
            "heating_type": "Fernwärme",
            "pets_allowed": None,
            "description_summary": "Helle 2-Zimmer-Wohnung in Lichtenberg.",
        }
        mock_post.return_value = _chat_response(json.dumps(payload))
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertTrue(result["wbs_required"])
        self.assertEqual(result["wbs_tier"], "WBS 140")
        self.assertEqual(result["energy_class"], "C")

    @patch("enrich.llm.requests.post")
    def test_drops_null_fields(self, mock_post):
        payload = {k: None for k in (
            "wbs_required", "wbs_tier", "heizkosten", "deposit",
            "energy_class", "heating_type", "pets_allowed", "description_summary",
        )}
        payload["wbs_required"] = True
        mock_post.return_value = _chat_response(json.dumps(payload))
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"wbs_required": True})

    @patch("enrich.llm.requests.post")
    def test_ignores_unknown_keys(self, mock_post):
        mock_post.return_value = _chat_response(
            json.dumps({"wbs_required": False, "made_up_key": "x"})
        )
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"wbs_required": False})

    @patch("enrich.llm.requests.post")
    def test_handles_json_wrapped_in_prose(self, mock_post):
        mock_post.return_value = _chat_response(
            'Here is the data:\n```json\n{"energy_class": "B"}\n```'
        )
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"energy_class": "B"})

    @patch("enrich.llm.requests.post")
    def test_unparseable_returns_empty(self, mock_post):
        mock_post.return_value = _chat_response("not json at all")
        self.assertEqual(LLMExtractor(_CFG).extract(_LISTING, "detail text"), {})

    @patch("enrich.llm.requests.post")
    def test_http_failure_returns_empty(self, mock_post):
        mock_post.side_effect = Exception("connection refused")
        self.assertEqual(LLMExtractor(_CFG).extract(_LISTING, "detail text"), {})

    def test_empty_detail_text_skips_call(self):
        # No HTTP mock — if a call were made it would raise (no server).
        self.assertEqual(LLMExtractor(_CFG).extract(_LISTING, ""), {})

    @patch.dict("os.environ", {"MY_LLM_KEY": "secret-123"})
    @patch("enrich.llm.requests.post")
    def test_api_key_sent_as_bearer(self, mock_post):
        mock_post.return_value = _chat_response('{"energy_class": "A"}')
        ext = LLMExtractor({**_CFG, "api_key_env": "MY_LLM_KEY"})
        ext.extract(_LISTING, "detail text")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-123")


class TestParseJsonObject(unittest.TestCase):

    def test_plain_object(self):
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})

    def test_none_on_empty(self):
        self.assertIsNone(_parse_json_object(""))

    def test_none_on_non_object(self):
        self.assertIsNone(_parse_json_object("[1, 2, 3]"))


if __name__ == "__main__":
    unittest.main()
