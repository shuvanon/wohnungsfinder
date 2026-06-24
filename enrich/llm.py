"""
enrich/llm.py — LLM extraction layer.

The LLM here is a narrow *normalizer*, not a judge. Its only job is to recover
the unstructured signals the list view misses or gets wrong — most importantly
the true WBS requirement, which can be stated in the headline or detail-page
body even when the structured list table says "nicht erforderlich".

The structured fields it returns feed the existing rule-based hard filter and
priority scorer. No LLM decisions are made about pass/fail.

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

logger = logging.getLogger(__name__)

# Fields the model is asked to return. Anything it can't determine must be null.
_SCHEMA_FIELDS = (
    "wbs_required",        # bool   — true if a Wohnberechtigungsschein is needed
    "wbs_tier",           # string — e.g. "WBS 140", "140%-220%", or null
    "heizkosten",         # number — monthly heating cost in €, or null
    "deposit",            # number — Kaution in €, or null
    "energy_class",       # string — energy efficiency class A–H, or null
    "heating_type",       # string — e.g. "Fernwärme", "Gas", "Erdwärme", or null
    "pets_allowed",       # bool   — pets permitted, or null
    "description_summary",  # string — one-sentence summary, or null
)

_SYSTEM_PROMPT = (
    "You extract structured data from German apartment listings. "
    "You are given a listing title and the visible text of its detail page. "
    "Return ONLY a JSON object with exactly these keys: "
    + ", ".join(_SCHEMA_FIELDS) + ". "
    "Use null for any value you cannot determine from the provided text — never guess. "
    "For wbs_required: return true if the listing requires a Wohnberechtigungsschein "
    "(look for 'WBS', 'Wohnberechtigungsschein', 'WBS erforderlich', income-limit / "
    "'einkommensorientierte Vermietung' wording), false if it explicitly does not, "
    "null if unclear. heizkosten and deposit are numbers in euros (no currency symbol). "
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

        # Keep only known keys with non-null values.
        return {k: data[k] for k in _SCHEMA_FIELDS if data.get(k) is not None}

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
