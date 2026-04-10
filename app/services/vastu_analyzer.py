import asyncio
import io
import json
import logging
import re
from typing import Any

import google.generativeai as genai
from PIL import Image

from app.models.schemas import AnalyzeResponse, RuleResult

logger = logging.getLogger(__name__)


def _build_analysis_prompt(north_direction: str, rules: list[dict[str, Any]]) -> str:
    """
    Build the structured text prompt that instructs Gemini how to analyze the floor plan.

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


def _parse_gemini_response(response_text: str, rules: list[dict[str, Any]]) -> tuple[list[RuleResult], str]:
    """
    Parse Gemini's JSON response into typed RuleResult objects.

    Defensively handles cases where Gemini wraps the JSON in a markdown code block.
    Returns a tuple of (rule_results, summary).
    Raises ValueError if the response cannot be parsed or is structurally invalid.
    """
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned non-JSON response: {e}\nRaw response: {response_text[:500]}") from e

    if "rule_results" not in data or not isinstance(data["rule_results"], list):
        raise ValueError(f"Response missing 'rule_results' list. Got keys: {list(data.keys())}")

    if "summary" not in data:
        raise ValueError("Response missing 'summary' field")

    valid_rules = {r["id"]: r["weightage"] for r in rules}

    rule_results: list[RuleResult] = []
    for item in data["rule_results"]:
        rule_id = item.get("rule_id", "")
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
    Sum of individual rule scores equals the overall score out of 100,
    since each rule's max_score is already its weightage out of 100.
    """
    return round(sum(r.score for r in rule_results), 1)


async def analyze_floor_plan(
    image_bytes: bytes,
    content_type: str,
    north_direction: str,
    rules: list[dict[str, Any]],
    gemini_api_key: str,
    gemini_model: str,
    max_tokens: int,
) -> AnalyzeResponse:
    """
    Core analysis function — calls Gemini vision API with the floor plan image
    and Vastu rules, parses the response, and returns a structured AnalyzeResponse.

    Gemini accepts PIL Images directly — no base64 encoding needed, which is
    simpler than the Anthropic approach.

    Raises:
        google.api_core.exceptions.GoogleAPIError: if the API call fails
        ValueError: if Gemini's response cannot be parsed
    """
    logger.info(f"Starting Vastu analysis — north: {north_direction}, model: {gemini_model}, rules: {len(rules)}")

    # Configure the Gemini client with the API key
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(model_name=gemini_model)

    # Convert raw bytes to a PIL Image — Gemini's SDK accepts PIL images directly
    image = Image.open(io.BytesIO(image_bytes))
    prompt_text = _build_analysis_prompt(north_direction, rules)

    logger.info("Sending request to Gemini API...")

    # Gemini's SDK is synchronous — running it directly in an async function would block
    # the entire FastAPI event loop for the 15-30s the API call takes. asyncio.to_thread()
    # offloads it to a thread pool, keeping the event loop free for other requests.
    response = await asyncio.to_thread(
        model.generate_content,
        [image, prompt_text],
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=0.2,  # Low temperature for consistent, factual analysis
        ),
    )

    response_text = response.text
    logger.info("Gemini response received")

    rule_results, summary = _parse_gemini_response(response_text, rules)
    overall_score = _calculate_overall_score(rule_results)

    logger.info(f"Analysis complete — overall score: {overall_score}/100")

    return AnalyzeResponse(
        overall_score=overall_score,
        north_direction=north_direction,
        rule_results=rule_results,
        summary=summary,
    )
