# 12 ta yangilanish — bajarildi va sinovdan o'tdi

**Sana:** 2026-07-29 · Foydalanuvchi so'ragan 12 ta yangilanishning hammasi
kodda yozilgan, konteyner qayta build qilingan va **sinovdan o'tgan**.
Tizim holati uchun `HOLAT.md`, qolgan katta vazifalar uchun `VAZIFALAR.md`.

---

## Vazifalar ro'yxati

| # | Vazifa | Holat | Qayerda |
|---|---|---|---|
| 1 | Sahifa yangilanganda suhbat o'chmasin | Sinaldi | `app.js`: `SESSION_KEY` localStorage, startup'da `openSession(saved)`; backend `GET /api/sessions/{id}` |
| 2 | Suhbatlar tarixi bo'limi, har suhbat alohida | Sinaldi | Sidebar "Suhbatlar" ro'yxati (`loadSessions`), `GET /api/sessions`, `DELETE /api/sessions/{id}` |
| 3 | Agentlar bo'limi ochilib-yopilsin | Sinaldi | `agents-toggle` tugmasi, chevron, holat `huquq_agents_collapsed` localStorage'da |
| 4 | Qidiruv Hujjatlar bo'limidan tashqarida ham | Sinaldi | Sidebar "Qidiruv" bandi → `#search-modal` global qidiruv oynasi |
| 5 | Fonda faqat tavsif jumlasi qolsin | Sinaldi | `showEmptyState()`: "Agent rejimi" va "Imkoniyatlar" kartalari, boshqa hech narsa |
| 6 | Shriftlar sezilarli qalinroq | Sinaldi | `style.css`: body 500, sarlavhalar 700–800, tugma/nav 600–700 |
| 7 | Disclaimer javobdan ajralib tursin | Sinaldi | Har bot-javob ostida `answer-disclaimer` bloki; model disclaimer yozmaydi (`generate.py` 9-qoida), frontend `stripDisclaimer()` bilan himoya |
| 8 | Manbalar 6 → 4, aniqlik | Sinaldi | `rerank.py` TOP_N=4; `generate.py` `filter_cited_sources()`; `chat.py` 3 yo'lda ham ulangan |
| 9 | Manbalar qalin havola | Sinaldi | `renderSources`: sarlavha `<a class="source-link">` bold, lex.uz'ga ochiladi; karta bosilsa modal |
| 10 | Agent rejimi tugmasi halqa | Sinaldi | `.ring-toggle` — yoqilganda accent halqa + ichki nuqta + glow, sidebar pastida |
| 11 | Fonda "Agent rejimi" kartasi + tushuntirish | Sinaldi | Karta bosilganda `AGENT_MODE_INFO` matni modalda (markdown render) |
| 12 | Tungi/kunduzgi/tizim rejimlari | Sinaldi | `.theme-switch`, `huquq_theme` localStorage, flash'ga qarshi inline skript, `:root[data-theme="dark"]` |

---

## Sinov natijalari (2026-07-29)

**Suhbat tiklanishi.** `GET /api/sessions` 29 suhbat qaytardi, `GET
/api/sessions/{id}` xabarlarni manbalari bilan beradi. Brauzerda (Playwright)
saqlangan sessionId bilan sahifa qayta yuklanganda suhbat manbalar va
disclaimer bloki bilan qayta chizildi, sidebar'da faol suhbat belgilandi.

**Manba filtri.** Ikki savol sinaldi: "FK 125-modda" → 2 manba (FK 125 +
FK birinchi qism), "O'g'irlik jazosi" → 3 manba (JK 169, JK 54, o'g'irlik
bo'yicha Plenum qarori). Ikkalasida ham manbalar ≤4 va hammasi javobda iqtibos
qilingan moddalarga mos — iqtibossiz manba qolmadi. Rerank balli bo'yicha
qo'shimcha kesish **kerak bo'lmadi**.

**UI.** `scripts/ui_check.py` (Playwright, headless Chromium) 12 tekshiruvni
o'tkazadi: light/dark/tizim rejimlari, halqa tugma, Agentlar yig'ilishi,
global qidiruv, welcome kartalar, agent-info modali, suhbat tiklanishi,
disclaimer bloki. Natija 12/12, skrinshotlar `data/ui_shots/` da. Suhbatni
sidebar'dan o'chirish ham alohida sinaldi (ro'yxat kamaydi).

Ishga tushirish:

```bash
pip install playwright          # brauzer allaqachon bor: chromium-1228
python scripts/ui_check.py
```

---

## Eslatmalar

- Frontend ham, backend ham Docker image ichida — kod o'zgarsa
  `docker compose up -d --build backend`.
- LLM bepul tarif: har model kuniga ~20 so'rov (6 ta fallback model).
- Sinov suhbatlari bazada turibdi (`data/app.db`, ~30 ta) — xohlasangiz
  `DELETE /api/sessions/{id}` bilan tozalash mumkin.
