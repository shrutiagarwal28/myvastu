from pydantic import BaseModel, Field


class RuleResult(BaseModel):
    """
    The analysis result for a single Vastu rule.

    Each rule gets its own score and specific feedback — not just a pass/fail.
    This granularity is what makes the app useful: the user knows exactly
    which aspects of their floor plan are good and which need attention.
    """

    rule_id: str = Field(description="Unique identifier matching the rule's id in vastu-rules.json")
    rule_name: str = Field(description="Human-readable rule name for display in the UI")
    score: float = Field(
        ge=0,
        description="Points scored for this rule (between 0 and the rule's weightage)"
    )
    max_score: float = Field(description="Maximum possible points for this rule (the rule's weightage)")
    observation: str = Field(description="What Claude observed about this specific aspect of the floor plan")
    suggestion: str = Field(description="Actionable improvement suggestion if score is not perfect; empty string if ideal")


class AnalyzeResponse(BaseModel):
    """
    The complete Vastu analysis result returned by the /analyze endpoint.

    Designed to be self-contained — the frontend needs nothing else to render
    the full results page.
    """

    overall_score: float = Field(
        ge=0,
        le=100,
        description="Total Vastu score out of 100, calculated as the weighted sum of individual rule scores"
    )
    north_direction: str = Field(description="The north direction as provided by the user, echoed back for confirmation")
    rule_results: list[RuleResult] = Field(description="Per-rule breakdown of observations and scores")
    summary: str = Field(description="A brief, plain-language overall summary suitable for a layperson")


class ErrorResponse(BaseModel):
    """
    Standard error response shape for all 4xx and 5xx responses.

    Using a consistent error schema means the frontend always knows what to expect
    when something goes wrong — instead of sometimes getting a string, sometimes a dict.
    Never expose internal error details (stack traces, file paths) in this response.
    """

    error: str = Field(description="A safe, user-facing error message with no internal details")
    detail: str | None = Field(
        default=None,
        description="Optional additional context — still user-safe, never a stack trace"
    )
