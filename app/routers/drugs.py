from fastapi import APIRouter, Depends

from app.auth import verify_service_key
from app.models.schemas import DrugSearchRequest, DrugSearchResponse, DrugSearchResult
from app.services import drug_database

router = APIRouter(prefix="/drugs", tags=["drugs"], dependencies=[Depends(verify_service_key)])


@router.post("/search", response_model=DrugSearchResponse)
async def search_drugs(payload: DrugSearchRequest) -> DrugSearchResponse:
    records = drug_database.search(payload.query, limit=payload.limit)
    return DrugSearchResponse(
        results=[
            DrugSearchResult(
                drug_id=r.drug_id,
                generic_name=r.generic_name,
                brand_name_ar=r.brand_name_ar,
                common_strengths=r.common_strengths,
                common_forms=r.common_forms,
            )
            for r in records
        ]
    )
