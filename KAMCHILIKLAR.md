# Kamchiliklar

Tizimning zaif joylari, o'lchov bilan tasdiqlangan holda. Har biri uchun sabab va
tuzatish yo'li ko'rsatilgan. Oxirgi bo'lim — tizim doirasida hal qilib bo'lmaydigan,
tashqi sharoitdan kelib chiqadigan cheklovlar.

**O'lchov sanasi:** 2026-07-29 · 22 513 chunk · `eval/run.py`
**Oxirgi tahrir:** 2026-08-02 — Google kirishi bo'yicha o'lchov (3.9)

---

## 0. 2026-08-01 da tuzatilganlar

Production'ga chiqarish oldidan o'tkazilgan audit natijasida quyidagilar hal qilindi.
Batafsil: [MONETIZATSIYA.md](MONETIZATSIYA.md) 1-bo'lim.

| Kamchilik | Nima edi | Nima bo'ldi |
|---|---|---|
| **Suhbatlar ochiq edi** | `GET /api/sessions` **barcha** foydalanuvchilar suhbatini qaytarardi; har kim har qanday sessiyani o'qishi va o'chirishi mumkin edi | `sessions.user_id`, har so'rovda egalik tekshiruvi. Begona sessiya 404 qaytaradi — mavjudligini ham bildirmaydi |
| **Autentifikatsiya yo'q edi** | Barcha endpointlar ochiq, har kim Gemini kaliti hisobidan so'rov yuborardi | Imzolangan bearer token (`POST /api/auth/anon`) va B2B uchun `X-API-Key` |
| **Rate limiting ishlamasdi** | `Limiter` e'lon qilingan, `SlowAPIMiddleware` qo'shilmagan → amalda cheklov nol | Middleware ulandi; kalit hisob bo'yicha (proksi orqasida IP hammaga bitta) |
| **Qdrant himoyasiz** | `0.0.0.0:6333`, parolsiz | `127.0.0.1:6333` + `QDRANT__SERVICE__API_KEY` |
| **Versiyalar qotirilmagan** | `requirements.txt` da bitta ham versiya yo'q | Hammasi pin qilindi, `requirements-dev.txt` ajratildi |
| **SQLite ulanish oqishi** | `with sqlite3.connect(...)` tranzaksiyani yopadi, ulanishni emas → deskriptorlar tugaydi, "database is locked" | Contextmanager ulanishni yopadi; WAL yoqildi |
| **LLM fallback qaytmasdi** | `_model_index` faqat oshardi → bitta foydalanuvchi kvotani tugatsa, hammaga eng zaif model qolardi | `LLM_PRIMARY_RETRY_MINUTES` dan keyin asosiy model qayta sinaladi |
| **Ko'p worker bilan ishlamasdi** | Scheduler `lifespan` da → 4 worker = 4 ta parallel crawl, lex.uz bloklaydi | Scheduler alohida konteyner (`python -m backend.app.scheduler`) |
| **Embedding bo'g'izi** | Bitta `asyncio.Lock` — barcha savollar navbatda | `EMBED_CONCURRENCY` semaphore |
| **Sarf hisobi yo'q edi** | Token hisobi global, kim sarflagani noma'lum | Har so'rov uchun meter, `usage_events` jadvali, USD xarajat |
| **Kuzatuv yo'q edi** | `structlog` bog'liqlikda bor, kodda ishlatilmagan | structlog + request-id har qatorda + access log |
| **SSE xatosi tashqariga chiqardi** | `str(exc)` — provayder xato matni brauzerga | Umumiy xabar + `request_id`, tafsilot jurnalda |
| **Fayl yuklash cheklovsiz** | 15 MB base64, autentifikatsiyasiz | Body limit middleware + tarif bo'yicha ruxsat va hajm |
| **Korpus deploy yo'li yo'q** | `data/` gitignore'da, serverda korpus qayerdan kelishi aytilmagan | `scripts/export_corpus.py` / `import_corpus.py` |
| **Testlar yo'q edi** | 0 ta birlik testi | 72 ta test, GitHub Actions CI |
| **Kesh eskirardi** | `lru_cache` hech qachon yangilanmasdi → yangilangan hujjat restartgacha ko'rinmasdi | `corpus.py` — mtime kuzatuvi, chunk fayli byte-offset indeksi |
| **Path traversal ehtimoli** | `report_date` fayl yo'liga tekshirilmasdan qo'yilardi | `^\d{4}-\d{2}-\d{2}$` |
| **Rus tili yarim ishlardi** | Kirill savolda sparse tomon nolga tushardi | Rus savol aniqlanadi va o'zbekcha variantga tarjima qilinib qidiriladi |
| **Huquqiy hujjatlar yo'q** | Oferta, maxfiylik siyosati, saqlash muddati — yo'q | `docs/legal/` (yurist tasdig'i talab qilinadi) |
| **Konteyner root ostida** | — | `uid 10001`, healthcheck, Caddy + TLS |

**Qolgan kamchiliklar** quyida — ular qidiruv sifatiga oid va tashqi cheklovlarga
bog'liq, ya'ni audit doirasida hal qilinmaydi.

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
| 3.1 | Rate limiting amalda ishlamayapti | ✅ **tuzatildi** 2026-08-01 |
| 3.2 | API kalit himoyasi yo'q | ✅ **tuzatildi** 2026-08-01 |
| 3.3 | Birlik testlari yo'q | ✅ **tuzatildi** — 72 ta test, `pytest` |
| 3.4 | **Kirill hujjatlar sinalmagan** | Transliteratsiya funksiyasi yozilgan, lekin **hech qachon ishlamagan**: 1 283 hujjatning hammasi lotin yozuvida chiqdi. Ya'ni bu kod yo'li tekshirilmagan. Test yozish uchun kirill-only hujjat topish kerak |
| 3.5 | **To'lov integratsiyasi yo'q** | Buyurtma oqimi to'liq ishlaydi (muddat, chegirma, buyurtma raqami, faollashtirish), lekin bankdan "to'landi" signali yo'q — operator qo'lda tasdiqlaydi. Payme/Click callback'i `orders.activate` ni chaqirsa bas. Batafsil: [MONETIZATSIYA.md](MONETIZATSIYA.md) 5-bo'lim |
| 3.8 | **SMS provayderi ulanmagan** | `SMS_PROVIDER=console` — kod jurnalga yoziladi. Eskiz uchun kod yozilgan, lekin hisob va shablon tasdig'i kerak. Production'da `console` **rad etiladi**, ya'ni ulanmasa ro'yxatdan o'tish ishlamaydi |
| 3.9 | Google orqali kirish | ✅ **ishlaydi** 2026-08-02 — popup oqimida, tirik hisob bilan tekshirildi. Yo'l nega o'zgartirilgani quyida |
| 3.6 | **Huquqiy hujjatlar yurist tasdig'isiz** | `docs/legal/` dagi uch hujjat tizim amalda nima qilishiga muvofiq yozilgan, lekin **yuridik kuchga ega emas**. Ishga tushirishdan oldin yurist ko'rib chiqishi shart |
| 3.7 | **Kechikish — 82 soniya** | Bitta savol uchun o'lchandi (2026-08-01, `mehnat` rejimi). Kvota cheklovi emas: jurnalda 429 yo'q. Sabab — CPU'da 5 ta embedding va 3 ta ketma-ket LLM chaqiruvi. Foydalanuvchi uchun bu **juda uzoq**. Choralar va ularning narxi: [MONETIZATSIYA.md](MONETIZATSIYA.md) 2.2-bo'lim. Eng foydalisi — rerank'ni lokal cross-encoder'ga o'tkazish (xarajat −60%, vaqt −15…25 s). **2026-08-02 qayta o'lchov:** ikki savol `umumiy` rejimda 20.4 s va 23.7 s. Ya'ni 82 s har doimgi holat emas — lekin 20 s ham ko'p |

### 3.9 — Google kirishi: nima o'lchandi

Holat 2026-08-02 ga. Console tomonida kamchilik topilmadi, muammo Google'ning tugma
endpointida.

| Tekshiruv | Natija |
|---|---|
| `GOOGLE_CLIENT_ID` formati | 72 belgi, to'g'ri, kesilmagan |
| Klient Google'da mavjudmi | **Ha**. Soxta ID `invalid_client` beradi, bu ID bermaydi |
| Klient turi | **Web application**. `127.0.0.1:1234` va `oob` redirect'lari rad etildi — desktop klient emas |
| `http://localhost:8000` JS origin sifatida ro'yxatdami | **Ha**. `storagerelay://http/localhost:8000` redirect'i bilan avtorizatsiya endpointi kirish sahifasiga o'tkazadi; `localhost:9999` va begona domen esa rad etiladi |
| `GET /api/auth/config` | `google_enabled: true` |
| Auth testlari | 17 ta, hammasi o'tadi |
| `accounts.google.com/gsi/button` | **403**, konsolda `[GSI_LOGGER]: The given origin is not allowed for the given client ID` |
| Headless va oddiy brauzer | Farqi yo'q, ikkalasida ham 403 |

Ya'ni Google'ning ikki qatlami bir-biriga zid javob beradi: OAuth avtorizatsiya endpointi
origin'ni tan oladi, GIS tugma endpointi tanimaydi. Console'da qo'shiladigan sozlama
qolmagan.

**Chora:** tugmani render qiladigan `gsi/button` yo'lidan voz kechildi. Kirish
`google.accounts.oauth2.initTokenClient` popup oqimiga o'tkazildi — u aynan yuqorida
tekshirilgan va **ishlaydigan** `storagerelay` redirect'idan foydalanadi. Backend endi
ID token bilan bir qatorda access token'ni ham qabul qiladi va uni `tokeninfo` orqali
tekshiradi (`aud` bizning klientmi — asosiy shart).

Natija: 2026-08-02 da haqiqiy Google hisobi bilan kirish muvaffaqiyatli o'tdi.

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

Xavfsizlik va infratuzilma bandlari 2026-08-01 da yopildi. Qolgani — qidiruv sifati:

| Navbat | Ish | Sabab |
|---|---|---|
| 1 | 3.8 — SMS provayderini ulash (Eskiz) | Bo'lmasa hech kim ro'yxatdan o'ta olmaydi |
| 2 | 3.7 — kechikishni tushirish (lokal rerank) | 82 s da foydalanuvchi kutmaydi. Xarajatni ham 60% kamaytiradi |
| 3 | 3.6 — huquqiy hujjatlarni yurist tasdig'idan o'tkazish | Ishga tushirishdan oldin majburiy |
| 4 | 1.3 — ikkinchi modda raqami | Sabab aniq, tuzatish kichik, natija darhol o'lchanadi |
| 5 | 2.1 — eval yorliqlari ro'yxatga aylansin | Bu tuzatilmasa, keyingi o'lchovlar noto'g'ri xato ko'rsatib turaveradi |
| 6 | 1.2 — so'zlashuv lug'ati | Eng ko'p foydalanuvchiga ta'sir qiladigan bo'shliq |
| 7 | 1.4 va 1.5 — ko'p nishonli savollar | Savolni bo'lish kerak |
| 8 | 1.1 — dense tomon | Eng qimmati (~3 soat qayta embedding), eng oxirida |
