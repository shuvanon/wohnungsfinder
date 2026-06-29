"""
enrich/llm.py — LLM extraction layer.

The detail page is the source of truth. The list view is often partially or
totally wrong (e.g. a total rent shown as 600 € that is really 1100 €, or a
WBS requirement the table hides). So when we open the detail page, the LLM
re-extracts the *whole datasheet* from it and those values overwrite the list
values; the list value is only kept for fields the LLM cannot determine.

The LLM is still a normalizer, not a judge — it only fills fields. The
rule-based hard filter and priority scorer then decide pass/fail on the
corrected datasheet.

Backend is any OpenAI-compatible chat endpoint (a self-hosted server, Ollama,
or a cheap cloud API) — configured entirely via the `llm` section of
settings.json. Implemented with plain `requests`; no SDK dependency.

Public interface:
    extractor = LLMExtractor(cfg["llm"])
    fields = extractor.extract(listing, detail_text)   # {} if disabled/failed
"""

import json
import logging
import os
import re

import requests

from scraper.parser import _parse_german_float

logger = logging.getLogger(__name__)

# The detail page is authoritative for these. Fields are grouped by the
# coercion applied to the model's raw output; anything the model can't
# determine must be null and is dropped (so the list value is kept on merge).
_NUMBER_FIELDS = (
    "total_rent",   # number — Warmmiete / Gesamtmiete in €
    "cold_rent",    # number — Nettokaltmiete in €
    "rooms",        # number — number of rooms
    "size_m2",      # number — living area in m²
    "heizkosten",   # number — monthly heating cost in €
    "deposit",      # number — Kaution in €
)
_INT_FIELDS = (
    "year_built",   # int    — year of construction
)
_BOOL_FIELDS = (
    "pets_allowed",  # bool   — pets permitted
)
_LIST_FIELDS = (
    "features",     # list   — short German feature names (Balkon, Aufzug, …)
)
_TEXT_FIELDS = (
    "wbs",          # string — "erforderlich" or "nicht erforderlich"
    "wbs_tier",     # string — e.g. "WBS 140", "140%-220%"
    "available",    # string — availability date / text (Bezugsfrei ab)
    "energy_class",  # string — energy efficiency class A–H
    "heating_type",  # string — e.g. "Fernwärme", "Gas", "Erdwärme"
    "description_summary",  # string — one-sentence summary
)
_SCHEMA_FIELDS = (
    _NUMBER_FIELDS + _INT_FIELDS + _BOOL_FIELDS + _LIST_FIELDS + _TEXT_FIELDS
)

_SYSTEM_PROMPT = (
    "You extract structured data from German apartment listings. "
    "You are given a listing title and the visible text of its detail page. "
    "Return ONLY a JSON object with exactly these keys: "
    + ", ".join(_SCHEMA_FIELDS) + ". "
    "Base every value on the detail page text, not the title. "
    "Use null for any value you cannot determine from the text — never guess. "
    "Numbers (total_rent, cold_rent, rooms, size_m2, heizkosten, deposit, "
    "year_built) must be plain JSON numbers, with no currency symbol and no "
    "thousands separators (e.g. 1100.5, not \"1.100,50 €\"). "
    "total_rent is the Warmmiete/Gesamtmiete; cold_rent is the Nettokaltmiete. "
    "wbs is \"erforderlich\" if a Wohnberechtigungsschein is required (look for "
    "'WBS', 'Wohnberechtigungsschein', income-limit / 'einkommensorientierte "
    "Vermietung' wording), otherwise \"nicht erforderlich\". "
    "features is a JSON array of short German feature names (e.g. Balkon, "
    "Aufzug, Einbauküche, Keller). "
    "Respond with the JSON object and nothing else."
)


class LLMExtractor:
    """
    Extracts normalized fields from a listing's detail text via an
    OpenAI-compatible chat endpoint.

    Instantiate once with the `llm` section of settings.json. If the section
    is missing or `enabled` is false, the extractor is inert and extract()
    always returns {} — the pipeline then runs on list-view data alone.
    """

    def __init__(self, config: dict | None):
        cfg = config or {}
        self.enabled: bool = cfg.get("enabled", False)
        self.base_url: str = cfg.get("base_url", "").rstrip("/")
        self.model: str = cfg.get("model", "")
        self.timeout: int = cfg.get("timeout", 60)
        self.max_detail_chars: int = cfg.get("max_detail_chars", 8000)
        # Cap generation. The extraction JSON is ~15 small fields, so this is
        # ample; it exists to bound the worst case — an uncapped model can run
        # away and generate until it fills the context, blowing the timeout.
        self.max_tokens: int = cfg.get("max_tokens", 512)

        api_key_env = cfg.get("api_key_env", "LLM_API_KEY")
        self.api_key: str = os.environ.get(api_key_env, "") if api_key_env else ""

        if self.enabled and not (self.base_url and self.model):
            logger.warning(
                "LLM enrichment enabled but base_url/model not set — disabling"
            )
            self.enabled = False

    def extract(self, listing: dict, detail_text: str) -> dict:
        """
        Return a dict of normalized fields for this listing, or {} on
        failure / when disabled. Only keys the model populated (non-null)
        are returned, so callers can safely dict.update() over list data.
        """
        if not self.enabled:
            return {}
        if not detail_text:
            return {}

        text = detail_text[: self.max_detail_chars]
        user_content = json.dumps(
            {"title": listing.get("title", ""), "detail_text": text},
            ensure_ascii=False,
        )

        try:
            raw = self._chat(user_content)
        except Exception as e:
            logger.warning(f"LLM call failed for {listing.get('url')}: {e}")
            return {}

        data = _parse_json_object(raw)
        if data is None:
            logger.warning(f"LLM returned unparseable JSON for {listing.get('url')}")
            return {}

        # Coerce each known field; drop anything that comes back null/unusable
        # so the caller's dict.update() keeps the list value for that field.
        result = {}
        for field in _SCHEMA_FIELDS:
            if data.get(field) is None:
                continue
            coerced = _coerce(field, data[field])
            if coerced is not None:
                result[field] = coerced
        return result

    # ── Internals ────────────────────────────────────────────────────────────

    def _chat(self, user_content: str) -> str:
        """POST one chat-completion request and return the message content."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["choices"][0]["message"]["content"]


def _coerce(field: str, value):
    """
    Normalize one raw model value into the type the datasheet expects.
    Returns None when the value can't be used (so the list value is kept).
    """
    if field in _NUMBER_FIELDS:
        return _to_number(value)

    if field in _INT_FIELDS:
        num = _to_number(value)
        return int(num) if num is not None else None

    if field in _BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "ja", "1")
        return None

    if field in _LIST_FIELDS:
        if isinstance(value, list):
            items = [str(x).strip() for x in value if str(x).strip()]
            return items or None
        return None

    if field == "wbs":
        return _normalize_wbs(value)

    # Remaining text fields.
    text = str(value).strip()
    return text or None


def _to_number(value):
    """Coerce a JSON number or German-formatted numeric string to float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _parse_german_float(value)
    return None


def _normalize_wbs(value) -> str | None:
    """Map a free-form WBS string to the canonical filter values."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if any(neg in s for neg in ("nicht", "kein", "ohne", "no ", "not ")):
        return "nicht erforderlich"
    if "erforderlich" in s or "wbs" in s or "berechtigung" in s or s in ("true", "ja", "yes"):
        return "erforderlich"
    return None


def _parse_json_object(raw: str):
    """
    Parse a JSON object from a model response. Tolerates a stray code fence or
    surrounding prose by falling back to the first {...} span. Returns the dict
    or None.
    """
    if not raw:
        return None
    raw = raw.strip()
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        result = json.loads(match.group(0))
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None
