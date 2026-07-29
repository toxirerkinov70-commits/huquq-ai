# Kamchiliklar

Tizimning zaif joylari, o'lchov bilan tasdiqlangan holda. Har biri uchun sabab va
tuzatish yo'li ko'rsatilgan. Oxirgi bo'lim — tizim doirasida hal qilib bo'lmaydigan,
tashqi sharoitdan kelib chiqadigan cheklovlar.

**O'lchov sanasi:** 2026-07-29 · 22 513 chunk · `eval/run.py`

---

## 1. Qidiruv kamchiliklari

| # | Kamchilik | Dalil | Tuzatish |
|---|---|---|---|
| 1.1 | **Dense tomon jadvalli moddalarda ko'r** | dense recall@5 = 0.52. 33 va 51-savollarda sparse nishonni 2–3-o'rinda topadi, dense top-20 ga ham kiritmaydi | Bor, lekin qimmat — quyida |
| 1.2 | **So'zlashuv tili → huquqiy atama bo'shlig'i** | Qiyin to'plamda `colloquial` recall@5 = **0.33** (3 tadan 1 tasi) | Sinonim lug'ati kerak |
| 1.3 | **Bitta savolda ikkita modda raqami** | `superscript` recall@5 = 0.67. "FK 173 va 173² farqi" savolida 173² siqib chiqariladi | **Oson va aniq** |
| 1.4 | **Ikki kodeks chegarasidagi savol** | `cross_code` recall@5 = **0.00** (1 savol) | Ko'p qidiruvli reja kerak |
| 1.5 | **Ko'p qismli savol** | `multipart` recall@5 = **0.00** (1 savol) | Savolni bo'lish kerak |
| 1.6 | **Vaziyat bayoni** | `situation` recall@5 = **0.67** — asosiy to'plamdagi eng past ko'rsatkich | 1.2 bilan bir xil ildiz |

### 1.1 — Dense tomon ko'rligi

Modda matni jadval va raqamlarga to'la bo'lsa, uning o'rtacha vektori mavzuni
ifodalamaydi. RRF esa ikkala ro'yxatda ham o'rtacha turgan nomzodni bitta ro'yxatda
birinchi turgandan yuqori qo'yadi — ya'ni dense ko'rligi gibridga ham zarar yetkazadi.

**Yechim:** `parser/lex/chunk.py` dagi `_embedding_body()` hozir jadvalni 600 belgigacha
qisqartiradi. Buning o'rniga jadval qatorlaridan **raqamlarni olib tashlab, faqat qator
nomlarini** qoldirish kerak ("Banklar", "Budjet tashkilotlari") — semantik signal o'sha
yerda.

**Narxi:** bu `text_for_embedding` ni o'zgartiradi, ya'ni 22 513 chunk qaytadan
embedding qilinadi (~3 soat, keshdan foyda yo'q). Shuning uchun hali qilinmagan.

**Sinab ko'rilgan va yordam bermagan** (qaytadan urinmang):

| Urinish | Natija |
|---|---|
| Fusion havzasini chuqurlashtirish (20 → 100 → 400) | recall umuman o'zgarmadi |
| `RRF_K` ni pasaytirish (60 → 3) | bitta savolni tuzatib boshqasini buzdi |
| Hujjat bo'yicha cheklov (max N chunk) | recall 0.96 → **0.91 ga tushdi** |

### 1.2 va 1.6 — So'zlashuv tili bo'shlig'i

"Meni ishdan haydashdi" → qonunda "mehnat shartnomasini qonunga xilof ravishda bekor
qilish" (MK 174-modda). Bu ko'chirmani na BM25 (so'zlar umuman boshqa), na e5
embedding (o'zbek tilidagi huquqiy sinonimlarga o'rgatilmagan) qoplaydi.

Query expansion qisman yordam beradi, lekin u LLM chaqiruvi — ya'ni kvotaga bog'liq
va har savolda ishlatib bo'lmaydi.

**Yechim yo'nalishi:** so'zlashuv ↔ huquqiy atama lug'ati (qo'lda yoki korpusdan
avtomatik), sparse tomonga so'rov kengaytirish sifatida ulanadi. LLM talab qilmaydi,
shuning uchun kvotaga tegmaydi.

### 1.3 — Ikkinchi modda raqami yo'qoladi

`backend/app/services/query.py` dagi `detect_article_no()` `ARTICLE_RE.search()` dan
foydalanadi va **faqat birinchi** moslikni qaytaradi. Savolda ikkita raqam bo'lsa
ikkinchisi butunlay e'tiborsiz qoladi.

**Tuzatish:** `search()` → `findall()`, funksiya ro'yxat qaytarsin, `hybrid_search()`
har bir raqam uchun `article_lookup()` chaqirib natijalarni birlashtirsin. Chaqiruv
joylari: `retrieval.py`, `chat.py`, `search.py`, `coverage.py`.

### 1.4 va 1.5 — Bitta savol, bir nechta nishon

"Do'kondan 200 ming so'mlik mahsulot o'g'irlasam, bu ma'muriy huquqbuzarlikmi yoki
jinoyatmi?" — javob uchun MJK 61 va JK 169 **birga** kerak. Ikkalasi ham korpusda bor,
lekin bitta qidiruv ikkalasini ham yuqoriga chiqara olmaydi.

Xuddi shu narsa ko'p qismli savolda: ikkinchi qismning so'zlari birinchisini
cho'ktiradi.

**Yechim:** savolni bir nechta mustaqil so'rovga ajratib, har biri bo'yicha alohida
qidirish. Agentik rejim buni allaqachon qila oladi (model o'zi bir necha marta
`search_legal_base` chaqiradi), standart quvurda esa yo'q.

---

## 2. Baholash tizimidagi kamchiliklar

| # | Kamchilik | Izoh |
|---|---|---|
| 2.1 | **Bitta savolga bitta to'g'ri javob** | Eval yorlig'i bitta `doc_id` + `article_no` juftligi. 2-savolda ("qasddan odam o'ldirish jazosi") Plenum qarori JK 97-moddadan yuqori chiqadi — bu **mazmunan to'g'ri**, lekin eval uni xato deb sanaydi |
| 2.2 | **9-guruh sinalmagan** | 185 ta Oliy sud hujjati qo'shilgan, lekin ularni sinaydigan savol atigi 3 ta |
| 2.3 | **Faqat retrieval o'lchanadi** | Javob halolligi, format va til to'g'riligi qo'lda tekshiriladi (`eval/hard_questions.md` bo'yicha), avtomatik emas |

**Tuzatish (2.1):** yorliqni juftliklar **ro'yxatiga** aylantirish —
`"accepted": [{"doc_id": ..., "article_no": ...}, ...]`. `eval/run.py` dagi `rank_of()`
birinchi mos kelganini qaytarsin.

---

## 3. Kod va xavfsizlik

| # | Kamchilik | Holati |
|---|---|---|
| 3.1 | **Rate limiting amalda ishlamayapti** | `main.py` da `Limiter(default_limits=["60/minute"])` e'lon qilingan, `RateLimitExceeded` handler ham ulangan — lekin `SlowAPIMiddleware` qo'shilmagan va yo'llarda `@limiter.limit(...)` yo'q. slowapi'da `default_limits` faqat middleware orqali kuchga kiradi, ya'ni **hozir hech qanday chegara qo'llanmaydi** |
| 3.2 | **API kalit himoyasi yo'q** | Barcha endpointlar ochiq, CORS `allow_origins=["*"]`. Lokal ishlatishda muammo emas, ochiq internetga chiqarilsa — jiddiy muammo |
| 3.3 | **Birlik testlari yo'q** | Faqat `eval/run.py` (retrieval sifati) va `scripts/ui_check.py` (UI). `sparse.tokenize`, `query.detect_article_no`, `diff.compare`, `chunk_document` kabi sof funksiyalar test bilan qoplanmagan — regressiyani faqat eval ko'rsatadi, u ham bilvosita |
| 3.4 | **Kirill hujjatlar sinalmagan** | Transliteratsiya funksiyasi yozilgan, lekin **hech qachon ishlamagan**: 1 283 hujjatning hammasi lotin yozuvida chiqdi. Ya'ni bu kod yo'li tekshirilmagan |

**Tuzatish (3.1):** `app.add_middleware(SlowAPIMiddleware)` — bitta qator.

**Tuzatish (3.2):** `X-API-Key` sarlavhasini tekshiradigan `Depends` bog'liqligi va
CORS ro'yxatini aniq domenlarga cheklash. Deploy qilishdan **oldin** majburiy.

---

## 4. Tizim doirasida hal qilib bo'lmaydigan cheklovlar

Bular kod xatosi emas — tashqi sharoitdan kelib chiqadi va faqat sharoit o'zgarsa
yo'qoladi.

| Cheklov | Ta'siri | Nega tizim ichida hal qilinmaydi |
|---|---|---|
| **LLM bepul tarifi** | Har model kuniga ~20 so'rov, 6 ta zaxira model bilan ~120 so'rov/kun. Bitta savol 3 ta so'rov yeydi (rewrite + rerank + javob), ya'ni **~40 savol/kun** | Faqat pullik tarif hal qiladi. Kod tomondan qilingani: 6 modelli fallback zanjiri va `ENABLE_QUERY_EXPANSION` / `ENABLE_RERANK` o'chirgichlari |
| **lex.uz `Crawl-delay: 20`** | Bitta hujjat = 20 soniya. Korpusni kengaytirish tabiatan sekin | `robots.txt` talabi. Tezlashtirish IP blokga olib keladi va loyihani to'xtatadi |
| **8 GB RAM** | Backend konteyneri va indexatsiya jarayoni birga sig'maydi — har indexatsiyada konteynerni to'xtatish kerak | Ikkala jarayon ham embedding modelini (~1.1 GB) va o'z ish xotirasini talab qiladi. Faqat temir hal qiladi |
| **Lokal embedding tezligi** | ~2 chunk/s. `text_for_embedding` o'zgarsa butun korpus ~3 soat qayta hisoblanadi | GPU yo'q. Har embedding eksperimenti shuncha turadi — shuning uchun 1.1 hali sinalmagan |
| **Modern Standby** | Mashina uyquga ketganda uzoq fon jarayonlari o'ladi | OS sozlamasi. Yumshatish: barcha skriptlar uzilishdan tiklanadi (`run_fetch` yuklanganlarni o'tkazib yuboradi, `index.py` upsert idempotent) |
| **Korpusda rus tilidagi matn yo'q** | Rus tilidagi savol javobni faqat ko'p tilli embedding orqali topadi; sparse tomon umuman ishlamaydi, ya'ni gibridning yarmi yo'qoladi | lex.uz dan `lang=4` (o'zbek lotin) versiyasi olingan. Rus versiyasini qo'shish korpusni ikki baravar kattalashtiradi va yuqoridagi ikkita cheklovga taqaladi |

---

## 5. Ustuvorlik

Agar loyiha davom ettirilsa, shu tartibda:

| Navbat | Ish | Sabab |
|---|---|---|
| 1 | 3.1 va 3.2 — rate limiting va API kalit | Deploy qilishdan oldin majburiy, ikkalasi ham bir necha qator |
| 2 | 1.3 — ikkinchi modda raqami | Sabab aniq, tuzatish kichik, natija darhol o'lchanadi |
| 3 | 2.1 — eval yorliqlari ro'yxatga aylansin | Bu tuzatilmasa, keyingi o'lchovlar noto'g'ri xato ko'rsatib turaveradi |
| 4 | 1.2 — so'zlashuv lug'ati | Eng ko'p foydalanuvchiga ta'sir qiladigan bo'shliq |
| 5 | 3.3 — birlik testlari | Yuqoridagilarni xavfsiz qilish uchun |
| 6 | 1.1 — dense tomon | Eng qimmati, eng oxirida |
