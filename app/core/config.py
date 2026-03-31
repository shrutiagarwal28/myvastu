import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Using Pydantic BaseSettings here instead of os.environ.get() so that:
    - Every required variable is declared explicitly with a type
    - Missing required variables raise a ValidationError at startup, not mid-request
    - The .env file is loaded automatically — no manual dotenv.load() calls needed
    - This object can be injected into routes via FastAPI's Depends() system
    """

    # Required — Pydantic will raise ValidationError on startup if this is missing or empty
    gemini_api_key: str

    # Gemini 1.5 Flash — free tier, supports vision, fast response times
    gemini_model: str = "gemini-1.5-flash"

    # Controls response length; 2048 is plenty for structured JSON analysis output
    max_tokens: int = 2048

    model_config = SettingsConfigDict(
        # Tells Pydantic to look for a .env file in the working directory
        env_file=".env",
        # Ignore any extra env variables not declared in this class
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    Using lru_cache here instead of instantiating Settings() directly in each function
    because BaseSettings reads from disk (.env file) and the environment every time it's
    constructed — that's unnecessary I/O for every request. The cache means it's read
    once at first call, then reused for the lifetime of the process.

    FastAPI's Depends(get_settings) will call this function, but the cache ensures
    it only constructs the Settings object once regardless of how many routes use it.
    """
    logger.info("Loading application settings from environment")
    return Settings()
