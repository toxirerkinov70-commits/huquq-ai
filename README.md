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

To'liq hujjat 10-bosqichda yoziladi.
