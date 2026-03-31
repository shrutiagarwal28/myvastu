import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from google.api_core import exceptions as google_exceptions

from app.core.config import Settings, get_settings
from app.core.rules_loader import load_vastu_rules
from app.models.schemas import AnalyzeResponse
from app.services import vastu_analyzer

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_NORTH_DIRECTIONS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze a floor plan for Vastu compliance",
    description=(
        "Upload a floor plan image (JPG or PNG) and specify the north direction. "
        "Returns an overall Vastu score out of 100 with per-rule feedback and improvement suggestions."
    ),
)
async def analyze_floor_plan(
    floor_plan: UploadFile = File(description="Floor plan image — JPG or PNG, max 5MB"),
    north_direction: str = Form(description="North direction — one of: N, NE, E, SE, S, SW, W, NW"),
    settings: Settings = Depends(get_settings),
) -> AnalyzeResponse:
    """
    POST /analyze — validates inputs, then delegates to the vastu_analyzer service.
    This handler contains no business logic — only HTTP concerns.
    """
    logger.info(f"Received analysis request — north='{north_direction}', file='{floor_plan.filename}'")

    # Validate north direction
    normalized_direction = north_direction.strip().upper()
    if normalized_direction not in VALID_NORTH_DIRECTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid north direction '{north_direction}'. Must be one of: {', '.join(sorted(VALID_NORTH_DIRECTIONS))}",
        )

    # Validate file type
    if floor_plan.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{floor_plan.content_type}'. Only JPG and PNG images are accepted.",
        )

    # Read and validate file size
    image_bytes = await floor_plan.read()

    if len(image_bytes) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    if len(image_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"File too large ({len(image_bytes) // 1024}KB). Maximum allowed size is 5MB.",
        )

    # Load rules (cached — reads from disk only once per process lifetime)
    rules = load_vastu_rules()

    # Delegate to the service layer — all AI logic lives there
    try:
        result = await vastu_analyzer.analyze_floor_plan(
            image_bytes=image_bytes,
            content_type=floor_plan.content_type,
            north_direction=normalized_direction,
            rules=rules,
            gemini_api_key=settings.gemini_api_key,
            gemini_model=settings.gemini_model,
            max_tokens=settings.max_tokens,
        )
    except google_exceptions.PermissionDenied:
        logger.error("Gemini API authentication failed — check GEMINI_API_KEY")
        raise HTTPException(status_code=500, detail="Analysis service configuration error. Please contact support.")
    except google_exceptions.ResourceExhausted:
        logger.warning("Gemini API rate limit hit")
        raise HTTPException(status_code=429, detail="Analysis service is busy. Please try again in a moment.")
    except google_exceptions.GoogleAPIError as e:
        logger.error(f"Gemini API error: {e}")
        raise HTTPException(status_code=502, detail="Analysis service is temporarily unavailable. Please try again.")
    except ValueError as e:
        logger.error(f"Failed to parse analysis response: {e}")
        raise HTTPException(status_code=500, detail="Analysis returned an unexpected result. Please try again.")

    return result
