# MediCare AI Service — API Contract v1.1

_Last synced with implementation: 2026-09-03. This document is the single source of truth for the ASP.NET Core team — if the running service ever disagrees with this file, the file is what's wrong and should be fixed, not worked around._

## Architecture overview

```
Flutter App  --->  ASP.NET Core Web API (C#)  --->  AI Service (Python / FastAPI)
                         |                                  |
                    SQL Server                    LLM Vision + Drug DB matching
```

The ASP.NET Core backend is the **only** caller of the AI service. The AI service is never called directly by Flutter — it has no user-facing auth, only service-to-service auth. ASP.NET Core owns the user session, persists results to SQL Server, and forwards only what the AI service needs.

---

## 1. Base URL

| Environment | Base URL |
|---|---|
| Local dev | `http://localhost:8001` |
| Production (Render) | `https://<your-service-name>.onrender.com` — replace once the Render service is live; update this row and hand the real URL to the ASP.NET Core team's `appsettings.json` `AiService:BaseUrl` |

All endpoints are prefixed with `/api/v1`.

**Note on network exposure:** unlike the private-VPC deployment originally assumed below, a Render Web Service gets a **public URL by default**. `X-Service-Api-Key` is therefore the only access control — treat it as a real production secret (long, random, stored in Render's environment variables, never in `.env` committed to git or shared in chat/tickets). Check whether your Render plan supports IP allowlisting and restrict inbound traffic to the ASP.NET Core backend's IP if so.

Recommendation (if/when you outgrow Render's shared infrastructure): deploy the AI service inside the same private network/VPC as the ASP.NET Core backend (e.g. same Azure VNet or AWS VPC) and block public internet access to it entirely at the network level. This removes an entire class of auth problems for a service nothing but your own backend should ever reach. Until then, on Render, the API key is doing that job — see the network exposure note above.

---

## 2. Authentication (service-to-service)

Since this is backend-to-backend traffic (not user-facing), use a static API key plus optional mutual TLS, not user JWTs.

**Header required on every request:**
```
X-Service-Api-Key: {shared_secret}
Content-Type: multipart/form-data   (for image endpoints)
Content-Type: application/json      (for JSON-only endpoints)
```

- The shared secret is generated once, stored in Azure Key Vault / AWS Secrets Manager, and injected into both services as an environment variable (`AI_SERVICE_API_KEY`). Never hardcode it.
- Optionally pass a `X-Request-Id` (GUID) header from ASP.NET Core for distributed tracing/log correlation across both services.
- If the AI service ever needs to be reachable outside the VPC (e.g. multi-region), upgrade to short-lived service JWTs issued by ASP.NET Core (client-credentials style), not a long-lived static key.

**401 response if the key is missing/invalid:**
```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or missing service API key"
  }
}
```

---

## 3. Endpoints

### 3.1 `GET /api/v1/health`
Simple liveness/readiness check for load balancers and monitoring.

**Response 200:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "model_provider": "openrouter:anthropic/claude-sonnet-4.5",
  "timestamp": "2026-09-03T10:15:00Z"
}
```
`model_provider` reflects whatever `OPENROUTER_MODEL` is currently configured — this is a locked production decision (see §8), not something to change casually based on this field alone.

---

### 3.2 `POST /api/v1/prescriptions/analyze`

This is the core endpoint. It receives the prescription image and returns structured, confidence-scored medication data.

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|---|---|---|---|
| `image` | file | yes | JPEG or PNG. Max 10 MB. Recommended min resolution 1080px on the shortest side. |
| `patient_id` | string (GUID) | yes | Passed through only for logging/traceability — the AI service is stateless and does not query SQL Server itself. |
| `language_hint` | string | no | `"ar"` (default) or `"en"`. Helps the OCR/LLM step bias toward the correct language for handwriting mixed with drug brand names. |

**cURL example:**
```bash
curl -X POST https://ai.medicare.internal/api/v1/prescriptions/analyze \
  -H "X-Service-Api-Key: {secret}" \
  -F "image=@prescription.jpg" \
  -F "patient_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -F "language_hint=ar"
```

**Response 200 — success:**
```json
{
  "success": true,
  "analysis_id": "b7e1a2f0-9c3d-4e5f-8a6b-1d2e3f4a5b6c",
  "processing_time_ms": 3420,
  "overall_confidence": 0.92,
  "requires_review": true,
  "image_quality": {
    "score": 0.88,
    "issues": []
  },
  "medications": [
    {
      "raw_text_match": "أموكسيسيلين 500 مجم",
      "matched_drug": {
        "drug_id": "eda-00214",
        "generic_name": "Amoxicillin",
        "brand_name_ar": "أموكسيسيلين",
        "strength": "500mg",
        "form": "capsule",
        "matched_in_database": true,
        "database_match_score": 0.97
      },
      "dosage": {
        "amount": 1,
        "unit": "كبسولة",
        "frequency_per_day": 3,
        "duration_days": 7,
        "instructions_ar": "يفضل تناوله بعد الأكل مع كوب ماء كافٍ",
        "as_needed": false
      },
      "confidence": {
        "ocr_confidence": 0.95,
        "llm_extraction_confidence": 0.93,
        "database_match_confidence": 0.97,
        "combined_confidence": 0.96
      },
      "warnings": [
        "أخبر طبيبك إذا كنت تعاني من حساسية للمضادات الحيوية"
      ]
    },
    {
      "raw_text_match": "بانادول 500 مجم",
      "matched_drug": {
        "drug_id": "eda-00089",
        "generic_name": "Paracetamol",
        "brand_name_ar": "بانادول",
        "strength": "500mg",
        "form": "tablet",
        "matched_in_database": true,
        "database_match_score": 0.99
      },
      "dosage": {
        "amount": 1,
        "unit": "قرص",
        "frequency_per_day": null,
        "duration_days": null,
        "instructions_ar": "عند اللزوم",
        "as_needed": true
      },
      "confidence": {
        "ocr_confidence": 0.9,
        "llm_extraction_confidence": 0.91,
        "database_match_confidence": 0.99,
        "combined_confidence": 0.92
      },
      "warnings": []
    }
  ],
  "doctor_instructions_ar": "الالتزام بالعلاج والمحافظة على مواعيد الأدوية",
  "flagged_for_manual_review": [
    {
      "medication_index": 1,
      "reason": "LOW_CONFIDENCE_FREQUENCY",
      "message": "لم يتم التعرف على عدد مرات الجرعة بوضوح، برجاء المراجعة"
    }
  ]
}
```

**Key design notes for your ASP.NET Core team:**

- `combined_confidence` is what screen 7 in the Flutter app should display as the percentage (96%, 92%, 89% style badges). It is a weighted average: `0.4 × ocr_confidence + 0.4 × llm_extraction_confidence + 0.2 × database_match_confidence`. Tune the weights once you have real data.
- `requires_review` is `true` whenever **any** medication's `combined_confidence` is below a threshold (currently 0.90) or `matched_in_database` is `false` for any item, or a `POSSIBLE_AMOUNT_STRENGTH_CONFUSION` signal fires (see below). ASP.NET Core should always route to the review/edit screen (screen 8) in that case, never auto-confirm.
- `flagged_for_manual_review` gives you the exact field to highlight in the review UI, so Flutter doesn't have to guess which value looked shaky — it's authoritative from the model, not inferred from confidence alone (e.g. some fields silently default to null rather than scoring low).
- `analysis_id` should be stored by ASP.NET Core against the patient's prescription record for auditing — never regenerate an ID for it.
- The drug database backing `matched_in_database`/`database_match_score` is a growing curated list (40+ entries and counting, each brand name manually verified before being added — see the service's own README for the verification policy). Expect `matched_in_database: false` for anything not yet added; this is the system working correctly, not a bug to route around.

**All `flagged_for_manual_review[].reason` codes currently emitted:**

| Reason code | Meaning | Typical trigger |
|---|---|---|
| `LOW_OVERALL_CONFIDENCE` | This medication's `combined_confidence` is below the review threshold | Unclear handwriting, or a drug not in the database |
| `LOW_CONFIDENCE_FREQUENCY` | `frequency_per_day` came back null and the item isn't marked `as_needed` | Model couldn't read how many times per day |
| `DRUG_NOT_IN_DATABASE` | `matched_in_database` is `false` | Real drug not yet added to the curated list, or a genuine misread |
| `POSSIBLE_AMOUNT_STRENGTH_CONFUSION` | `dosage.amount` numerically equals the number inside `strength` | Model may have copied the drug's concentration (e.g. "20mg") into the intake-amount field instead of the actual unit count (e.g. "1 tablet") |

`POSSIBLE_AMOUNT_STRENGTH_CONFUSION` has a known benign false-positive: a drug whose strength number happens to equal a genuinely correct intake amount (e.g. "Augmentin 1g — take 1 tablet" triggers it because both numbers are `1`). This is intentional — the service errs toward over-flagging rather than risking a real confusion slipping through silently. Treat it as "worth a second glance," not "definitely wrong."

---

**Response 422 — poor image quality (analysis not attempted):**
```json
{
  "success": false,
  "error": {
    "code": "IMAGE_QUALITY_TOO_LOW",
    "message": "الصورة غير واضحة بما يكفي للتحليل، برجاء إعادة التصوير في إضاءة أفضل",
    "image_quality": {
      "score": 0.31,
      "issues": ["blurry", "low_contrast"]
    }
  }
}
```

**Response 400 — bad request (missing/invalid file):**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_IMAGE",
    "message": "The uploaded file is not a valid JPEG or PNG image, or exceeds 10MB."
  }
}
```

**Response 429 — rate limited:**
```json
{
  "success": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Retry after the specified interval.",
    "retry_after_seconds": 5
  }
}
```

**Response 500 — upstream AI provider failure:**
```json
{
  "success": false,
  "error": {
    "code": "AI_PROVIDER_ERROR",
    "message": "The AI analysis service is temporarily unavailable. Please retry.",
    "retryable": true
  }
}
```
ASP.NET Core should implement retry-with-backoff (e.g. Polly) for `500`/`AI_PROVIDER_ERROR` and `429`, but never auto-retry `400`/`422` — those need a new image from the user.

---

### 3.3 `POST /api/v1/drugs/search` (helper endpoint, optional but recommended)

Lets ASP.NET Core (or a Flutter "add medication manually" screen — screen 11's "إضافة دواء جديد") search the same drug database the AI uses, for consistent naming.

**Request:**
```json
{
  "query": "اموكسيسيلين",
  "limit": 5
}
```

**Response 200:**
```json
{
  "success": true,
  "results": [
    {
      "drug_id": "eda-00214",
      "generic_name": "Amoxicillin",
      "brand_name_ar": "أموكسيسيلين",
      "common_strengths": ["250mg", "500mg", "1g"],
      "common_forms": ["capsule", "syrup"]
    }
  ]
}
```

---

## 4. Image upload constraints (enforce on both sides)

| Rule | Value |
|---|---|
| Max file size | 10 MB |
| Accepted formats | `image/jpeg`, `image/png` |
| Recommended min resolution | 1080px shortest side |
| Recommended max resolution | 4096px shortest side (downscale before upload to save bandwidth — no benefit above this for OCR accuracy) |

Recommendation: have **Flutter** compress/resize the image client-side before it ever reaches ASP.NET Core (e.g. cap at ~2000px longest side, JPEG quality 85%). This cuts upload time and AI service cost significantly with negligible accuracy loss, and ASP.NET Core should re-validate size/format server-side regardless — never trust client-side validation alone.

---

## 5. Confidence score summary (for quick reference)

| Field | Range | Meaning |
|---|---|---|
| `overall_confidence` | 0.0 – 1.0 | Average across all medications on the prescription |
| `combined_confidence` (per medication) | 0.0 – 1.0 | Weighted score shown to the user as a percentage |
| `database_match_score` | 0.0 – 1.0 | Fuzzy-match strength against the drug database |
| `image_quality.score` | 0.0 – 1.0 | Below ~0.5 → reject before even attempting extraction |

`image_quality.issues` is a list drawn from: `unreadable_file`, `resolution_too_low`, `blurry`, `too_dark`, `overexposed`, `low_contrast`. It can be empty even when `score` isn't perfect — a mediocre-but-usable photo. Seen in real testing: a photo scoring 0.78 with `resolution_too_low` still produced a usable analysis; treat the list as advisory detail for a "retake photo?" prompt, not a hard gate (the service itself already gates on `score`, not on the presence of any specific issue).

Multiply by 100 and round for display (e.g. `0.96` → `96%`, matching screen 7's badges).

---

## 6. Suggested SQL Server persistence (ASP.NET Core side)

Not part of the AI service's contract, but so both teams agree on what gets stored: persist the full raw JSON response against the prescription record (a `nvarchar(max)` / JSON column), plus normalized rows in a `PrescriptionMedications` table for querying. Never persist only the parsed/normalized version — keep the raw AI response too, since you'll want it for reprocessing if you improve prompts later, and for audit trail in a medical app.

---

## 8. Locked model decision

The AI service is configured to use **`anthropic/claude-sonnet-4.5`** (via OpenRouter) in production. This was a deliberate decision after comparing it against cheaper/free alternatives (including a free-tier Gemini model and DeepSeek's vision model) — Claude was measurably more reliable at reading handwritten prescriptions and did not require the safety-threshold workarounds the alternatives needed. Do not change the configured model without re-running that comparison; a cheaper model that reads a dose wrong is not actually cheaper.

This is transparent to ASP.NET Core: the contract (request/response shape, field names, error codes) does not change based on which underlying model is configured. Only `health`'s `model_provider` field reflects it.

---

## 9. Versioning

- The contract is versioned via the URL path (`/api/v1/...`). Breaking changes ship as `/api/v2/...` with the old version kept alive for a deprecation window — never break `v1` in place.
- Add new optional fields freely without a version bump; only removals/renames/type changes require one.
