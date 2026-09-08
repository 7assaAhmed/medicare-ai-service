import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.routers import drugs, health, prescriptions
from app.routers.prescriptions import limiter

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="MediCare AI Service",
    version="1.0.0",
    description="Internal AI microservice for prescription analysis. "
    "Called only by the ASP.NET Core backend — never exposed to Flutter directly.",
)

# CORS is open here ONLY to support the local demo.html test page (opened directly
# from the filesystem or a static server, which browsers treat as a cross-origin
# request). The real ASP.NET Core backend is server-to-server and never subject to
# CORS at all — this does not weaken production security, X-Service-Api-Key still
# gates every call. If demo.html is ever removed, tighten allow_origins accordingly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health.router, prefix="/api/v1")
app.include_router(prescriptions.router, prefix="/api/v1")
app.include_router(drugs.router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Wraps every HTTPException raised in the app into the contract's
    {"success": false, "error": {...}} shape, whether `detail` was passed
    as a plain string or as the structured dict our routers use.
    """
    if isinstance(exc.detail, dict):
        error_body = exc.detail
    else:
        error_body = {"code": "ERROR", "message": str(exc.detail)}

    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error_body},
    )
