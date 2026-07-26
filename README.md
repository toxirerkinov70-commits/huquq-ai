# Huquqiy Hybrid-RAG

O'zbekiston Respublikasi qonunchiligi bo'yicha savol-javob tizimi. Manba: lex.uz.

## Dev muhitni ishga tushirish

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # kalitlarni to'ldiring

docker compose up -d          # Qdrant
uvicorn backend.app.main:app --reload
```

Tekshiruv: `curl http://localhost:8000/health`

## Hujjatlar reyestrini yig'ish

```bash
python parser/run_discover.py --group 1   # Konstitutsiya
python parser/run_discover.py --group 2   # Kodekslar
```

Guruhlar: 1 Konstitutsiya, 2 Kodekslar, 3 Qonunlar, 4 Prezident hujjatlari,
5 Hukumat qarorlari, 6 Sud amaliyoti, 7 Idoraviy hujjatlar, 8 Xalqaro hujjatlar.

Natija `data/registry.jsonl` da, `doc_id` bo'yicha idempotent. Javoblar `data/cache/`
da keshlanadi, shuning uchun qayta ishga tushirish tarmoqqa chiqmaydi.

lex.uz `robots.txt` da `Crawl-delay: 20` e'lon qilingan va client shu qiymatga
rioya qiladi.

## Hujjat matnlarini yuklash

```bash
python parser/run_fetch.py --group 2          # bitta guruh
python parser/run_fetch.py                    # reyestrdagi hammasi, qiymat tartibida
python parser/run_fetch.py --limit 50         # sinov uchun
```

Sahifalar `data/raw/{doc_id}.html` ga xom holda saqlanadi va hech qachon
o'zgartirilmaydi. Yuklangan fayl qayta yuklanmaydi, shuning uchun skript uzilib
qolsa qoldigan joyidan davom etadi. Xatolar `data/failed.jsonl` ga yoziladi va
oxirida bir marta qayta urinib ko'riladi.

`--concurrency` standart holatda 1. Uni oshirish robots.txt da e'lon qilingan
tezlikni buzadi va IP bloklanish xavfini tug'diradi — ongli qaror bo'lsagina
ishlating. 429 javobi kelsa client o'zi sekinlashadi.

Guruhlar hajmi (`status=Y&minor=N` filtri bilan, 2026-07 holatiga):

| Guruh | Hujjat | Ketma-ket vaqt |
|---|---:|---:|
| 1 Konstitutsiya | 1 | ~20 s |
| 2 Kodekslar | 20 | ~7 daq |
| 3 Qonunlar | 562 | 3.1 soat |
| 4 Prezident hujjatlari | 3 526 | 19.6 soat |
| 5 Hukumat qarorlari | 4 588 | 25.5 soat |
| 6 Sud amaliyoti | 565 | 3.1 soat |
| 7 Idoraviy hujjatlar | 1 216 | 6.8 soat |
| 8 Xalqaro hujjatlar | 1 510 | 8.4 soat |

## Matn ajratish va chunking

```bash
python parser/run_extract.py                    # yuklangan hammasi
python parser/run_extract.py --group 2
python parser/run_extract.py --doc-id -111453   # bitta hujjat
```

Uch qatlam hosil bo'ladi:

| Fayl | Mazmun |
|---|---|
| `data/raw/{doc_id}.html` | lex.uz dan kelgan asl sahifa, o'zgartirilmaydi |
| `data/markdown/{doc_id}.md` | frontmatter + `#` bo'lim / `##` bob / `###` modda |
| `data/chunks.jsonl` | metadata bilan modda darajasidagi chunklar |

Skript reyestrni ham boyitadi: `adopted_date`, `effective_date`, `okoz`, `tsz`,
`script` va modda soni hujjat sahifasidan olinadi.

Chunk `source_url` da modda anchor'i bo'ladi (`...#-154738`), ya'ni havola
to'g'ridan-to'g'ri o'sha moddaga olib boradi.

## Qdrant'ga indexatsiya

```bash
python scripts/index.py                 # chunks.jsonl dagi hammasi
python scripts/index.py --group 2       # bitta guruh
python scripts/index.py --recreate      # kolleksiyani qaytadan qurish
```

Kolleksiya ikkita vektor saqlaydi: `dense` (768, cosine) va `sparse` (BM25,
Qdrant `IDF` modifikatori bilan). Hammasi `on_disk` — 8 GB RAM uchun majburiy.
Payload indekslari: `doc_id`, `doc_type`, `act_type`, `article_no`, `okoz`,
`tsz`, `status`, `group`.

Embedding natijalari `data/embeddings/` da keshlanadi, shuning uchun qayta
indexlash API'ga qayta chiqmaydi va pul ketmaydi. Nuqta identifikatori
`chunk_id` dan hosil qilinadi, ya'ni upsert idempotent.

### Embedding qayerda hisoblanadi

`EMBED_PROVIDER` ikki qiymat oladi:

| Qiymat | Model | Cheklov |
|---|---|---|
| `local` (standart) | `intfloat/multilingual-e5-base` | Yo'q — shu mashinada ishlaydi |
| `gemini` | `gemini-embedding-001` | Bepul tarifda kuniga 1 000 so'rov |

Gemini bepul tarifi bu korpus uchun yaramaydi: 7 430 chunkni indexlash 7 kun
talab qiladi (`EmbedContentRequestsPerDayPerProjectPerModel-FreeTier` = 1000).
Shuning uchun standart holatda lokal model ishlatiladi — u bir marta yuklab
olinadi (~1.1 GB) va keyin internet ham, pul ham kerak emas.

O'zbek tilida uchta lokal model o'lchandi (10 ta savol, ground truth bilan):

| Model | O'lchov | recall@5 | MRR |
|---|---|---:|---:|
| `multilingual-e5-base` | 768 | 0.80 | 0.595 |
| `multilingual-e5-small` | 384 | 0.50 | 0.417 |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | 0.10 | 0.114 |

e5 modellari hujjat va so'rovni turlicha belgilashni talab qiladi
(`passage:` va `query:` prefikslari) — bu kodda hisobga olingan.

### Sparse kodlash haqida

O'zbek tili agglyutinativ: so'rovda `poytaxt`, matnda `poytaxti` — aniq so'z
mosligi ishlamaydi. Shuning uchun sparse vektorga to'liq so'z bilan birga
uning 4-belgili n-grammalari ham (kichikroq og'irlik bilan) qo'shiladi.
To'liq korpusda o'lchangan natija: MRR 0.327 → 0.475.

## Backend va frontend

```bash
uvicorn backend.app.main:app --reload
```

Brauzerda `http://localhost:8000` — chat interfeysi shu yerda ochiladi.

| Metod | Yo'l | Vazifa |
|---|---|---|
| POST | `/api/chat` | Savol → SSE streaming javob va manbalar |
| POST | `/api/search` | Faqat retrieval natijasi (debug) |
| GET | `/api/agents` | Agent rejimlari |
| GET | `/api/documents` | Hujjatlar reyestri |
| GET | `/api/document/{doc_id}` | Bitta hujjat va uning moddalari |
| GET | `/health` | Holat va indexdagi nuqtalar soni |

Qidiruv quvuri: savolni suhbat tarixiga qarab mustaqil savolga aylantirish →
LLM orqali 2 ta muqobil formulirovka → dense va sparse qidiruv → RRF birlashtirish
→ modda raqami bo'yicha to'g'ridan-to'g'ri filtr → LLM rerank (top-6) → javob.

## Baholash

```bash
python eval/run.py                  # gibrid
python eval/run.py --mode sparse    # embedding API'siz ishlaydi
python eval/run.py --verbose
```

`recall@5`, `recall@10` va MRR ni savol turlari (semantik, modda raqami,
kodeks nomi) bo'yicha alohida hisoblaydi.

To'liq hujjat 10-bosqichda yoziladi.
