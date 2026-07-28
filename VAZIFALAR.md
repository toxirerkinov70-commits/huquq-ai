# Qolgan vazifalar — yangi seans uchun topshiriq

Bu fayl loyihani davom ettiradigan yangi Claude Code seansi uchun yozilgan.
Avval `HOLAT.md` ni o'qing — u tizimning hozirgi holatini tushuntiradi.

**Sana:** 2026-07-28 · **Oxirgi commit:** `a12cc73` · **12 bosqichdan 12 tasi ishlaydi**

---

## 0. Boshlashdan oldin bilishingiz shart

Bu qoidalar tajribada olingan. Ularni buzsangiz ish qaytadan bajarilishi kerak
bo'ladi yoki loyiha to'xtaydi.

| # | Qoida | Nega |
|---|---|---|
| 1 | **lex.uz ga so'rovlar orasida 20 soniya kuting** | `robots.txt` da `Crawl-delay: 20`. Client buni avtomatik bajaradi. Tezlashtirsangiz IP bloklanadi. |
| 2 | **`HF_HUB_OFFLINE=1` qo'ying** | `sentence-transformers` har ishga tushganda Hugging Face Hub'ga versiya so'rovi yuboradi. Ketma-ket ko'p jarayon ishlatilsa Hub ulanishni yopadi va model lokal keshda bo'lsa ham yuklanmaydi. |
| 3 | **Embedding lokal modelda** | `EMBED_PROVIDER=local`. Gemini bepul tarifi kuniga 1 000 embedding — bu korpus uchun 20 kun. |
| 4 | **`text_for_embedding` ni o'zgartirsangiz butun korpus qayta embedding qilinadi** | Embedding keshi shu maydonning xeshiga bog'langan. `heading` va sparse tomonini o'zgartirish esa bepul — dense vektorlar keshdan keladi. |
| 5 | **LLM kuniga 20 so'rov beradi (har model uchun alohida)** | Eval'ni `ENABLE_QUERY_EXPANSION=false` bilan ishlating — u LLM'ga umuman tegmaydi. |
| 6 | **`data/raw/*.html` hech qachon o'zgartirilmaydi** | Asl manba. Parser xatosi topilsa `run_extract.py` ni qayta ishga tushiring, qayta yuklash shart emas. |
| 7 | **Indexatsiyadan oldin `bash scripts/backup.sh`** | Buzilgan yangilanishdan snapshot orqali qaytish mumkin. |
| 8 | **Host'da `index.py` yoki `eval/run.py` ishlatishdan oldin backend konteynerini to'xtating** | Ikkalasi ham embedding modelini xotiraga yuklaydi, 8 GB da sig'maydi. |
| 9 | **Yangi hujjat indexlagandan keyin `python scripts/build_vocab.py`** | Agentik rejimning "bazada bu tushuncha yo'q" tekshiruvi shu lug'atga tayanadi. Yangilamasangiz yangi qo'shilgan atama hali ham yo'q bo'lib ko'rinadi. |
| 10 | **Modern Standby** | Mashina uxlaganda fon jarayonlari o'ladi — bu seansda ham ikki marta sodir bo'ldi. Barcha skriptlar uzilishdan tiklanadi, lekin uzun ishlarni kuzatib turing va uzoq jarayonlarni `python -u` bilan ishga tushiring, aks holda log bufferda qolib ketadi. |
| 11 | **Har bosqichdan keyin commit** | CLAUDE.md talabi. |

---

## 1. Vazifalar jadvali

| # | Vazifa | Muhimligi | Vaqt |
|---|---|---|---|
| 1 | Dense tomon jadvalli moddalarda ko'r | o'rtacha | dasturlash + ~2 soat qayta index |
| 2 | Eval to'plamini kengaytirish va yorliqlarni tuzatish | o'rtacha | ~2 soat |
| 3 | Prezident/hukumat hujjatlari (4 va 5-guruh) | past | kunlar |
| 4 | Kirill hujjatlarni sinash | past | ~1 soat |

---

## Vazifa 1 — Dense tomon ba'zi savollarda umuman ko'r

Gibrid qidiruvning qolgan zaif joyi. 33 va 51-savollarda sparse nishonni 2-3
o'rinda topadi, dense esa top-20 ga ham kiritmaydi, natijada RRF uni pastga
tushiradi (ikkala ro'yxatda ham o'rtacha turgan nomzod bitta ro'yxatda birinchi
turgandan yuqori ball oladi).

Sabab: modda matni jadval va raqamlarga to'la bo'lsa, uning o'rtacha vektori
mavzuni ifodalamaydi.

**Sinab ko'rilgan va yordam bermagan** (qaytadan urinmang):
- Fusion havzasini chuqurlashtirish (20 → 100 → 400): recall umuman o'zgarmadi
- `RRF_K` ni pasaytirish (60 → 3): bitta savolni tuzatib boshqasini buzadi
- Hujjat bo'yicha cheklov: recall 0.96 → 0.91 ga **tushdi**

**Keyingi urinish uchun g'oya:** `parser/lex/chunk.py` dagi `_embedding_body()`
hozir jadvalni 600 belgigacha qisqartiradi. Buning o'rniga jadval qatorlaridan
**raqamlarni olib tashlab, faqat qator nomlarini** qoldirish kerak ("Banklar",
"Budjet tashkilotlari"), chunki semantik signal o'sha yerda, raqamlarda emas.
Saqlangan `text` to'liq qoladi, javobda jadval baribir to'liq ko'rsatiladi.

Diqqat: bu `text_for_embedding` ni o'zgartiradi, ya'ni 22 513 chunk qaytadan
embedding qilinadi (lokal model, ~2 chunk/s ≈ 3 soat). Fon rejimida ishga
tushiring va Modern Standby ni hisobga oling.

---

## Vazifa 2 — Eval to'plami

70 savol endi tizimni yetarli darajada qiynamayapti (recall@10 = 1.00), va
bitta yorliq noto'g'ri.

1. **2-savolning yorlig'i.** "Qasddan odam o'ldirish uchun qanday jazo
   belgilangan?" uchun faqat JK 97-modda to'g'ri deb belgilangan. Endi bazada
   Oliy sud Plenumining aynan shu mavzudagi qarori ham bor va u yuqori chiqadi —
   bu mazmunan to'g'ri. Eval bir savolga bir nechta to'g'ri javobni qabul
   qiladigan qilinsa (`doc_id`/`article_no` juftliklari ro'yxati), bu xato
   yo'qoladi.
2. **9-guruh uchun savollar yo'q.** 185 ta Oliy sud hujjati qo'shildi, lekin
   eval'da ularni sinaydigan savol yo'q. Kamida 10 ta qo'shing.
3. Umumiy hajmni 100 savolgacha kengaytiring.

---

## Vazifa 3 — Prezident va hukumat hujjatlari

4-guruh (Prezident hujjatlari) va 5-guruh (hukumat qarorlari) hali qo'shilmagan
— bu ~10 800 hujjat. CLAUDE.md rejasida ular bor.

Amaliy normalarning katta qismi shu yerda: "bond ombori" savoli aynan shuning
uchun bazada topilmadi va live qidiruvga tushdi.

Har guruhdan keyin eval'ni qayta ishlating va recall pasaymaganini tekshiring.
Yuklash uzoq davom etadi (20 s/hujjat → 10 800 hujjat ≈ 60 soat), shuning uchun
bo'lib-bo'lib bajaring: `--group 4` ni avval `--max-pages` bilan sinab ko'ring.

---

## Vazifa 4 — Kirill hujjatlar

Transliteratsiya funksiyasi yozilgan, lekin hech qachon ishlamagan: 1 283
hujjatning hammasi lotin yozuvida chiqdi. Eski hujjatlarda `lang=3` (kirill)
versiyasi bor. Bittasini qo'lda yuklab, `extract` va `chunk` to'g'ri
ishlashini tekshiring.

---

## 2. Foydali buyruqlar

```bash
docker compose up -d                     # qdrant + backend
bash scripts/backup.sh                   # snapshot

ENABLE_QUERY_EXPANSION=false HF_HUB_OFFLINE=1 python eval/run.py
python eval/run.py --mode dense          # gibrid qancha foyda berayotganini ko'rish

python parser/run_update.py --window today --dry-run
python scripts/index.py --chunk-ids data/update_chunks.txt
python scripts/build_vocab.py            # indexatsiyadan keyin

curl http://localhost:8000/api/updates
curl -X POST http://localhost:8000/api/chat/agentic \
  -H 'Content-Type: application/json' \
  -d '{"question":"...","stream":false}'
```

---

## 3. Kod xaritasi

| Fayl | Vazifa |
|---|---|
| `parser/lex/client.py` | HTTP client: robots.txt, kesh, backoff |
| `parser/lex/discover.py` | Qidiruv sahifalari, ASP.NET pagination, 9 guruh |
| `parser/lex/extract.py` | HTML → Markdown, modda ajratish, sup raqamlar |
| `parser/lex/chunk.py` | Modda → chunk, preamble fallback, `heading` maydoni |
| `parser/lex/watch.py` | Rasmiy e'lonlar tasmasi, qamrov bo'yicha tasniflash |
| `parser/lex/diff.py` | Ikki Markdown versiyani solishtirish |
| `parser/run_update.py` | Yangilanish orkestratori, xavfsizlik chegaralari |
| `backend/app/scheduler.py` | APScheduler: kunlik 06:00, haftalik, oylik |
| `backend/app/services/aliases.py` | Hujjat nomi detektori (reyestrdan) |
| `backend/app/services/sparse.py` | BM25, n-gramma, sarlavha og'irligi |
| `backend/app/services/retrieval.py` | Dense, sparse, RRF, modda detektori |
| `backend/app/services/coverage.py` | "Bazada bunday tushuncha bormi?" tekshiruvi |
| `backend/app/services/generate.py` | System prompt, qisman javob qoidasi |
| `backend/app/services/tools.py` | 5 ta vosita, live lex.uz, yangilanish navbati |
| `backend/app/services/agentic.py` | Function calling bilan javob |
| `scripts/index.py` | Qdrant indexatsiyasi, `--chunk-ids` bilan tanlab |
| `scripts/build_vocab.py` | Korpus lug'ati (agentik rejim uchun) |
