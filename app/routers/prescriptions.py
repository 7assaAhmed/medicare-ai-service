import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import verify_service_key
from app.config import settings
from app.models.schemas import AnalyzeResponse
from app.services import confidence as confidence_service
from app.services.ai_extraction import AIProviderError, extract_prescription
from app.services.image_quality import assess_image_quality

router = APIRouter(
    prefix="/prescriptions",
    tags=["prescriptions"],
    dependencies=[Depends(verify_service_key)],
)

limiter = Limiter(key_func=get_remote_address)


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def analyze_prescription(
    request: Request,  # required by slowapi's limiter decorator
    image: UploadFile = File(...),
    patient_id: str = Form(...),
    language_hint: str = Form("ar"),
) -> AnalyzeResponse:
    start = time.perf_counter()

    # --- 1. Validate content type ---
    if image.content_type not in settings.allowed_image_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IMAGE",
                "message": "The uploaded file is not a valid JPEG or PNG image, or exceeds 10MB.",
            },
        )

    image_bytes = await image.read()

    # --- 2. Validate size ---
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IMAGE",
                "message": "The uploaded file is not a valid JPEG or PNG image, or exceeds 10MB.",
            },
        )

    # --- 3. Image quality gate (cheap, runs before the expensive AI call) ---
    quality = assess_image_quality(image_bytes)
    if quality.score < settings.image_quality_reject_threshold:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "IMAGE_QUALITY_TOO_LOW",
                "message": "الصورة غير واضحة بما يكفي للتحليل، برجاء إعادة التصوير في إضاءة أفضل",
                "image_quality": quality.model_dump(),
            },
        )

    # --- 4. Call the AI model ---
    try:
        raw = extract_prescription(image_bytes, image.content_type, language_hint)
    except AIProviderError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "AI_PROVIDER_ERROR",
                "message": "The AI analysis service is temporarily unavailable. Please retry.",
                "retryable": True,
            },
        )

    # --- 5. Match against drug database + compute confidence ---
    medications, review_flags = confidence_service.build_medications(raw.medications)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return AnalyzeResponse(
        analysis_id=str(uuid.uuid4()),
        processing_time_ms=elapsed_ms,
        overall_confidence=confidence_service.overall_confidence(medications),
        requires_review=confidence_service.requires_review(medications),
        image_quality=quality,
        medications=medications,
        doctor_instructions_ar=raw.doctor_instructions_ar,
        flagged_for_manual_review=review_flags,
    )
