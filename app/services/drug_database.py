"""
Drug database + fuzzy matching.

This is a starter in-memory database so the service is runnable and testable
end-to-end immediately. In production, replace `DRUG_DB` with a real query
against your drug reference table (e.g. a mirror of the Egyptian Drug
Authority / EDA list, or a licensed drug database), loaded into SQL Server
or a dedicated search index (Elasticsearch/Postgres full-text) if the list
grows past a few thousand entries.

The matching interface (`find_best_match`, `search`) is what the rest of the
app depends on — swap the storage without touching callers.

IMPORTANT: prescriptions are overwhelmingly written with the ENGLISH brand
name (doctors write "Panadol", "Augmentin", "Zyrtec" — not the Arabic name
or the generic name). Every record must list its real English brand
name(s) in `brand_names_en`, or matching will silently fail on exactly the
text a prescription actually contains. This was a real bug found during
testing: the first version of this file only indexed generic_name and
brand_name_ar, so English brand names extracted straight off a real
prescription (Solupred, Rinvoq, Rhinocort, Augmentin, Zyrtec) matched
nothing at all.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from rapidfuzz import fuzz, process


@dataclass
class DrugRecord:
    drug_id: str
    generic_name: str
    brand_name_ar: str
    # A generic can have several English brand names on the market
    # (e.g. Paracetamol -> Panadol, Adol, Fevadol) — list every one you know.
    brand_names_en: list[str] = field(default_factory=list)
    common_strengths: list[str] = field(default_factory=list)
    common_forms: list[str] = field(default_factory=list)


# Starter dataset, expanded from the original 8-drug placeholder. Generic-name
# mappings below were verified against public drug references (not guessed) —
# see the comment on each uncertain entry. This is STILL a starter list, not a
# production drug database: replace with a licensed source (e.g. a mirror of
# the Egyptian Drug Authority / EDA registry) before real patients rely on it.
DRUG_DB: list[DrugRecord] = [
    # --- Analgesics / antipyretics / NSAIDs ---
    DrugRecord("eda-00089", "Paracetamol", "بانادول", ["Panadol", "Adol", "Fevadol"],
               ["500mg", "1g"], ["tablet", "syrup", "suppository"]),
    DrugRecord("eda-00298", "Ibuprofen", "بروفين", ["Brufen"],
               ["200mg", "400mg", "600mg"], ["tablet", "syrup"]),
    DrugRecord("eda-00901", "Diclofenac", "فولتارين", ["Voltaren", "Cataflam"],
               ["50mg", "75mg", "100mg"], ["tablet", "suppository", "gel"]),
    DrugRecord("eda-00902", "Mefenamic acid", "بونستان", ["Ponstan"],
               ["250mg", "500mg"], ["capsule", "syrup"]),

    # --- Antibiotics ---
    DrugRecord("eda-00214", "Amoxicillin", "أموكسيسيلين", ["Amoxil", "Emox"],
               ["250mg", "500mg", "1g"], ["capsule", "syrup"]),
    DrugRecord("eda-00903", "Co-amoxiclav (amoxicillin/clavulanate)", "أوجمنتين", ["Augmentin"],
               ["625mg", "1g", "312mg/5ml", "457mg/5ml"], ["tablet", "syrup"]),
    DrugRecord("eda-00455", "Azithromycin", "أزيثروميسين", ["Zithromax", "Azomax"],
               ["250mg", "500mg"], ["tablet", "syrup"]),
    DrugRecord("eda-00904", "Cefixime", "سيفيكسيم", ["Suprax"],
               ["200mg", "400mg"], ["tablet", "syrup"]),
    # Verified: Daktarin (Janssen) = Miconazole, an antifungal for oral thrush
    # and other fungal infections.
    DrugRecord("eda-00934", "Miconazole", "دكتارين", ["Daktarin"],
               ["2%"], ["oral gel", "cream"]),
    DrugRecord("eda-00905", "Ciprofloxacin", "سيبروفلوكساسين", ["Ciprocin", "Ciprobay"],
               ["250mg", "500mg", "750mg"], ["tablet"]),
    # Verified: Tavanic (Sanofi/Aventis) = Levofloxacin, a fluoroquinolone antibiotic.
    DrugRecord("eda-00932", "Levofloxacin", "تافانيك", ["Tavanic"],
               ["250mg", "500mg", "750mg"], ["tablet", "IV infusion"]),

    # --- Antihistamines / allergy ---
    DrugRecord("eda-00612", "Cetirizine", "زيرتك", ["Zyrtec"],
               ["10mg"], ["tablet", "syrup"]),
    DrugRecord("eda-00906", "Loratadine", "كلاريتين", ["Claritine"],
               ["10mg"], ["tablet", "syrup"]),
    # Verified via public drug references: Rhinocort = budesonide nasal spray,
    # a corticosteroid for allergic rhinitis (not an antibiotic/antihistamine).
    DrugRecord("eda-00907", "Budesonide (nasal)", "رينوكورت", ["Rhinocort"],
               ["32mcg/dose", "64mcg/dose"], ["nasal spray"]),

    # --- Corticosteroids ---
    # Verified: Solupred is a French/MENA brand of prednisolone.
    DrugRecord("eda-00908", "Prednisolone", "سولوبريد", ["Solupred"],
               ["5mg", "20mg"], ["tablet", "orodispersible tablet", "syrup"]),

    # --- GI / PPIs ---
    DrugRecord("eda-00341", "Omeprazole", "أوميبرازول", ["Gastrazole", "Omez"],
               ["20mg", "40mg"], ["capsule"]),
    DrugRecord("eda-00909", "Esomeprazole", "نيكسيوم", ["Nexium"],
               ["20mg", "40mg"], ["tablet"]),
    DrugRecord("eda-00910", "Domperidone", "موتيليوم", ["Motilium"],
               ["10mg"], ["tablet", "syrup"]),

    # --- Diabetes / cardiovascular / cholesterol ---
    DrugRecord("eda-00512", "Metformin", "ميتفورمين", ["Cidophage", "Glucophage"],
               ["500mg", "850mg", "1000mg"], ["tablet"]),
    DrugRecord("eda-00733", "Atorvastatin", "أتورفاستاتين", ["Lipitor", "Atorlip"],
               ["10mg", "20mg", "40mg"], ["tablet"]),
    DrugRecord("eda-00911", "Amlodipine", "نورفاسك", ["Norvasc"],
               ["5mg", "10mg"], ["tablet"]),
    DrugRecord("eda-00912", "Losartan", "لوسارتان", ["Cozaar"],
               ["25mg", "50mg", "100mg"], ["tablet"]),
    # Verified: Coversyl Plus = Perindopril arginine + Indapamide combo (Servier),
    # for hypertension.
    DrugRecord("eda-00918", "Perindopril/Indapamide", "كوفرسيل بلس", ["Coversyl Plus", "Coversyl-plus"],
               ["5/1.25mg", "10/2.5mg"], ["tablet"]),
    # Verified: Diamicron MR = Gliclazide modified-release (Servier), for type 2 diabetes.
    DrugRecord("eda-00919", "Gliclazide", "دياميكرون", ["Diamicron"],
               ["30mg", "60mg", "80mg"], ["modified-release tablet"]),
    # Verified: Crestor = Rosuvastatin (AstraZeneca), cholesterol-lowering statin.
    DrugRecord("eda-00920", "Rosuvastatin", "كريستور", ["Crestor"],
               ["5mg", "10mg", "20mg"], ["tablet"]),
    # Verified: Plavix = Clopidogrel (Sanofi), antiplatelet used after cardiac events/stents.
    # Clopex (Marcyrl, Egypt) is a second confirmed Egyptian brand of the same generic.
    DrugRecord("eda-00921", "Clopidogrel", "بلافيكس", ["Plavix", "Clopex"],
               ["75mg"], ["tablet"]),
    # Colchicine is written on prescriptions by its generic name directly — no
    # separate brand entry needed, but included so the generic name itself matches.
    # Used for gout and familial Mediterranean fever.
    DrugRecord("eda-00922", "Colchicine", "كولشيسين", [],
               ["0.5mg"], ["tablet"]),

    # --- Antiparasitic ---
    # CRITICAL FIX: "Iverzine" (a real Egyptian brand) was previously fuzzy-matching
    # to Cetirizine/Zyrtec because the names share the "-rizine" suffix. These are
    # completely different drug classes (antiparasitic vs. antihistamine) — a
    # dangerous mismatch. Verified: Iverzine = Ivermectin, used for parasitic skin/
    # hair infections (e.g. scabies, lice), not allergies. Adding it explicitly
    # so it matches correctly instead of falling through to a similar-sounding
    # but pharmacologically unrelated drug.
    DrugRecord("eda-00916", "Ivermectin", "إيفرزين", ["Iverzine"],
               ["3mg", "6mg"], ["tablet", "cream", "lotion"]),

    # --- Neurology / psychiatry ---
    # Verified: Alzemenda/Alzmenda = Memantine (NMDA receptor antagonist), for
    # moderate-to-severe Alzheimer's — commonly co-prescribed with a
    # cholinesterase inhibitor like donepezil.
    DrugRecord("eda-00929", "Memantine", "الزيمندا", ["Alzemenda", "Alzmenda"],
               ["5mg", "10mg", "20mg"], ["tablet"]),
    # High-confidence but not directly source-verified: "Alzepezil" follows the
    # same Egyptian naming convention as Alzemenda (Alzheimer's + generic-name
    # suffix) and "-epezil" directly mirrors "donepezil". Standard practice
    # pairs a cholinesterase inhibitor (donepezil) with memantine in Alzheimer's
    # treatment, matching how these two appeared together on the same
    # prescription during testing. Verify against an official source before
    # relying on this in production if exact confirmation matters.
    DrugRecord("eda-00930", "Donepezil (unconfirmed brand mapping)", "الزيبيزيل", ["Alzepezil"],
               ["5mg", "10mg"], ["tablet"]),
    # Verified: Riscure = Risperidone (antipsychotic), from an official Egyptian
    # drug classification list alongside other risperidone brands (Risperdal,
    # Risdal, etc.).
    DrugRecord("eda-00931", "Risperidone", "ريسكيور", ["Riscure"],
               ["1mg", "2mg", "3mg", "4mg"], ["tablet", "syrup"]),

    # --- Respiratory / cough (English brand spelling and exact composition
    # not independently verified for the Egyptian market — confirm against
    # an official source before relying on these in production) ---
    DrugRecord("eda-00913", "Ambroxol", "توسيكان", ["Tussikan"],
               ["30mg", "15mg/5ml"], ["tablet", "syrup"]),
    # Verified: Tussistop = Levodropropizine syrup, a non-opioid cough suppressant
    # marketed in Egypt (ATCO Pharma) — distinct from Ambroxol/Tussikan above.
    DrugRecord("eda-00917", "Levodropropizine", "توسيستوب", ["Tussistop"],
               ["30mg/5ml"], ["syrup"]),
    DrugRecord("eda-00914", "Salbutamol", "فنتولين", ["Ventolin"],
               ["100mcg/dose", "2mg", "4mg"], ["inhaler", "tablet", "syrup"]),

    # --- Eye / ENT drops (verified compositions) ---
    DrugRecord("eda-00923", "Fluorometholone/Tetrahydrozoline", "إيفيميو", ["Efemyo"],
               [], ["eye drop"]),
    # Composition of Remowax varies slightly by market source; core function
    # (earwax softener) is confirmed. Verify exact local formulation before
    # displaying detailed ingredient info to patients.
    DrugRecord("eda-00924", "Earwax softener (multi-ingredient)", "ريموواكس", ["Remowax"],
               [], ["ear drop"]),

    # --- Antihistamines / respiratory (continued) ---
    # Verified: Aerius = Desloratadine (MSD/Organon), second-generation antihistamine.
    DrugRecord("eda-00925", "Desloratadine", "إيريوس", ["Aerius"],
               ["5mg"], ["tablet", "syrup"]),

    # --- GI / PPI (continued) ---
    # Verified: Controloc = Pantoprazole (Takeda), proton pump inhibitor.
    DrugRecord("eda-00926", "Pantoprazole", "كونترولوك", ["Controloc"],
               ["20mg", "40mg"], ["tablet"]),

    # --- Nutritional supplements commonly prescribed alongside real drugs
    # (verified via manufacturer/pharmacy listings — these are supplements,
    # not regulated pharmaceuticals in the strict sense, but patients scan
    # them just the same and doctors prescribe them for anemia/general health) ---
    DrugRecord("eda-00927", "Iron supplement (ferrous compound)", "فارافيرو", ["Pharaferro", "Pharreferro"],
               [], ["capsule"]),
    DrugRecord("eda-00928", "Multi-antioxidant supplement", "أوكسيفري", ["Oxifree"],
               [], ["capsule"]),

    # --- Specialty / biologics (verified: Rinvoq = upadacitinib, a JAK
    # inhibitor for rheumatoid arthritis, atopic dermatitis, and related
    # conditions — extended-release tablets) ---
    DrugRecord("eda-00915", "Upadacitinib", "رينفوك", ["Rinvoq"],
               ["15mg", "30mg", "45mg"], ["extended-release tablet"]),
]

# Index by generic name, Arabic brand name, AND every English brand name —
# a match on any of these should resolve to the same record.
_SEARCH_INDEX: dict[str, DrugRecord] = {}
for _rec in DRUG_DB:
    _SEARCH_INDEX[_rec.generic_name.lower()] = _rec
    _SEARCH_INDEX[_rec.brand_name_ar] = _rec
    for _brand in _rec.brand_names_en:
        _SEARCH_INDEX[_brand.lower()] = _rec


def find_best_match(raw_name: str, score_cutoff: float = 70.0) -> tuple[DrugRecord | None, float]:
    """
    Fuzzy-match a raw OCR/LLM-extracted drug name against the database.
    Returns (matched_record_or_None, match_score_0_to_100).

    Uses rapidfuzz's token_sort_ratio so word order and minor OCR noise
    ("اموكسيسيلين" vs "أموكسيسيلين", "augmentine" vs "Augmentin") don't
    break the match.

    SAFETY-CRITICAL THRESHOLD — do not lower this casually. It was raised
    from 60 to 70 after testing found "Quetiapine" (an antipsychotic) fuzzy-
    matching to "Cetirizine" (an antihistamine — Zyrtec) at score 60. Every
    verified legitimate match seen in testing so far scores 74+, while that
    dangerous cross-class mismatch scored exactly at the old cutoff. A missed
    match just means "not found, ask the user to confirm manually" (safe);
    a wrong match silently substitutes one drug's identity for another's
    (dangerous). When in doubt, tighten this number, not loosen it.
    """
    if not raw_name or not raw_name.strip():
        return None, 0.0

    candidates = list(_SEARCH_INDEX.keys())
    result = process.extractOne(
        raw_name.strip(),
        candidates,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=score_cutoff,
    )
    if result is None:
        return None, 0.0

    matched_key, score, _ = result
    return _SEARCH_INDEX[matched_key], score


def search(query: str, limit: int = 5) -> list[DrugRecord]:
    """Used by the /drugs/search helper endpoint (manual medication entry)."""
    if not query or not query.strip():
        return []

    candidates = list(_SEARCH_INDEX.keys())
    results = process.extract(
        query.strip(),
        candidates,
        scorer=fuzz.token_sort_ratio,
        limit=limit * 2,  # over-fetch, then dedupe by drug_id below
        score_cutoff=40.0,
    )

    seen_ids: set[str] = set()
    matches: list[DrugRecord] = []
    for key, _score, _ in results:
        rec = _SEARCH_INDEX[key]
        if rec.drug_id not in seen_ids:
            seen_ids.add(rec.drug_id)
            matches.append(rec)
        if len(matches) >= limit:
            break
    return matches
