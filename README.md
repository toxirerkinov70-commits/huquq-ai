# Huquqiy Hybrid-RAG

O'zbekiston Respublikasi qonunchiligi bo'yicha savol-javob tizimi. Manba: lex.uz.

## Dev muhitni ishga tushirish

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # kalitlarni to'ldiring

docker compose up -d qdrant   # dev'da faqat Qdrant konteynerda
uvicorn backend.app.main:app --reload
```

Backend dev paytida local `venv` da ishlaydi — Docker rebuild sikli sekin va
8 GB da ortiqcha yuk. To'liq konteynerli variant "Deploy" bo'limida.

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

| Guruh | Hujjat | Ketma-ket vaqt | Qamrovda |
|---|---:|---:|---|
| 1 Konstitutsiya | 1 | ~20 s | ha |
| 2 Kodekslar | 20 | ~7 daq | ha |
| 3 Qonunlar | 562 | 3.1 soat | ha |
| 4 Prezident hujjatlari | 3 526 | 19.6 soat | yo'q |
| 5 Hukumat qarorlari | 4 588 | 25.5 soat | yo'q |
| 6 Sud amaliyoti | 565 | 3.1 soat | ha |
| 7 Idoraviy hujjatlar | 1 216 | 6.8 soat | yo'q |
| 8 Xalqaro hujjatlar | 1 510 | 8.4 soat | yo'q |

Parser sakkizala guruhni qo'llab-quvvatlaydi, lekin baza 1, 2, 3 va 6-guruh
bilan cheklangan — ya'ni Konstitutsiya, kodekslar, qonunlar va sud amaliyoti.
4, 5, 7-guruhlarning katta qismi bir martalik, vaziyatga oid hujjatlar
("falon lavozimga tayinlansin", "falon mablag' ajratilsin"): ular yangi norma
qo'shmaydi, faqat qidiruv shovqinini oshiradi.

Buning narxi bor: nizom va tartiblar bilan belgilanadigan amaliy tartib-taomil
savollariga (qanday hujjat topshiriladi, qancha to'lov) baza javob bermaydi.
Bunday holatda tizim "bazada aniq norma topilmadi" deb ochiq aytadi.

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

`eval/questions.jsonl` da 50 savol bor va ularning har biri indexlangan
21 kodeksning haqiqiy moddasiga bog'langan. Bir qism savol qiyin holatlarni
sinash uchun `tag` bilan belgilangan: yuqori indeksli modda raqamlari
(`289¹`), matni jadval bo'lgan moddalar, bir gaplik moddalar.

Savollar 21 kodeksga bog'langan, shuning uchun 562 qonun qo'shilishi ular uchun
sof shovqin — korpus kattalashishining narxini shu bilan o'lchash mumkin:

| Rejim | recall@5 (7 430 chunk) | recall@5 (20 249 chunk) | MRR |
|---|---:|---:|---:|
| hybrid | 0.98 | **0.98** | 0.869 → 0.859 |
| dense | 0.62 | 0.56 | 0.561 → 0.523 |
| sparse | 0.70 | 0.60 | 0.557 → 0.509 |

Korpus 2.7 baravar kattaydi. Sof vektor qidiruv recall@5 ni 6 punkt, sof
kalit so'z qidiruvi 10 punkt yo'qotdi — ya'ni "ma'lumot ko'paygani sari
qidiruv susayadi" degan xavotir asosli. Gibrid esa deyarli o'zgarmadi,
chunki modda raqami va hujjat nomi detektorlari nomzodlar to'plamini
reyting bosqichidan **oldin** toraytiradi: qo'shilgan hujjatlar raqobatga
umuman kirmaydi.

Modda raqamli savollarda gibrid 1.00 beradi, dense 0.08, sparse 0.00 —
gibrid arxitektura shu turdagi savollar uchun kerak.

## Deploy

```bash
docker compose up -d              # qdrant + backend
docker compose logs -f backend
```

Backend `backend/Dockerfile` dan quriladi. Ikkita narsa image ichiga
qo'yilmagan:

- **torch** CPU indeksidan o'rnatiladi. Standart wheel nvidia CUDA
  kutubxonalarini tortadi — bu mashinada ular ishlatilmaydi va image ikki
  baravardan ko'proq kattalashadi (2.0 GB o'rniga ~4.5 GB).
- **Embedding modeli** (~1.1 GB) `hf_models` volume'ida saqlanadi. U koddan
  ancha kam o'zgaradi, shuning uchun rebuild qilinganda qayta yuklanmaydi.

RAM taqsimoti (mashinada jami 8 GB): Qdrant 2 GB, backend 3 GB. Ishlayotgan
holatda backend ~1.2 GB, Qdrant ~0.2 GB egallaydi.

Indexatsiyani host'dagi `venv` dan ishlatsangiz backend konteynerini
to'xtatib turing — ikkalasi ham embedding modelini xotiraga yuklaydi va
8 GB da ular birga sig'maydi:

```bash
docker compose stop backend
python scripts/index.py --group 3
docker compose start backend
```

## Zaxira nusxa

```bash
bash scripts/backup.sh
```

Qdrant snapshot, SQLite dump va reyestr nusxasini
`data/backups/{sana}/` ga yozadi, oxirgi 5 tasini saqlaydi (`BACKUP_KEEP`).
Snapshot yuklab olingandan keyin serverdagi nusxa o'chiriladi.

Buni **indexatsiya va yangilanishdan oldin** ishlating: quvur buzilsa butun
korpusni qayta embedding qilish o'rniga snapshot'dan qaytish mumkin.
