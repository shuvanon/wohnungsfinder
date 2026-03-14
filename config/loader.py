"""
config/loader.py — Central config loader.

Loads settings.json once and validates that required keys are present.
Import this instead of doing raw json.load() anywhere in the codebase.

Usage:
    from config.loader import load_config
    cfg = load_config()
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "settings.json"

# Keys that must exist at the top level of settings.json
_REQUIRED_KEYS = ["telegram", "hard_filters", "priority_scoring", "scraper"]


def load_config(path: Path = _CONFIG_PATH) -> dict:
    """
    Load and return the settings dict.

    Raises:
        FileNotFoundError  — if settings.json doesn't exist
        ValueError         — if required top-level keys are missing
        json.JSONDecodeError — if the file is not valid JSON
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Copy config/settings.json.example to config/settings.json and fill in your values."
        )

    with open(path) as f:
        cfg = json.load(f)

    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"settings.json is missing required keys: {missing}")

    logger.debug(f"Config loaded from {path}")
    return cfg
