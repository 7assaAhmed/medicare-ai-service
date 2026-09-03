"""
Core AI extraction: sends the prescription image directly to a vision-capable
LLM (routed through OpenRouter: https://openrouter.ai) and gets back
structured medication data in one call — no separate OCR step, a modern
vision LLM reads the handwriting and structures it in the same pass.

OpenRouter exposes an OpenAI-compatible endpoint, so we use the `openai`
SDK pointed at OpenRouter's base URL instead of a provider-specific SDK.
This also means you can swap `settings.openrouter_model` to any
vision-capable model on https://openrouter.ai/models (Claude, GPT-4o,
Gemini, etc.) without touching this file.

The model is prompted to self-report two confidence signals per medication:
  - text_clarity: how legible/certain it was about the raw handwriting
    (stands in for what a classic OCR confidence score would be)
  - extraction_certainty: how confident it is in the structured fields
    it derived (dose, frequency, duration) from that text

These map to `ocr_confidence` and `llm_extraction_confidence` in the
final response. `database_match_confidence` is computed separately in
confidence.py after fuzzy-matching against the drug database.
"""
from __future__ import annotations
import base64
import json
import logging
from dataclasses import dataclass

import openai
from app.config import settings

logger = logging.getLogger(__name__)

_client = openai.OpenAI(
    api_key=settings.openrouter_api_key,
    base_url=settings.openrouter_base_url,
    # Without an explicit timeout, the SDK defaults to a very long wait (minutes)
    # before giving up — a slow or overloaded free-tier provider would hang the
    # whole request instead of failing fast into our retry/error handling.
    # 45s comfortably covers a normal ~15-20s analysis with headroom, without
    # leaving the user staring at a spinner for minutes on a bad day.
    timeout=45.0,
    default_headers={
        # OpenRouter-specific headers — used for their dashboard attribution
        # and to unlock certain free-tier rate limits. Safe to leave as-is.
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_site_name,
    },
)

_SYSTEM_PROMPT = """You are a medical prescription analysis assistant used inside a \
patient-facing medication reminder app. You will be shown a photo of a handwritten or \
printed prescription. Extract every medication mentioned and return ONLY a JSON object \
— no prose, no markdown fences, nothing before or after the JSON.

Rules:
- If a field is not present or not legible, use null. Never invent a value.
- "duration_days" and "frequency_per_day" must be integers or null.
- If the prescription says "as needed" / "عند اللزوم" / "PRN", set as_needed=true and \
leave frequency_per_day/duration_days null unless explicitly stated.
- text_clarity and extraction_certainty are your own honest self-assessment from 0.0 to 1.0. \
Do not default to a high number — if the handwriting is genuinely hard to read, say so with a \
low text_clarity even if you produced a best-guess value.
- doctor_instructions_ar: any general instructions on the prescription not tied to a specific \
drug (e.g. "follow up in 2 weeks"), translated/kept in Arabic as written. Null if none.

CRITICAL — do not confuse these two, they are different numbers on the same label:
- "strength" is the concentration printed on the drug packaging itself, fixed per product \
(e.g. "Solupred 20mg" means each tablet IS 20mg — strength="20mg", regardless of how many \
tablets the patient takes).
- "dosage.amount" is how many units the patient actually takes per intake, as written by the \
doctor (e.g. "1 tab morning" means amount=1, unit="tablet" — NOT 20).
A prescription reading "Solupred 20mg — 1 tab morning" must produce strength="20mg" AND \
dosage.amount=1, unit="tablet". Never put the strength number into dosage.amount just because \
it is the only number you are confident about — if the actual intake amount is not legible, \
set dosage.amount to null and lower extraction_certainty instead of substituting the strength.

CRITICAL — every entry in "medications" MUST be an actual drug with an identifiable name. \
Prescriptions are often written with the drug name on one line and its dosing instructions \
on the next line or two (e.g. "Solupred 20mg" then below it "1 tab morning"). Do NOT create \
a separate medications entry for a continuation line that has no drug name of its own — \
attach that text to the "dosage" of the medication it belongs to instead. A standalone \
fragment like "1 tablet", "قرص واحد", "3 times daily", or "for 7 days" with no adjacent drug \
name is dosing instruction text, never a medication in its own right.

Return exactly this JSON shape:
{
  "medications": [
    {
      "raw_text_match": "<the drug name and strength as you read it from the image>",
      "generic_or_brand_guess": "<your best guess at the standardized drug name>",
      "strength": "<the product's fixed concentration, e.g. '20mg', '312mg/5ml', or null>",
      "dosage": {
        "amount": <number of units taken per intake, or null — NEVER the strength value>,
        "unit": "<e.g. 'tablet', 'ml', 'capsule', or null>",
        "frequency_per_day": <integer or null>,
        "duration_days": <integer or null>,
        "instructions_ar": "<string or null>",
        "as_needed": <boolean>
      },
      "confidence": {
        "text_clarity": <0.0-1.0>,
        "extraction_certainty": <0.0-1.0>
      }
    }
  ],
  "doctor_instructions_ar": "<string or null>"
}
"""


@dataclass
class RawExtraction:
    medications: list[dict]
    doctor_instructions_ar: str | None


def _build_image_content(image_bytes: bytes, media_type: str) -> dict:
    """OpenAI-compatible vision content block (data URI), used by OpenRouter regardless
    of which underlying model/provider actually serves the request."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def extract_prescription(image_bytes: bytes, media_type: str, language_hint: str = "ar") -> RawExtraction:
    """
    Calls the LLM (via OpenRouter) once with the prescription image and returns
    the parsed, validated extraction. Raises `AIProviderError` on any failure
    so the router can translate it into the contract's 500/AI_PROVIDER_ERROR shape.
    """
    user_text = (
        "Analyze this prescription image. Respond in the exact JSON shape from your "
        f"instructions. The patient's preferred language is '{language_hint}' — keep "
        "instructions_ar and doctor_instructions_ar in Arabic regardless of what "
        "script the prescription itself uses."
    )

    try:
        response = _client.chat.completions.create(
            model=settings.openrouter_model,
            max_tokens=2000,
            # Some models (notably Gemini 3.x) support a "thinking" mode that can leak
            # visible reasoning text into the response content instead of pure JSON —
            # exactly what broke the first Gemini test. Requesting the lowest effort
            # keeps the model from narrating its reasoning in-line. Providers that don't
            # recognize this parameter (e.g. some Claude routes) generally ignore it, but
            # if a provider hard-rejects it, remove it for that provider's config.
            extra_body={"reasoning_effort": "low"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        _build_image_content(image_bytes, media_type),
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
        )
    except openai.APIError as exc:
        logger.exception("OpenRouter API call failed")
        raise AIProviderError(str(exc)) from exc

    if not response.choices:
        raise AIProviderError("OpenRouter returned no choices in the response")

    raw_text = (response.choices[0].message.content or "").strip()

    # Defensive cleanup in case the model wraps the JSON in fences despite instructions.
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # Defense in depth: some models (seen with Gemini) prepend visible
        # "thinking out loud" text before the actual JSON despite instructions
        # and reasoning_effort=low. Try to salvage the outermost {...} block —
        # the first '{' to the LAST '}' — before giving up entirely.
        extracted = _extract_json_object(raw_text)
        if extracted is None:
            logger.error("Model returned non-JSON output: %s", raw_text[:500])
            raise AIProviderError("Model returned an unparsable response")
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as exc:
            logger.error("Model returned non-JSON output: %s", raw_text[:500])
            raise AIProviderError("Model returned an unparsable response") from exc

    return RawExtraction(
        medications=parsed.get("medications", []),
        doctor_instructions_ar=parsed.get("doctor_instructions_ar"),
    )


def _extract_json_object(text: str) -> str | None:
    """Pulls the outermost {...} block out of text that may have stray prose
    around it (e.g. a model 'thinking out loud' before its JSON answer)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


class AIProviderError(Exception):
    """Raised when the upstream AI provider call fails or returns unusable output."""
