# عقد API الخاص بخدمة الذكاء الاصطناعي في MediCare — الإصدار 1.1

_آخر مزامنة مع الكود الفعلي: 2026-09-03. المستند ده هو المرجع الوحيد لفريق الـ ASP.NET Core — لو السيرفر الشغال خالف حاجة هنا، المستند هو اللي غلط ولازم يتصحح، مش إن الفريق يتأقلم مع الاختلاف._

## نظرة عامة على البنية

```
تطبيق Flutter  --->  ASP.NET Core Web API (C#)  --->  خدمة الذكاء الاصطناعي (Python / FastAPI)
                         |                                  |
                    SQL Server                    LLM Vision + مطابقة قاعدة بيانات الأدوية
```

الباك اند ASP.NET Core هو **الوحيد** اللي بينادي على خدمة الذكاء الاصطناعي. خدمة الذكاء الاصطناعي أبدًا متتنادى مباشرة من Flutter — مفيش عندها أي مصادقة موجهة للمستخدم، بس مصادقة بين الخدمات (Service-to-service). الـ ASP.NET Core هو اللي مسؤول عن جلسة المستخدم، وحفظ النتائج في SQL Server، وبيبعت لخدمة الـ AI بس البيانات اللي محتاجاها.

---

## 1. الـ Base URL

| البيئة | الرابط الأساسي |
|---|---|
| بيئة التطوير المحلية | `http://localhost:8001` |
| الإنتاج (FastAPI Cloud) | `https://medicare-ai-service.fastapicloud.dev` |

كل الـ Endpoints ليها بادئة `/api/v1`.

**ملاحظة عن التعرض للشبكة العامة:** بعكس افتراض العزل داخل VPC خاص اللي كان مكتوب هنا الأول، خدمة Render Web Service بتاخد **رابط عام افتراضيًا**. يعني `X-Service-Api-Key` بقى خط الدفاع الوحيد — عامله كسر إنتاج حقيقي (طويل وعشوائي، مخزّن في Environment Variables بتاعة Render، وأبدًا متتكتبش في `.env` مرفوع على Git أو في أي محادثة/تذكرة). لو الخطة بتاعتك في Render بتدعم IP Allowlisting، فعّلها واقصر الوصول على IP بتاع سيرفر الـ ASP.NET Core.

**توصية (لو مستقبلًا احتجت تتجاوز بنية Render المشتركة):** انشر خدمة الذكاء الاصطناعي جوه نفس الشبكة الخاصة (VPC) بتاعة الـ ASP.NET Core (زي نفس Azure VNet أو AWS VPC)، وامنع الوصول للإنترنت العام عليها خالص على مستوى الشبكة. ده بيلغي فئة كاملة من مشاكل المصادقة لخدمة مفروض محدش يوصلها غير الباك اند بتاعك. لحد ما تحتاج كده، على Render، مفتاح الـ API هو اللي بيعمل الوظيفة دي — شوف ملاحظة التعرض للشبكة فوق.

---

## 2. المصادقة (بين الخدمات)

بما إن ده تراسل بين باك اندين (مش موجّه للمستخدم مباشرة)، استخدم API Key ثابت زائد mTLS اختياري، مش JWT خاص بالمستخدم.

**الهيدر المطلوب في كل طلب:**
```
X-Service-Api-Key: {shared_secret}
Content-Type: multipart/form-data   (لـ endpoints الصور)
Content-Type: application/json      (لـ endpoints الـ JSON فقط)
```

- الـ Shared Secret بيتولد مرة واحدة، ويتخزن في Azure Key Vault / AWS Secrets Manager، ويتحقن في الخدمتين كمتغير بيئة (`AI_SERVICE_API_KEY`). محدش يكتبه Hardcoded في الكود أبدًا.
- اختياريًا، ابعت هيدر `X-Request-Id` (GUID) من الـ ASP.NET Core عشان تتبع الطلب في اللوجات بين الخدمتين (Distributed Tracing).
- لو خدمة الذكاء الاصطناعي محتاجة تبقى متاحة برة الـ VPC يومًا ما (زي مثلًا نشر متعدد المناطق Multi-region)، رقّي النظام لـ Service JWTs قصيرة العمر تصدرها الـ ASP.NET Core (على نمط Client-credentials)، مش مفتاح ثابت طويل العمر.

**استجابة 401 لو المفتاح ناقص أو غلط:**
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

## 3. الـ Endpoints

### 3.1 `GET /api/v1/health`
فحص بسيط للتأكد إن الخدمة شغالة (Liveness/Readiness check) لأغراض الـ Load Balancer والمراقبة.

**استجابة 200:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "model_provider": "openrouter:gemini-3.6-flash",
  "timestamp": "2026-09-03T10:15:00Z"
}
```
`model_provider` بتعكس أي موديل متظبط دلوقتي في `OPENROUTER_MODEL` — وده قرار إنتاج مثبت (شوف القسم 8)، مش حاجة تتغير بناءً على القيمة دي لوحدها.

---

### 3.2 `POST /api/v1/prescriptions/analyze`

ده الـ Endpoint الأساسي. بياخد صورة الروشتة ويرجّع بيانات الأدوية منظمة مع نسبة ثقة لكل عنصر.

**الطلب:** `multipart/form-data`

| الحقل | النوع | مطلوب؟ | ملاحظات |
|---|---|---|---|
| `image` | ملف | أيوه | JPEG أو PNG. أقصى حجم 10 ميجا. الدقة الأدنى المقترحة 1080 بكسل على أقصر ضلع. |
| `patient_id` | نص (GUID) | أيوه | بيتم تمريره بس لأغراض التتبع/اللوج — خدمة الذكاء الاصطناعي Stateless ومش بتستعلم على SQL Server بنفسها. |
| `language_hint` | نص | لأ | `"ar"` (افتراضي) أو `"en"`. بيساعد خطوة الـ OCR/LLM تميل للغة الصح لما الخط يدوي ومختلط بأسماء أدوية تجارية. |

**مثال cURL:**
```bash
curl -X POST https://ai.medicare.internal/api/v1/prescriptions/analyze \
  -H "X-Service-Api-Key: {secret}" \
  -F "image=@prescription.jpg" \
  -F "patient_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -F "language_hint=ar"
```

**استجابة 200 — نجاح:**
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

**ملاحظات تصميمية مهمة لفريق الـ ASP.NET Core:**

- `combined_confidence` هو اللي المفروض شاشة 7 في تطبيق Flutter تعرضه كنسبة مئوية (باجات زي 96%، 92%، 89%). وهو متوسط مرجّح: `0.4 × ocr_confidence + 0.4 × llm_extraction_confidence + 0.2 × database_match_confidence`. عدّل الأوزان دي لما يبقى عندك بيانات حقيقية من الاستخدام الفعلي.
- `requires_review` بتبقى `true` لو **أي** دواء نسبة الثقة بتاعته (`combined_confidence`) أقل من حد معين (المقترح 0.90) أو `matched_in_database` بتاعته `false`. الـ ASP.NET Core لازم دايمًا يوجّه لشاشة المراجعة والتعديل (شاشة 8) في الحالة دي، وأبدًا ميعتمدش البيانات تلقائيًا.
- `flagged_for_manual_review` بيديك بالظبط الحقل اللي محتاج تظهره في واجهة المراجعة، عشان Flutter منحتاجش نخمّن أي قيمة كانت مش مضمونة — القيمة دي جاية من الموديل نفسه، مش مستنتجة بس من نسبة الثقة (لأن بعض الحقول بترجع null تلقائيًا بدل ما تاخد نسبة ثقة منخفضة).
- `analysis_id` لازم يتخزن من الـ ASP.NET Core مربوط بسجل روشتة المريض لأغراض المراجعة (Audit) — أبدًا متولّدش ID جديد بدله.
- قاعدة بيانات الأدوية اللي بيعتمد عليها `matched_in_database`/`database_match_score` قايمة مُنتقاة بتكبر باستمرار (أكتر من 40 دواء لحد دلوقتي، وكل اسم تجاري اتأكد منه يدويًا قبل الإضافة). متوقع إن `matched_in_database: false` تظهر لأي دواء لسه مضافش — ده النظام شغال صح، مش باج تحتاج تتجاوزه.

**كل أكواد `flagged_for_manual_review[].reason` الموجودة فعليًا في الكود:**

| الكود | المعنى | السبب النموذجي |
|---|---|---|
| `LOW_OVERALL_CONFIDENCE` | نسبة الثقة الكلية لهذا الدواء أقل من حد المراجعة | خط غير واضح، أو دواء مش موجود في القاعدة |
| `LOW_CONFIDENCE_FREQUENCY` | `frequency_per_day` رجعت `null` والدواء مش معلّم `as_needed` | الموديل مقدرش يقرأ عدد مرات الجرعة اليومية |
| `DRUG_NOT_IN_DATABASE` | `matched_in_database` قيمتها `false` | دواء حقيقي لسه مضافش للقائمة، أو قراءة غلط فعلاً |
| `POSSIBLE_AMOUNT_STRENGTH_CONFUSION` | `dosage.amount` بتطابق رقميًا الرقم الموجود جوه `strength` | الموديل ممكن يكون نسخ تركيز الدواء (زي "20mg") بدل عدد الوحدات الفعلي (زي "قرص واحد") |

`POSSIBLE_AMOUNT_STRENGTH_CONFUSION` عندها حالة إنذار كاذب معروفة وغير ضارة: دواء رقم تركيزه بالصدفة يطابق كمية جرعة صحيحة فعلاً (زي "Augmentin 1g — قرص واحد" بيفعّل التحذير لأن الرقمين اتنين "1"). ده مقصود — الخدمة بتفضّل التحذير الزيادة على مخاطرة تفويت لخبطة حقيقية بصمت. تعامل معاه كـ"يستاهل نظرة تانية"، مش "غلط أكيد".

---

**استجابة 422 — جودة صورة ضعيفة (التحليل ملحقش يبدأ):**
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

**استجابة 400 — طلب غير صحيح (ملف ناقص أو غير صالح):**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_IMAGE",
    "message": "The uploaded file is not a valid JPEG or PNG image, or exceeds 10MB."
  }
}
```

**استجابة 429 — تجاوز الحد المسموح من الطلبات:**
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

**استجابة 500 — فشل من مزوّد الذكاء الاصطناعي:**
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
الـ ASP.NET Core لازم يطبّق إعادة محاولة تدريجية (Retry-with-backoff، زي مكتبة Polly) لحالات `500`/`AI_PROVIDER_ERROR` و`429`، بس أبدًا متعملش إعادة محاولة تلقائية لـ `400`/`422` — دول محتاجين صورة جديدة من المستخدم نفسه.

---

### 3.3 `POST /api/v1/drugs/search` (Endpoint مساعد، اختياري بس منصوح بيه)

بيسمح للـ ASP.NET Core (أو شاشة "إضافة دواء يدويًا" في Flutter — شاشة 11 "إضافة دواء جديد") إنه يبحث في نفس قاعدة بيانات الأدوية اللي بتستخدمها خدمة الذكاء الاصطناعي، عشان تضمن تناسق الأسماء.

**الطلب:**
```json
{
  "query": "اموكسيسيلين",
  "limit": 5
}
```

**استجابة 200:**
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

## 4. قيود رفع الصور (تفعيلها من الجانبين)

| القاعدة | القيمة |
|---|---|
| أقصى حجم للملف | 10 ميجابايت |
| الصيغ المقبولة | `image/jpeg`, `image/png` |
| الدقة الدنيا المقترحة | 1080 بكسل على أقصر ضلع |
| الدقة القصوى المقترحة | 4096 بكسل على أقصر ضلع (قلّل الحجم قبل الرفع لتوفير البيانات — مفيش فايدة إضافية لدقة الـ OCR فوق الحد ده) |

**توصية:** خلّي **Flutter** يضغط ويصغّر الصورة من جهة العميل قبل ما توصل لـ ASP.NET Core أصلًا (مثلًا أقصى طول 2000 بكسل، جودة JPEG 85%). ده بيقلل وقت الرفع وتكلفة خدمة الذكاء الاصطناعي بشكل كبير مع فقدان دقة ضئيل جدًا، وبرضو الـ ASP.NET Core لازم يعيد التحقق من الحجم والصيغة من ناحية السيرفر في كل الأحوال — محدش يعتمد على التحقق من جهة العميل بس.

---

## 5. ملخص نسب الثقة (للرجوع السريع)

| الحقل | المدى | المعنى |
|---|---|---|
| `overall_confidence` | 0.0 – 1.0 | المتوسط عبر كل الأدوية في الروشتة |
| `combined_confidence` (لكل دواء) | 0.0 – 1.0 | النسبة المرجحة اللي بتتعرض للمستخدم كنسبة مئوية |
| `database_match_score` | 0.0 – 1.0 | قوة المطابقة التقريبية (Fuzzy match) مع قاعدة بيانات الأدوية |
| `image_quality.score` | 0.0 – 1.0 | لو أقل من 0.5 تقريبًا → ارفض الصورة قبل حتى محاولة الاستخراج |

حقل `image_quality.issues` قايمة من القيم دي: `unreadable_file`, `resolution_too_low`, `blurry`, `too_dark`, `overexposed`, `low_contrast`. ممكن تيجي فاضية حتى لو `score` مش مثالي — يعني صورة متوسطة بس قابلة للاستخدام. شفنا فعليًا في الاختبار الحقيقي: صورة بـ score=0.78 وفيها `resolution_too_low` ولسه طلعت تحليل مفيد. تعامل مع القايمة كتفصيل استرشادي لسؤال "تصور تاني؟"، مش شرط قاطع (الخدمة نفسها بترفض بناءً على `score` بس، مش على وجود أي issue بعينه).

اضرب في 100 وقرّب الرقم للعرض (مثلًا `0.96` → `96%`، بنفس شكل الباجات في شاشة 7).

---

## 6. اقتراح لتخزين البيانات في SQL Server (من جانب ASP.NET Core)

ده مش جزء من عقد خدمة الذكاء الاصطناعي نفسها، بس عشان الفريقين يتفقوا على شكل التخزين: احفظ استجابة الـ JSON الخام كاملة مربوطة بسجل الروشتة (عمود `nvarchar(max)` / JSON)، بالإضافة لصفوف منظمة (Normalized) في جدول `PrescriptionMedications` للاستعلام السهل. أبدًا متحفظش بس النسخة المُحلّلة (Parsed) — خلّي استجابة الذكاء الاصطناعي الخام موجودة برضو، لأنك هتحتاجها لو حسّنت الـ Prompt لاحقًا وعايز تعيد المعالجة، وكمان كسجل تدقيق (Audit trail) ضروري في تطبيق طبي.

---

## 8. قرار الموديل المثبت (مُراجَع)

خدمة الذكاء الاصطناعي متظبطة تشتغل بـ **`gemini-3.6-flash`** في الإنتاج، بيتم استدعاؤه مباشرة عبر طبقة توافق OpenAI بتاعة Gemini من جوجل (`OPENROUTER_BASE_URL` بتشاور على العنوان ده رغم اسم المتغير — سيبناه عام كده عشان الكود يشتغل مع أي مزوّد متوافق مع OpenAI).

**التاريخ، من باب الشفافية:** القرار الأصلي (الموثّق في نسخة سابقة من العقد ده) كان `anthropic/claude-sonnet-4.5`، اتقرر بعد اختبار فعلي على صور حقيقية أثبت إنه بيقرا الروشتات بخط اليد أدق من البدائل المجانية/الأرخص. الفريق بعدين غيّر لـ Gemini لأسباب التكلفة أثناء التطوير. **ده تنازل واعي عن الدقة مقابل التكلفة، مش تحسين في الدقة** — اختبار جنب لجنب على نفس الروشتات أظهر إن `ocr_confidence` بتاع Gemini بيطلع أقل بشكل ملحوظ من Claude على نفس الخط. معناه إن `requires_review` هتتفعّل أكتر كنتيجة مباشرة لكده — ده سلوك متوقع، مش خلل تحتاج تصلحه.

متغيّرش الموديل المتظبط تاني من غير ما تعيد نفس المقارنة على صور حقيقية. شكل العقد (حقول الطلب/الاستجابة، أكواد الأخطاء) مبيتغيرش بناءً على أي موديل متظبط — بس حقل `model_provider` في `health` هو اللي بيعكسه.

---

## 9. إدارة الإصدارات (Versioning)

- العقد بيتم إصداره عن طريق مسار الـ URL (`/api/v1/...`). أي تغيير جذري (Breaking change) بيتنقل لـ `/api/v2/...` مع إبقاء الإصدار القديم شغال لفترة انتقالية — أبدًا متكسرش `v1` وهو شغال.
- تقدر تضيف حقول اختيارية جديدة بحرية من غير ما تحتاج ترفع رقم الإصدار؛ الحاجة اللي محتاجة رفع إصدار هي بس الحذف أو تغيير الاسم أو تغيير النوع.
