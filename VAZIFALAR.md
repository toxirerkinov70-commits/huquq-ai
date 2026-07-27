# Qolgan vazifalar — yangi seans uchun topshiriq

Bu fayl loyihani davom ettiradigan yangi Claude Code seansi uchun yozilgan.
Avval `HOLAT.md` ni o'qing — u tizimning hozirgi holatini tushuntiradi.

---

## 0. Boshlashdan oldin bilishingiz shart

Bu qoidalar tajribada olingan. Ularni buzsangiz ish qaytadan bajarilishi kerak
bo'ladi yoki loyiha to'xtaydi.

| # | Qoida | Nega |
|---|---|---|
| 1 | **lex.uz ga so'rovlar orasida 20 soniya kuting** | `robots.txt` da `Crawl-delay: 20`. Client buni avtomatik bajaradi — `LEX_REQUEST_DELAY` ni pasaytirish yordam bermaydi. Tezlashtirsangiz IP bloklanadi va loyiha to'xtaydi. |
| 2 | **Embedding lokal modelda, uni Gemini'ga qaytarmang** | Gemini bepul tarifi kuniga 1 000 embedding so'rovi — bu korpus uchun 7 kun. `EMBED_PROVIDER=local` bo'lib turishi kerak. |
| 3 | **Embedding modelini o'zgartirsangiz, butun kolleksiyani qayta quring** | Vektorlar boshqa fazoda bo'ladi, eski va yangisini aralashtirib bo'lmaydi: `scripts/index.py --recreate`. |
| 4 | **LLM kuniga 20 so'rov beradi (har model uchun alohida)** | Tizim modellar zanjiri bo'ylab o'zi almashadi (`gemini_llm_fallbacks`). Ko'p sinov qilsangiz kvota tugaydi — ertaga tiklanadi. |
| 5 | **lex.uz sahifalashi POST orqali** | Oddiy `?page=2` ishlamaydi: ASP.NET WebForms, `__VIEWSTATE` bilan POST qilinadi. `parser/lex/discover.py` da hal qilingan. |
| 6 | **`data/raw/*.html` hech qachon o'zgartirilmaydi** | U asl manba. Parser xatosi topilsa, `run_extract.py` ni qayta ishga tushiring — qayta yuklash shart emas. |
| 7 | **Har bosqichdan keyin commit qiling** | CLAUDE.md talabi. |

---

## 1. Vazifalar jadvali

Ustuvorlik bo'yicha tartiblangan. "Vaqt" — mashina ishlaydigan vaqt, sizniki emas.

| # | Vazifa | Bosqich | Vaqt | Bog'liqlik |
|---|---|---|---|---|
| 1 | Qonunlar matnini yuklash va indexlash | 9 | ~3.5 soat | — |
| 2 | Sud amaliyotini qo'shish | 9 | ~3.5 soat | — |
| 3 | Baholashni 50 savolga kengaytirish | 10 | dasturlash | 1, 2 |
| 4 | Docker deploy va backup | 10 | dasturlash | — |
| 5 | Prezident hujjatlari | 9 | ~22 soat | — |
| 6 | Hukumat qarorlari | 9 | ~28 soat | — |
| 7 | Idoraviy hujjatlar | 9 | ~8 soat | — |
| 8 | Xalqaro hujjatlar | 9 | ~10 soat | — |
| 9 | Avtomatik yangilanish | 11 | dasturlash | 4 |
| 10 | Tool calling | 12 | dasturlash | — |

---

## Vazifa 1 — Qonunlarni qo'shish (562 hujjat)

Reyestr **allaqachon yig'ilgan** (`data/registry.jsonl` da 562 ta `group: 3`
yozuvi bor), shuning uchun `run_discover.py` ni qayta ishlatish shart emas.

```bash
python parser/run_fetch.py --group 3      # ~3.1 soat, fonda ishlatilsin
python parser/run_extract.py --group 3    # ~2 daqiqa
python scripts/index.py --group 3         # ~30 daqiqa (lokal embedding)
python eval/run.py                        # recall pasaymaganini tekshiring
```

**Tekshiruv:** `data/failed.jsonl` bo'sh yoki juda kichik; Qdrant nuqtalari
soni `chunks.jsonl` qatorlari soniga teng; `eval/run.py` da recall@5 pasaymagan.

**Diqqat:** yuklash uzoq davom etadi va uzilishi mumkin. Skript uzilishdan
davom etadi — qayta ishga tushirsangiz yuklangan fayllarni o'tkazib yuboradi.
Tarmoq xatolari normal, backoff ularni yutadi.

**Kutilayotgan muammo:** qonunlar orasida kirill yozuvidagilari bo'lishi
mumkin. `parser/lex/extract.py` da `detect_script()` va `transliterate()`
funksiyalari yozilgan, lekin haqiqiy ma'lumotda **hali sinalmagan**. Kirill
hujjat uchrasa, chunk sifatini qo'lda tekshiring.

---

## Vazifa 2 — Sud amaliyotini qo'shish (565 hujjat)

CLAUDE.md bu javob sifatini keskin oshirishini yozgan.

```bash
python parser/run_discover.py --group 6   # ~10 daqiqa
python parser/run_fetch.py --group 6      # ~3.1 soat
python parser/run_extract.py --group 6
python scripts/index.py --group 6
```

**Diqqat:** 6-guruh boshqa URL ishlatadi (`/uz/search/court`), chunki sud
hujjatlari alohida bo'limda. Bu `parser/lex/discover.py` dagi `GROUPS` da
sozlangan, lekin **hali sinalmagan** — birinchi sahifa to'g'ri parse
bo'lganini tekshiring.

Sud qarorlarining tuzilishi kodekslardan farq qiladi (moddalar o'rniga
bandlar bo'lishi mumkin). Agar `run_extract.py` "no articles found"
ogohlantirishini bersa, `parser/lex/extract.py` ni moslashtirish kerak.

---

## Vazifa 3 — Baholashni kengaytirish

Hozir `eval/questions.jsonl` da 15 savol bor va recall@5 = 1.00. Bu juda
kichik namuna — 50 tagacha kengaytiring.

- Har bir savol uchun `doc_id` va `article_no` ni **haqiqiy ma'lumotdan**
  tekshiring (`data/markdown/*.md` ni o'qing), taxmin qilmang.
- Turlar nisbati saqlansin: taxminan yarmi semantik, qolgani modda raqami
  va kodeks nomi bo'yicha.
- Yangi guruhlar qo'shilgach, ulardan ham savollar kiriting.
- Qiyin holatlarni qo'shing: yuqori indeksli moddalar (`173²`), jadvalli
  moddalar (soliq stavkalari), juda qisqa moddalar.

Keyin `eval/run.py` natijasiga qarab tuning qiling: chunk hajmi
(`parser/lex/chunk.py` da `MAX_TOKENS`), RRF `RRF_K`, `top-k`, rerank prompti.

---

## Vazifa 4 — Docker deploy va backup

1. `backend/Dockerfile` yozing. E'tibor bering: lokal embedding modeli
   (~1.1 GB) image ichiga kirishi yoki volume orqali ulanishi kerak, aks
   holda har ishga tushirishda qayta yuklab olinadi.
2. `docker-compose.yml` ga backend servisini qo'shing.
3. `scripts/backup.sh` — Qdrant snapshot (`POST /collections/{name}/snapshots`)
   va SQLite dump.
4. `README.md` ni toza muhitda tekshiring.

**Diqqat:** mashinada 8 GB RAM va Qdrant 2 GB oladi. Backend konteynerida
lokal model yana ~1.5 GB oladi. Sig'ishini tekshiring.

---

## Vazifalar 5-8 — Qolgan guruhlar

| Guruh | Hujjat | Yuklash | Izoh |
|---|---:|---:|---|
| 4. Prezident hujjatlari | 3 526 | ~19.6 soat | Amaliy normalar |
| 5. Hukumat qarorlari | 4 588 | ~25.5 soat | Nizom va tartiblar — amaliy savollar uchun qimmatli |
| 7. Idoraviy hujjatlar | 1 216 | ~6.8 soat | Eng kam qiymatli |
| 8. Xalqaro hujjatlar | 1 510 | ~8.4 soat | Oxirida |

Har biri uchun bir xil to'rt qadam (discover → fetch → extract → index).
Har guruhdan keyin `eval/run.py` ni ishga tushirib, recall pasaymaganini
tekshiring — korpus kattalashgani sari shovqin ortadi.

Bu guruhlar bir necha kunlik ish. Kechasi fonda qoldirish mumkin, skriptlar
uzilishdan tiklanadi.

---

## Vazifa 9 — Avtomatik yangilanish (11-bosqich)

CLAUDE.md da batafsil yozilgan. Asosiy nuqtalar:

- `parser/lex/watch.py` — `/uz/search/official?lang=4&pub_date=today` sahifasi
- `parser/lex/diff.py` — ikki Markdown versiyani `difflib` bilan solishtirish,
  `###` sarlavhalari bo'yicha qaysi modda o'zgarganini aniqlash
- Faqat o'zgargan moddalarni qayta embedding qilish
- Kuchini yo'qotgan hujjatlar **o'chirilmaydi**, `status: "R"` qo'yiladi
- `backend/app/scheduler.py` — APScheduler
- Xavfsizlik chegaralari: bir kunda 50 dan ortiq hujjat o'zgarsa yoki matn
  50% dan ko'p qisqarsa — to'xtash va tasdiq so'rash

`content_hash` allaqachon har bir Markdown faylning frontmatter'ida bor —
o'zgarishni aniqlash shu orqali ishlaydi.

---

## Vazifa 10 — Tool calling (12-bosqich)

LLM ga vositalar berish: qidiruv, modda olish, hujjat ro'yxati. CLAUDE.md
ning oxirgi bo'limiga qarang.

---

## 2. Foydali buyruqlar

```bash
# ishga tushirish
.\start.ps1

# holat
curl http://localhost:8000/health
curl http://localhost:6333/collections/uz_legal

# sifat
python eval/run.py --verbose
python eval/run.py --mode dense     # gibrid qanchalik foyda berayotganini ko'rish

# qayta qurish (embedding modeli o'zgarsa)
python scripts/index.py --recreate
```

---

## 3. Kod xaritasi

| Fayl | Vazifa |
|---|---|
| `parser/lex/client.py` | HTTP client: robots.txt, kesh, backoff |
| `parser/lex/discover.py` | Qidiruv sahifalari, ASP.NET pagination |
| `parser/lex/extract.py` | HTML → Markdown, modda ajratish, sup raqamlar |
| `parser/lex/chunk.py` | Modda → chunk, uzunlarini bo'lish |
| `backend/app/services/embedding.py` | Lokal va Gemini embedding |
| `backend/app/services/sparse.py` | BM25 + n-gramma kodlash |
| `backend/app/services/retrieval.py` | Dense, sparse, RRF, modda detektori |
| `backend/app/services/llm.py` | Gemini wrapper, model almashish |
| `backend/app/services/rerank.py` | LLM rerank |
| `backend/app/services/generate.py` | System prompt va javob |
| `scripts/index.py` | Qdrant indexatsiyasi |
