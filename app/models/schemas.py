"""
Pydantic schemas — these mirror MediCare_AI_Service_API_Contract.md exactly.
Any change here must be reflected in that document, and vice versa.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------- shared / nested objects ----------

class ImageQuality(BaseModel):
    score: float
    issues: list[str] = Field(default_factory=list)


class MatchedDrug(BaseModel):
    drug_id: Optional[str] = None
    generic_name: Optional[str] = None
    brand_name_ar: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    matched_in_database: bool = False
    database_match_score: float = 0.0


class Dosage(BaseModel):
    amount: Optional[float] = None
    unit: Optional[str] = None
    frequency_per_day: Optional[int] = None
    duration_days: Optional[int] = None
    instructions_ar: Optional[str] = None
    as_needed: bool = False


class Confidence(BaseModel):
    ocr_confidence: float
    llm_extraction_confidence: float
    database_match_confidence: float
    combined_confidence: float


class Medication(BaseModel):
    raw_text_match: str
    matched_drug: MatchedDrug
    dosage: Dosage
    confidence: Confidence
    warnings: list[str] = Field(default_factory=list)


class ReviewFlag(BaseModel):
    medication_index: int
    reason: str
    message: str


# ---------- /prescriptions/analyze ----------

class AnalyzeResponse(BaseModel):
    success: bool = True
    analysis_id: str
    processing_time_ms: int
    overall_confidence: float
    requires_review: bool
    image_quality: ImageQuality
    medications: list[Medication]
    doctor_instructions_ar: Optional[str] = None
    flagged_for_manual_review: list[ReviewFlag] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: Optional[bool] = None
    retry_after_seconds: Optional[int] = None
    image_quality: Optional[ImageQuality] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail


# ---------- /drugs/search ----------

class DrugSearchRequest(BaseModel):
    query: str
    limit: int = 5


class DrugSearchResult(BaseModel):
    drug_id: str
    generic_name: str
    brand_name_ar: str
    common_strengths: list[str] = Field(default_factory=list)
    common_forms: list[str] = Field(default_factory=list)


class DrugSearchResponse(BaseModel):
    success: bool = True
    results: list[DrugSearchResult]


# ---------- /health ----------

class HealthResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    status: str
    version: str
    model_provider: str
    timestamp: str
