import base64
import json
import logging
import re
from typing import Any

import anthropic

from app.models.schemas import AnalyzeResponse, RuleResult

logger = logging.getLogger(__name__)


def _encode_image_as_base64(image_bytes: bytes) -> str:
    """
    Encode raw image bytes to a base64 string for the Claude vision API.
    Claude's vision API requires images to be base64-encoded when sent inline.
    """
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def _build_analysis_prompt(north_direction: str, rules: list[dict[str, Any]]) -> str:
    """
    Build the structured text prompt that instructs Claude how to analyze the floor plan.

    The prompt is built from the rules JSON so it stays in sync with vastu-rules.json
    automatically — no hardcoded rule descriptions in Python.
    """
    rules_section = ""
    for rule in rules:
        rules_section += f"""
Rule ID: {rule["id"]}
Rule Name: {rule["name"]}
Description: {rule["description"]}
What to look for: {rule["what_to_look_for"]}
Ideal: {rule["ideal"]}
Avoid: {rule["avoid"]}
Maximum score: {rule["weightage"]} points
---"""

    return f"""You are a Vastu Shastra expert analyzing a floor plan image.

The user has marked NORTH as: {north_direction}

Analyze this floor plan against the following {len(rules)} Vastu rules and return a JSON response.

RULES TO EVALUATE:
{rules_section}

SCORING INSTRUCTIONS:
- For each rule, assign a score between 0 and the rule's maximum score
- Be fair but honest — partial compliance should get partial credit
- If a room or feature is not clearly visible, note that and give a neutral score (50% of max)

RESPONSE FORMAT:
Return ONLY valid JSON — no markdown, no explanation outside the JSON. Use exactly this structure:

{{
  "rule_results": [
    {{
      "rule_id": "<rule id>",
      "rule_name": "<rule name>",
      "score": <number between 0 and max_score>,
      "max_score": <the rule weightage>,
      "observation": "<one or two sentences describing what you see in the floor plan for this rule>",
      "suggestion": "<specific actionable suggestion if score is not perfect, or empty string if ideal>"
    }}
  ],
  "summary": "<2-3 sentence plain-language overall summary a non-expert would understand>"
}}

Important: Write observations and suggestions in simple, warm language for someone buying or renting an apartment — not a Vastu expert."""


def _parse_claude_response(response_text: str, rules: list[dict[str, Any]]) -> tuple[list[RuleResult], str]:
    """
    Parse Claude's JSON response into typed RuleResult objects.

    Claude is instructed to return pure JSON, but we defensively handle cases
    where it wraps the JSON in a markdown code block anyway.

    Returns a tuple of (rule_results, summary).
    Raises ValueError if the response cannot be parsed or is structurally invalid.
    """
    # Strip markdown code blocks if Claude added them despite instructions
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        # Remove opening ```json or ``` and closing ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON response: {e}\nRaw response: {response_text[:500]}") from e

    if "rule_results" not in data or not isinstance(data["rule_results"], list):
        raise ValueError(f"Claude response missing 'rule_results' list. Got keys: {list(data.keys())}")

    if "summary" not in data:
        raise ValueError("Claude response missing 'summary' field")

    # Build a lookup of valid rule IDs and their weightages for validation
    valid_rules = {r["id"]: r["weightage"] for r in rules}

    rule_results: list[RuleResult] = []
    for item in data["rule_results"]:
        rule_id = item.get("rule_id", "")

        # Clamp score to valid range — never trust AI output blindly
        max_score = valid_rules.get(rule_id, item.get("max_score", 0))
        raw_score = float(item.get("score", 0))
        clamped_score = max(0.0, min(float(max_score), raw_score))

        if clamped_score != raw_score:
            logger.warning(f"Score for rule '{rule_id}' was out of range ({raw_score}), clamped to {clamped_score}")

        rule_results.append(RuleResult(
            rule_id=rule_id,
            rule_name=item.get("rule_name", ""),
            score=clamped_score,
            max_score=float(max_score),
            observation=item.get("observation", ""),
            suggestion=item.get("suggestion", ""),
        ))

    return rule_results, data["summary"]


def _calculate_overall_score(rule_results: list[RuleResult]) -> float:
    """
    Calculate the overall Vastu score as the sum of individual rule scores.

    Since each rule's max_score is already its weightage out of 100,
    the sum of scores is the overall score out of 100.
    This is a pure function — given the same results, always returns the same score.
    """
    return round(sum(r.score for r in rule_results), 1)


async def analyze_floor_plan(
    image_bytes: bytes,
    content_type: str,
    north_direction: str,
    rules: list[dict[str, Any]],
    anthropic_api_key: str,
    claude_model: str,
    max_tokens: int,
) -> AnalyzeResponse:
    """
    Core analysis function — calls Claude vision API with the floor plan image
    and Vastu rules, parses the response, and returns a structured AnalyzeResponse.

    This is a Phase 1 raw SDK implementation. All parameters are passed explicitly
    (no globals, no hidden state) making this function fully testable in isolation.

    Raises:
        anthropic.APIError: if the Claude API call fails
        ValueError: if Claude's response cannot be parsed
    """
    logger.info(f"Starting Vastu analysis — north: {north_direction}, model: {claude_model}, rules: {len(rules)}")

    # Map MIME type to the media_type string Claude's API expects
    media_type_map = {
        "image/jpeg": "image/jpeg",
        "image/png": "image/png",
    }
    media_type = media_type_map.get(content_type, "image/jpeg")

    image_b64 = _encode_image_as_base64(image_bytes)
    prompt_text = _build_analysis_prompt(north_direction, rules)

    client = anthropic.Anthropic(api_key=anthropic_api_key)

    logger.info("Sending request to Claude API...")
    message = client.messages.create(
        model=claude_model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        # The floor plan image — Claude vision reads this
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        # The structured analysis instructions
                        "type": "text",
                        "text": prompt_text,
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text
    logger.info(f"Claude response received — stop_reason: {message.stop_reason}, tokens used: {message.usage.input_tokens + message.usage.output_tokens}")

    rule_results, summary = _parse_claude_response(response_text, rules)
    overall_score = _calculate_overall_score(rule_results)

    logger.info(f"Analysis complete — overall score: {overall_score}/100")

    return AnalyzeResponse(
        overall_score=overall_score,
        north_direction=north_direction,
        rule_results=rule_results,
        summary=summary,
    )