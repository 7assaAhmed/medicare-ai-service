"""
Combines the LLM's raw extraction with the drug database match to produce
the final `Medication` objects and `combined_confidence` scores that go out
in the API response — this is the piece that turns "the model said X" into
"here's a trustworthy structured record, and here's exactly how much to
trust it."
"""
from __future__ import annotations

from app.config import settings
from app.models.schemas import Confidence, Dosage, MatchedDrug, Medication, ReviewFlag
from app.services import drug_database


def build_medications(raw_medications: list[dict]) -> tuple[list[Medication], list[ReviewFlag]]:
    medications: list[Medication] = []
    review_flags: list[ReviewFlag] = []

    for raw in raw_medications:
        raw_name = raw.get("raw_text_match") or raw.get("generic_or_brand_guess") or ""
        guess = raw.get("generic_or_brand_guess") or raw_name

        # --- Defense in depth: even with the corrected prompt, drop any entry
        # that is clearly dosing-instruction text mistaken for a drug name
        # (e.g. "قرص واحد" / "1 tablet" / "3 times daily" with no real name).
        # This happened in testing despite the prompt explicitly forbidding it,
        # so we don't rely on the prompt alone for a field this consequential.
        if _looks_like_instruction_not_a_drug(raw_name):
            continue

        # Computed AFTER the skip check above, so it always matches this
        # medication's eventual position in the `medications` list — using
        # the raw loop index here would drift out of sync as soon as any
        # entry gets skipped, misattributing every later review flag.
        idx = len(medications)

        db_record, db_score_0_100 = drug_database.find_best_match(guess)
        database_match_confidence = round(db_score_0_100 / 100.0, 2)

        raw_conf = raw.get("confidence", {})
        ocr_confidence = float(raw_conf.get("text_clarity", 0.0))
        llm_extraction_confidence = float(raw_conf.get("extraction_certainty", 0.0))

        combined = round(
            settings.weight_ocr * ocr_confidence
            + settings.weight_llm * llm_extraction_confidence
            + settings.weight_db_match * database_match_confidence,
            2,
        )

        matched_drug = MatchedDrug(
            drug_id=db_record.drug_id if db_record else None,
            generic_name=db_record.generic_name if db_record else None,
            brand_name_ar=db_record.brand_name_ar if db_record else None,
            # Prefer the model's own structured "strength" field (accurate now that
            # the prompt explicitly separates it from dosage.amount). Fall back to
            # regex-guessing from the raw text only for older/non-compliant model output.
            strength=raw.get("strength") or _extract_strength(raw_name),
            form=None,
            matched_in_database=db_record is not None,
            database_match_score=database_match_confidence,
        )

        raw_dosage = raw.get("dosage", {}) or {}
        dosage = Dosage(
            amount=raw_dosage.get("amount"),
            unit=raw_dosage.get("unit"),
            frequency_per_day=raw_dosage.get("frequency_per_day"),
            duration_days=raw_dosage.get("duration_days"),
            instructions_ar=raw_dosage.get("instructions_ar"),
            as_needed=bool(raw_dosage.get("as_needed", False)),
        )

        warnings: list[str] = []
        if not matched_drug.matched_in_database:
            warnings.append("لم يتم التعرف على هذا الدواء في قاعدة البيانات، برجاء التأكد من الاسم يدويًا")

        # --- Defense in depth: even with the corrected prompt, catch any residual
        # confusion where the model still copied the strength number into amount
        # (e.g. "20mg" strength ending up as dosage.amount=20). This is a plausible
        # failure mode specifically for a safety-critical field, so we don't rely
        # on the prompt fix alone — we verify the output shape itself.
        strength_confusion = _looks_like_strength_copied_into_amount(matched_drug.strength, dosage)
        if strength_confusion:
            warnings.append(
                "الكمية المستخرجة تطابق تركيز الدواء وليس عدد الوحدات — برجاء التأكد يدويًا من الجرعة الفعلية"
            )

        medications.append(
            Medication(
                raw_text_match=raw_name,
                matched_drug=matched_drug,
                dosage=dosage,
                confidence=Confidence(
                    ocr_confidence=ocr_confidence,
                    llm_extraction_confidence=llm_extraction_confidence,
                    database_match_confidence=database_match_confidence,
                    combined_confidence=combined,
                ),
                warnings=warnings,
            )
        )

        # --- Review flags: authoritative reasons, not just "confidence is low" ---
        if combined < settings.review_confidence_threshold:
            review_flags.append(
                ReviewFlag(
                    medication_index=idx,
                    reason="LOW_OVERALL_CONFIDENCE",
                    message="نسبة الثقة في هذا الدواء منخفضة، برجاء المراجعة اليدوية",
                )
            )
        if dosage.frequency_per_day is None and not dosage.as_needed:
            review_flags.append(
                ReviewFlag(
                    medication_index=idx,
                    reason="LOW_CONFIDENCE_FREQUENCY",
                    message="لم يتم التعرف على عدد مرات الجرعة بوضوح، برجاء المراجعة",
                )
            )
        if not matched_drug.matched_in_database:
            review_flags.append(
                ReviewFlag(
                    medication_index=idx,
                    reason="DRUG_NOT_IN_DATABASE",
                    message="اسم الدواء غير موجود في قاعدة البيانات، برجاء التأكيد اليدوي",
                )
            )
        if strength_confusion:
            review_flags.append(
                ReviewFlag(
                    medication_index=idx,
                    reason="POSSIBLE_AMOUNT_STRENGTH_CONFUSION",
                    message="الكمية المستخرجة تطابق تركيز الدواء بدل عدد الوحدات — تأكد يدويًا قبل الاعتماد",
                )
            )

    return medications, review_flags


def _looks_like_instruction_not_a_drug(raw_name: str) -> bool:
    """
    Returns True if `raw_name` is dosing-instruction text with no actual drug
    name in it (e.g. "قرص واحد", "1 tablet", "3 times daily", "for 7 days").

    Heuristic: strip known dosage/frequency words (Arabic + English) and any
    numbers/units; if nothing meaningful is left, it wasn't a drug name to
    begin with. A real drug name — even a misread one like "Rifocine forte"
    or "qualin" — always leaves letters behind after this strip.
    """
    import re

    if not raw_name or not raw_name.strip():
        return True

    text = raw_name.strip().lower()

    # Common dosage/frequency/form words that show up on instruction-only lines.
    filler_words = [
        "قرص", "أقراص", "قرصين", "قرصان", "كبسولة", "كبسولات", "كبسولتين",
        "حبة", "حبوب", "حبتين", "ملعقة", "ملعقتين", "بخة", "بختين",
        "مرة", "مرات", "مرتين", "يوميا", "يوميًا", "صباحا", "صباحًا", "مساء", "مساءً",
        "عند اللزوم", "للزوم", "قبل الأكل", "بعد الأكل",
        "واحد", "واحدة", "اثنان", "اثنين", "ثلاثة", "أربعة", "خمسة",
        "tablet", "tablets", "tab", "capsule", "capsules", "cap",
        "once", "twice", "daily", "morning", "evening", "night",
        "times", "time", "per day", "as needed", "prn", "before food", "after food",
    ]
    # Sort longest-first so a substring like "قرص" doesn't get replaced before
    # a longer word containing it (e.g. "قرصين") gets its own chance to match.
    for word in sorted(filler_words, key=len, reverse=True):
        text = text.replace(word, " ")

    # Strip numbers, units, and punctuation — what's left should be the drug name.
    text = re.sub(r"\d+(\.\d+)?", " ", text)
    text = re.sub(r"\b(mg|mcg|g|ml|مجم|مجرام|مل)\b", " ", text)
    text = re.sub(r"[^\w\u0600-\u06FF]", " ", text)  # punctuation/dashes
    remainder = text.strip()

    return len(remainder) == 0


def _looks_like_strength_copied_into_amount(strength: str | None, dosage: Dosage) -> bool:
    """
    Returns True if dosage.amount numerically matches the number inside `strength`
    (e.g. strength="20mg", amount=20) — a strong signal the model copied the
    concentration into the intake-amount field instead of the actual unit count.
    A genuine intake amount matching a strength number by coincidence (e.g. "20
    tablets") is rare enough that flagging for human review is the safer default.
    """
    import re

    if strength is None or dosage.amount is None:
        return False

    match = re.search(r"(\d+(?:\.\d+)?)", strength)
    if not match:
        return False

    strength_number = float(match.group(1))
    return abs(dosage.amount - strength_number) < 0.01


def _extract_strength(raw_name: str) -> str | None:
    """Best-effort pull of something like '500mg' / '500 مجم' out of the raw text."""
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|مجم|مجرام|مل)", raw_name, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def overall_confidence(medications: list[Medication]) -> float:
    if not medications:
        return 0.0
    return round(sum(m.confidence.combined_confidence for m in medications) / len(medications), 2)


def requires_review(medications: list[Medication]) -> bool:
    return any(
        m.confidence.combined_confidence < settings.review_confidence_threshold
        or not m.matched_drug.matched_in_database
        or _looks_like_strength_copied_into_amount(m.matched_drug.strength, m.dosage)
        for m in medications
    )
