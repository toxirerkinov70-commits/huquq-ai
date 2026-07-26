# Loyiha holati — 2026-07-27

## Qisqacha

Tizim ishlaydi. 21 hujjat (Konstitutsiya + 20 kodeks) to'liq indexlangan,
7 430 chunk Qdrant'da, qidiruv sifati o'lchandi va CLAUDE.md talablarini
qondiradi.

| Bosqich | Holat |
|---|---|
| 0. Skelet, Docker, Qdrant | Tugadi |
| 1. lex.uz reyestri | Tugadi — 21 hujjat |
| 2. HTML yuklash | Tugadi — 21/21, xatosiz |
| 3. Matn ajratish va chunking | Tugadi — 7 237 modda, 7 430 chunk |
| 4. Qdrant indexatsiya | Tugadi — 7 430/7 430 nuqta |
| 5. Gibrid retrieval | Tugadi — recall@5 = 1.00 |
| 6. Rerank va javob generatsiyasi | Tugadi |
| 7. FastAPI backend | Tugadi |
| 8. Frontend | Tugadi |
| 9-12 | Boshlanmagan |

## Qidiruv sifati (15 ta savol, `eval/questions.jsonl`)

| Rejim | recall@5 | recall@10 | MRR |
|---|---:|---:|---:|
| **hybrid** | **1.00** | **1.00** | **0.828** |
| dense | 0.60 | 0.73 | 0.523 |
| sparse | 0.60 | 0.80 | 0.467 |

Savol turlari bo'yicha (hybrid):

| Tur | n | recall@5 | MRR |
|---|---:|---:|---:|
| semantik | 7 | 1.00 | 0.810 |
| modda raqami | 5 | 1.00 | 1.000 |
| kodeks nomi | 3 | 1.00 | 0.583 |

Eng muhim natija: **modda raqamli savollarda sof vector qidiruv recall@5 = 0.00
beradi, gibrid esa 1.00.** CLAUDE.md aynan shuni bashorat qilgan edi va
modda raqami detektori shu muammoni hal qiladi.

## Sinovdan o'tgan xatti-harakatlar

- Savol → manba havolali javob: "Nikoh yoshi ... o'n sakkiz yosh (Oila kodeksi,
  15-modda)" + ishlaydigan lex.uz havolasi
- Bazada yo'q savol → "Bu savol bo'yicha bazada aniq norma topilmadi"
- Ketma-ket bog'liq 3 savol: "Uni bekor qilish..." va "Bunda xodimga qancha
  oldin..." oldingi kontekstdan to'g'ri tushunildi
- Rerank LLM ishlamay qolsa, retrieval tartibi saqlanadi (graceful degradation)

## Muhim texnik qarorlar

**Embedding lokal modelda.** Gemini bepul tarifi kuniga 1 000 embedding
so'roviga ruxsat beradi (`EmbedContentRequestsPerDayPerProjectPerModel-FreeTier`),
bu korpus uchun 7 kun degani. Shuning uchun `intfloat/multilingual-e5-base`
shu mashinada ishlaydi — kvota yo'q, pul yo'q. Uchta lokal model o'lchandi:

| Model | recall@5 | MRR |
|---|---:|---:|
| multilingual-e5-base | 0.80 | 0.595 |
| multilingual-e5-small | 0.50 | 0.417 |
| paraphrase-multilingual-MiniLM | 0.10 | 0.114 |

Butun korpusni indexlash ~53 daqiqa oldi.

**Sparse kodlashda n-grammalar.** O'zbek tili agglyutinativ: so'rovda
`poytaxt`, matnda `poytaxti`. Aniq so'z mosligi nol beradi. To'liq so'z +
4-belgili n-gramma kombinatsiyasi MRR ni 0.327 dan 0.475 ga ko'tardi.

**881 ta modda `<sup>` bilan raqamlangan** (173²-modda). Ular `article_no:
"173-2"` va `article_no_display: "173²"` sifatida saqlanadi.

## Ochiq masalalar

**LLM kvotasi.** Javob yozish `gemini-2.5-flash` da, uning bepul kunlik
chegarasi bor. Oddiy foydalanish uchun yetadi, lekin ko'p sinov qilinsa
tugaydi (2026-07-27 kuni shunday bo'ldi). Har savolga LLM chaqiruvlari soni
kamaytirildi: modda raqami yoki kodeks nomi bo'lgan savollarda so'rov
kengaytirish o'tkazib yuboriladi. `.env` da butunlay o'chirish mumkin:

```
ENABLE_QUERY_EXPANSION=false
ENABLE_RERANK=false
```

**Kirill hujjatlar sinalmagan.** Transliteratsiya funksiyasi yozilgan, lekin
21 hujjatning hammasi lotin yozuvida bo'lgani uchun haqiqiy ma'lumotda
tekshirilmagan. 4-5-guruhlarda kerak bo'ladi.

**API kalit.** `.env` da, gitignore'da, commit qilinmagan. Lekin chat orqali
ochiq yuborilgani uchun uni Google konsolida almashtirish tavsiya etiladi.

## Keyingi qadamlar

1. 9-bosqich: 3 → 6 → 4 → 5 → 7 → 8 guruhlarni qo'shish. Yuklash lex.uz
   `robots.txt` talabiga ko'ra 20 soniyalik oraliq bilan ketadi:
   3-guruh (562 qonun) ~3 soat, hammasi ~66 soat.
2. 10-bosqich: savollarni 50 tagacha kengaytirish, Docker deploy, backup.
3. 11-12-bosqichlar: avtomatik yangilanish va tool calling.

## Ishga tushirish

```bash
docker compose up -d
uvicorn backend.app.main:app --reload
# brauzerda http://localhost:8000
```
