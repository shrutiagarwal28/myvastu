import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.analyze import router as analyze_router
from app.core.config import get_settings
from app.core.rules_loader import load_vastu_rules

# Configure logging once, at the application entry point.
# All other modules use logging.getLogger(__name__) — they inherit this config.
# Format includes the level, module name, and message so logs are scannable in production.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager — runs startup logic before the app accepts requests,
    and shutdown logic when the process exits.

    Using lifespan instead of the older @app.on_event("startup") decorator because:
    - lifespan is the modern FastAPI pattern (on_event is deprecated)
    - It co-locates startup and shutdown logic in one place
    - It integrates cleanly with testing (TestClient respects the lifespan)

    Startup validation philosophy: if anything here raises an exception, the process
    exits immediately with a clear error message. This is intentional — a half-configured
    app should never serve traffic.
    """
    # --- Startup ---
    logger.info("MyVastu API starting up...")

    # Validate that ANTHROPIC_API_KEY is present and readable.
    # get_settings() will raise pydantic.ValidationError if any required config is missing.
    # We catch it here to log a clear message before the process exits.
    try:
        settings = get_settings()
        logger.info(f"Configuration loaded — model: {settings.claude_model}")
    except Exception as e:
        logger.critical(f"Startup failed — configuration error: {e}")
        logger.critical("Ensure ANTHROPIC_API_KEY is set in your .env file")
        sys.exit(1)

    # Validate that vastu-rules.json exists and is structurally valid.
    # load_vastu_rules() is cached, so this also warms the cache for the first request.
    try:
        rules = load_vastu_rules()
        logger.info(f"Vastu rules loaded — {len(rules)} rules, total weightage: {sum(r['weightage'] for r in rules)}")
    except (FileNotFoundError, ValueError) as e:
        logger.critical(f"Startup failed — rules file error: {e}")
        sys.exit(1)

    logger.info("MyVastu API ready to serve requests")

    yield  # Application runs here — everything above is startup, everything below is shutdown

    # --- Shutdown ---
    logger.info("MyVastu API shutting down")


# Create the FastAPI application instance.
# Metadata here feeds directly into the auto-generated /docs UI.
app = FastAPI(
    title="MyVastu API",
    description=(
        "Analyze apartment floor plans for Vastu Shastra compliance. "
        "Upload a floor plan image, specify north direction, and receive a score out of 100 "
        "with per-rule feedback and improvement suggestions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Register the analyze router under the /api/v1 prefix.
# Versioning the API path from day one means we can introduce /api/v2 later
# without breaking existing clients — even though we have no clients yet.
app.include_router(analyze_router, prefix="/api/v1", tags=["Analysis"])


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """
    Health check endpoint — returns 200 OK if the API is running.

    Used by load balancers and monitoring systems to verify the service is alive.
    Does not check downstream dependencies (Claude API, rules file) — those are
    validated at startup, not on every health check.
    """
    return {"status": "ok"}
