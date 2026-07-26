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

To'liq hujjat 10-bosqichda yoziladi.
