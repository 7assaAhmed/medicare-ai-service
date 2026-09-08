# MediCare AI Service

خدمة الذكاء الاصطناعي الداخلية اللي بتحلل صور الروشتات، مبنية بـ FastAPI. بتتنادى فقط من الباك اند ASP.NET Core — مش متاحة مباشرة لـ Flutter.

مطابقة تمامًا لـ `MediCare_AI_Service_API_Contract.md`.

## النشر على Render

1. **ارفع المشروع على GitHub الأول** (الأوامر بالأسفل)
2. من Render Dashboard، اربط الـ repo بتاعك بخدمة **Web Service** جديدة
3. الإعدادات المطلوبة في Render:
   | الحقل | القيمة |
   |---|---|
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
   | Health Check Path | `/api/v1/health` |
4. **ضيف الـ Environment Variables** من Render Dashboard (Settings → Environment) — **مش من ملف `.env`**، لأن `.env` أصلاً متجاهَل من Git (`.gitignore`) ومش هيترفع:
   ```
   SERVICE_API_KEY=<قيمة عشوائية طويلة حقيقية>
   OPENROUTER_API_KEY=<مفتاحك الحقيقي>
   OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
   OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
   ```

### ⚠️ تنبيه أمان مهم بسبب النشر العام
العقد (`API_CONTRACT.md`) كان مفترض إن الخدمة دي معزولة جوه شبكة خاصة (VPC) ومش متاحة للإنترنت العام. **Render بيديك رابط عام افتراضيًا** (`https://your-service.onrender.com`) — أي حد على الإنترنت يقدر يوصله. يعني:
- **`SERVICE_API_KEY` بقى خط الدفاع الوحيد** — لازم يبقى Secret طويل وعشوائي فعلاً، ومتتشاركهوش في أي شات أو كود عام.
- لو Render بيوفر خاصية IP Allowlisting في الخطة بتاعتك، فعّلها واسمح بس لـ IP بتاع سيرفر الـ ASP.NET Core.
- الـ Rate Limiting (`slowapi`) شغال بالفعل، بس هو حماية أساسية بس مش بديل عن مفتاح قوي.

### أوامر Git للرفع
```bash
cd medicare-ai-service
git init
git add .
git commit -m "Initial commit: MediCare AI service"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO_NAME.git
git push -u origin main
```

---

## التشغيل محليًا

```bash
python -m venv venv
source venv/bin/activate   # على ويندوز: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# افتح .env واملأ OPENROUTER_API_KEY من https://openrouter.ai/workspaces/default/keys
# وSERVICE_API_KEY بقيمة عشوائية طويلة

uvicorn app.main:app --reload --port 8001
```

بعد التشغيل، وثائق الـ API التفاعلية (Swagger) هتلاقيها على:
`http://localhost:8001/docs`

## اختبار سريع

```bash
curl -X POST http://localhost:8001/api/v1/prescriptions/analyze \
  -H "X-Service-Api-Key: change-me-to-a-long-random-string" \
  -F "image=@sample_prescription.jpg" \
  -F "patient_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -F "language_hint=ar"
```

## بنية المشروع

```
app/
  main.py                 نقطة تجميع FastAPI + معالجة الأخطاء الموحدة
  config.py                الإعدادات (متغيرات البيئة)
  auth.py                   التحقق من X-Service-Api-Key
  models/
    schemas.py              كل الـ Pydantic schemas (مطابقة للعقد)
  routers/
    health.py                GET /api/v1/health
    prescriptions.py          POST /api/v1/prescriptions/analyze
    drugs.py                   POST /api/v1/drugs/search
  services/
    ai_extraction.py          استدعاء نموذج رؤية عبر OpenRouter لاستخراج بيانات الروشتة
    drug_database.py          قاعدة بيانات الأدوية + المطابقة التقريبية (rapidfuzz)
    image_quality.py          فحص جودة الصورة قبل إرسالها للموديل (OpenCV)
    confidence.py             دمج نتائج الاستخراج مع المطابقة وحساب النسب النهائية
```

## نقاط مهمة قبل النشر على staging/production

1. **قاعدة بيانات الأدوية**: `drug_database.py` فيه حاليًا 8 أدوية بس كمثال. لازم تستبدلها بمصدر حقيقي — إما جدول في SQL Server يتم تحميله عند بدء التشغيل، أو فهرس بحث منفصل لو العدد كبر (Elasticsearch/Postgres full-text).
2. **قرار الموديل النهائي (مُراجَع)**: `OPENROUTER_MODEL` مثبت على `gemini-3.6-flash` (عبر Google AI Studio مباشرة، مش OpenRouter فعليًا رغم اسم المتغير) كقرار إنتاج نهائي حاليًا. القرار الأصلي كان Claude Sonnet 4.5 بناءً على دقة أعلى مُثبتة في الاختبار الفعلي، لكن اتغيّر لـ Gemini لاحقًا لأسباب التكلفة/التوفر أثناء التطوير. **مهم:** الدقة الفعلية لـ Gemini أقل من Claude في قراءة الروشتات (لوحظ في اختبارات حقيقية: `ocr_confidence` أقل بشكل ملحوظ) — القرار ده تنازل واعي عن الدقة مقابل التكلفة، مش تحسين. أي رجوع لـ Claude أو تغيير تاني لازم يمر بمقارنة دقة فعلية على عينة روشتات حقيقية.
3. **أوزان الثقة** (`WEIGHT_OCR`, `WEIGHT_LLM`, `WEIGHT_DB_MATCH`) في `.env` — دلوقتي قيم تقديرية. بعد ما يبقى عندك بيانات استخدام حقيقية، قيّم دقة كل مكون على حدة واضبط الأوزان.
4. **حد جودة الصورة** (`image_quality.py`, معامل الـ `500.0` في حساب الـ blur) — القيمة دي اتحطت تقديريًا، لازم تتظبط على عينة حقيقية من صور روشتات (واضحة ومش واضحة) عشان الرفض يبقى دقيق.
5. **Rate limiting**: حاليًا بسيط ومبني على IP الطالب (`get_remote_address`). في الإنتاج، بما إن الطالب الوحيد هو الـ ASP.NET Core، فكّر تربطه بمفتاح الخدمة نفسه بدل الـ IP لو هتوزع الباك اند على أكتر من سيرفر خلف Load Balancer.
6. **الـ Logging**: `patient_id` بيتسجل في اللوجات للتتبع بس — تأكد إن نظام اللوجات عندكم متوافق مع سياسة خصوصية البيانات الطبية (HIPAA-style handling) قبل ما تفعّل logging مفصّل في production.
