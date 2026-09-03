"""
Service-to-service authentication. ASP.NET Core must send the shared
X-Service-Api-Key header on every request. This is NOT user authentication —
there is no concept of a logged-in user at this layer.
"""
from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_service_key(x_service_api_key: str | None = Header(None, alias="X-Service-Api-Key")) -> None:
    if x_service_api_key is None or x_service_api_key != settings.service_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or missing service API key"},
        )
