"""
Application configuration.
All values are loaded from environment variables (.env in local dev,
real environment variables in staging/production — never commit secrets).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Service-to-service auth ---
    service_api_key: str  # value of X-Service-Api-Key that ASP.NET Core must send

    # --- AI provider (via OpenRouter — OpenAI-compatible endpoint) ---
    openrouter_api_key: str
    # Despite the "openrouter_" prefix (kept for historical/generality reasons —
    # this client works with any OpenAI-compatible endpoint), production actually
    # points directly at Google's Gemini OpenAI-compatibility layer. See
    # API_CONTRACT.md §8 for why.
    openrouter_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # Locked production decision (revised) — see API_CONTRACT.md §8. Do not
    # switch to another model without re-running the accuracy comparison
    # against real prescription images first.
    openrouter_model: str = "gemini-3.6-flash"
    # OpenRouter uses these to attribute usage to your app on their dashboard/leaderboards.
    # Optional, but recommended — set to your real site once you have one.
    openrouter_site_url: str = "https://medicare.app"
    openrouter_site_name: str = "MediCare"

    # --- Confidence weighting (must sum to 1.0) ---
    weight_ocr: float = 0.4
    weight_llm: float = 0.4
    weight_db_match: float = 0.2

    # --- Thresholds ---
    review_confidence_threshold: float = 0.90
    image_quality_reject_threshold: float = 0.50

    # --- Upload limits ---
    max_image_size_mb: int = 10
    allowed_image_types: tuple[str, ...] = ("image/jpeg", "image/png")

    # --- Rate limiting ---
    rate_limit_per_minute: int = 30


settings = Settings()
