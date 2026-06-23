"""
priority.py — Priority scoring.

Every listing that passes the hard filter is scored against a set of
user-defined rules.  The total score determines a priority label:

    🔴 HIGH    — score >= high threshold   (act immediately)
    🟡 MEDIUM  — score >= medium threshold (worth a look)
    ⚪ LOW     — everything else           (for completeness)

Rules are data-driven via config/settings.json.  Each rule specifies:
    - field:    which listing key to evaluate
    - points:   awarded when the rule matches
    - One of:
        match:    exact substring match (case-insensitive)
        contains: substring search across the field + raw_text
        min/max:  numeric range (inclusive, either bound optional)
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PriorityResult:
    label:   str        # "🔴 HIGH" / "🟡 MEDIUM" / "⚪ LOW"
    score:   int
    reasons: list[str] = field(default_factory=list)


class PriorityScorer:
    """
    Scores a listing and returns a PriorityResult.

    Instantiate once with the priority_scoring section of settings.json.
    """

    def __init__(self, config: dict):
        self._rules      = config.get("rules", [])
        self._thresholds = config.get("thresholds", {"high": 50, "medium": 25})

    def score(self, listing: dict) -> PriorityResult:
        total   = 0
        reasons = []

        for rule in self._rules:
            pts    = rule.get("points", 0)
            field_name  = rule.get("field", "")
            value  = listing.get(field_name)

            matched = False

            if "match" in rule:
                matched = self._match_string(value, rule["match"])

            elif "contains" in rule:
                matched = rule["contains"].lower() in str(value or "").lower()

            elif "min" in rule or "max" in rule:
                matched = self._match_range(value, rule.get("min"), rule.get("max"))

            if matched:
                total += pts
                reasons.append(f"{rule['name']} (+{pts})")
                logger.debug(f"Rule matched: '{rule['name']}' (+{pts})")

        label = self._label(total)
        return PriorityResult(label=label, score=total, reasons=reasons)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _label(self, score: int) -> str:
        if score >= self._thresholds.get("high", 50):
            return "🔴 HIGH"
        if score >= self._thresholds.get("medium", 25):
            return "🟡 MEDIUM"
        return "⚪ LOW"

    @staticmethod
    def _match_string(value, pattern: str) -> bool:
        if value is None:
            return False
        return pattern.lower() in str(value).lower()

    @staticmethod
    def _match_range(value, lo, hi) -> bool:
        if value is None:
            return False
        try:
            v = float(value)
            if lo is not None and v < lo:
                return False
            if hi is not None and v > hi:
                return False
            return True
        except (TypeError, ValueError):
            return False
