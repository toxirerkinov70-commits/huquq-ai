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
rioya qiladi — katta guruhlar (4, 5, 7) uchun bu bir necha kun degani.

To'liq hujjat 10-bosqichda yoziladi.
