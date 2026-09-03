from datetime import datetime, timezone
from fastapi import APIRouter

from app.config import settings
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        model_provider=f"openrouter:{settings.openrouter_model}",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
