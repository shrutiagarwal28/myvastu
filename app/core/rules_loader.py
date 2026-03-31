import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the rules file — relative to the project root, not this file's location.
# Using Path() instead of a raw string so this works correctly on both macOS and Windows
# and makes it easy to construct relative paths without string manipulation.
RULES_FILE_PATH = Path("vastu-rules.json")

'''
What we're building and why:
This module has one job: load vastu-rules.json from disk and return a validated list of rule objects. It's the bridge between the config file and the rest of the application.

Why a dedicated loader instead of json.load() inline?
If you wrote json.load(open("vastu-rules.json")) directly in the service or route, you'd have no validation (a malformed JSON rule would cause a cryptic error deep inside 
the analyzer), no single source of truth for the file path, and no reusability. A dedicated loader validates the structure once at startup and fails loudly if anything is wrong.

Design pattern: Single Responsibility Principle. This module knows about JSON loading and validation. The service layer knows about AI analysis. Neither knows about the other's concerns.
'''

def _validate_rule(rule: dict[str, Any], index: int) -> None:
    """
    Validate that a single rule object has all required fields with non-empty values.

    Raises ValueError with a descriptive message if validation fails.
    This is called at startup so malformed rules fail loudly before any request is served.
    """
    required_fields = ["id", "name", "description", "weightage", "what_to_look_for", "ideal", "avoid"]

    for field in required_fields:
        if field not in rule:
            raise ValueError(f"Rule at index {index} is missing required field: '{field}'")
        if field == "weightage":
            if not isinstance(rule[field], (int, float)):
                raise ValueError(f"Rule '{rule.get('id', index)}': 'weightage' must be a number, got {type(rule[field])}")
        else:
            if not isinstance(rule[field], str) or not rule[field].strip():
                raise ValueError(f"Rule '{rule.get('id', index)}': '{field}' must be a non-empty string")


def _validate_total_weightage(rules: list[dict[str, Any]]) -> None:
    """
    Validate that all rule weightages sum to exactly 100.

    This is a business logic constraint: the final Vastu score is out of 100,
    so the weightages must add up to 100 for the math to work correctly.
    """
    total = sum(rule["weightage"] for rule in rules)
    if total != 100:
        raise ValueError(
            f"Rule weightages must sum to 100 for scoring to work correctly. "
            f"Current total: {total}"
        )


@lru_cache
def load_vastu_rules() -> list[dict[str, Any]]:
    """
    Load and validate Vastu rules from vastu-rules.json.

    Returns a list of validated rule dictionaries.
    Raises FileNotFoundError if the file is missing.
    Raises ValueError if the file structure or any rule is invalid.

    Uses lru_cache so the file is read from disk only once per process lifetime —
    rules don't change at runtime, so re-reading on every request would be wasteful.
    """
    if not RULES_FILE_PATH.exists():
        raise FileNotFoundError(
            f"Vastu rules file not found at '{RULES_FILE_PATH}'. "
            f"Ensure vastu-rules.json exists in the project root directory."
        )

    logger.info(f"Loading Vastu rules from {RULES_FILE_PATH}")

    with RULES_FILE_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"vastu-rules.json contains invalid JSON: {e}") from e

    if "rules" not in data or not isinstance(data["rules"], list):
        raise ValueError(
            "vastu-rules.json must have a top-level 'rules' key containing a list of rule objects"
        )

    rules = data["rules"]

    if len(rules) == 0:
        raise ValueError("vastu-rules.json contains no rules — at least one rule is required")

    # Validate each rule's structure before any analysis can run
    for index, rule in enumerate(rules):
        _validate_rule(rule, index)

    # Validate the total weightage sums to 100
    _validate_total_weightage(rules)

    logger.info(f"Successfully loaded {len(rules)} Vastu rules")
    return rules
