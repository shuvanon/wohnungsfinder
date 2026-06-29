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

from enrich.llm import (
    LLMExtractor,
    _coerce,
    _normalize_wbs,
    _parse_json_object,
    _to_number,
)

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
    def test_parses_full_datasheet(self, mock_post):
        payload = {
            "total_rent": 1100.5,
            "cold_rent": "574,39",     # German string → 574.39
            "rooms": 2,                 # int → float
            "size_m2": 51.03,
            "wbs": "WBS erforderlich",  # → "erforderlich"
            "year_built": 1930,
            "available": "sofort",
            "features": ["Balkon", "Aufzug"],
            "heizkosten": 60.72,
            "deposit": 1407.81,
            "energy_class": "C",
            "heating_type": "Fernwärme",
            "pets_allowed": True,
            "wbs_tier": "WBS 140",
            "description_summary": "Helle Wohnung.",
        }
        mock_post.return_value = _chat_response(json.dumps(payload))
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")

        self.assertEqual(result["total_rent"], 1100.5)
        self.assertEqual(result["cold_rent"], 574.39)
        self.assertEqual(result["rooms"], 2.0)
        self.assertEqual(result["wbs"], "erforderlich")
        self.assertEqual(result["year_built"], 1930)
        self.assertIsInstance(result["year_built"], int)
        self.assertEqual(result["features"], ["Balkon", "Aufzug"])
        self.assertIs(result["pets_allowed"], True)

    @patch("enrich.llm.requests.post")
    def test_drops_null_fields(self, mock_post):
        mock_post.return_value = _chat_response(
            json.dumps({"wbs": "erforderlich", "energy_class": None, "rooms": None})
        )
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"wbs": "erforderlich"})

    @patch("enrich.llm.requests.post")
    def test_ignores_unknown_keys(self, mock_post):
        mock_post.return_value = _chat_response(
            json.dumps({"wbs": "nicht erforderlich", "made_up_key": "x"})
        )
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"wbs": "nicht erforderlich"})

    @patch("enrich.llm.requests.post")
    def test_drops_uncoercible_number(self, mock_post):
        mock_post.return_value = _chat_response(
            json.dumps({"total_rent": "n/a", "energy_class": "B"})
        )
        result = LLMExtractor(_CFG).extract(_LISTING, "detail text")
        self.assertEqual(result, {"energy_class": "B"})

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

    @patch("enrich.llm.requests.post")
    def test_max_tokens_capped_in_payload(self, mock_post):
        mock_post.return_value = _chat_response('{"energy_class": "A"}')
        LLMExtractor({**_CFG, "max_tokens": 256}).extract(_LISTING, "detail text")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["max_tokens"], 256)

    @patch("enrich.llm.requests.post")
    def test_max_tokens_defaults_to_512(self, mock_post):
        mock_post.return_value = _chat_response('{"energy_class": "A"}')
        LLMExtractor(_CFG).extract(_LISTING, "detail text")  # no max_tokens in cfg
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["max_tokens"], 512)


class TestCoercion(unittest.TestCase):

    def test_to_number_from_float(self):
        self.assertEqual(_to_number(1100.5), 1100.5)

    def test_to_number_from_german_string(self):
        self.assertEqual(_to_number("1.100,50"), 1100.5)
        self.assertEqual(_to_number("574,39"), 574.39)

    def test_to_number_rejects_bool_and_garbage(self):
        self.assertIsNone(_to_number(True))
        self.assertIsNone(_to_number("n/a"))

    def test_normalize_wbs(self):
        self.assertEqual(_normalize_wbs("nicht erforderlich"), "nicht erforderlich")
        self.assertEqual(_normalize_wbs("WBS erforderlich"), "erforderlich")
        self.assertEqual(_normalize_wbs("Wohnberechtigungsschein erforderlich"), "erforderlich")
        self.assertEqual(_normalize_wbs("kein WBS nötig"), "nicht erforderlich")
        self.assertIsNone(_normalize_wbs(""))
        self.assertIsNone(_normalize_wbs(None))

    def test_coerce_rooms_to_float(self):
        self.assertEqual(_coerce("rooms", 2), 2.0)

    def test_coerce_year_to_int(self):
        self.assertEqual(_coerce("year_built", "1930"), 1930)

    def test_coerce_features_list(self):
        self.assertEqual(_coerce("features", ["Balkon", " "]), ["Balkon"])
        self.assertIsNone(_coerce("features", "Balkon"))  # not a list

    def test_coerce_pets_from_string(self):
        self.assertIs(_coerce("pets_allowed", "ja"), True)
        self.assertIs(_coerce("pets_allowed", "nein"), False)


class TestParseJsonObject(unittest.TestCase):

    def test_plain_object(self):
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})

    def test_none_on_empty(self):
        self.assertIsNone(_parse_json_object(""))

    def test_none_on_non_object(self):
        self.assertIsNone(_parse_json_object("[1, 2, 3]"))


if __name__ == "__main__":
    unittest.main()
