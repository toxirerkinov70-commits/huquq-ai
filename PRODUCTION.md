# Production'ga chiqish

Tizim texnik jihatdan ishlaydi. Bu hujjat — **haqiqiy foydalanuvchilarni qo'yishdan
oldin** nima qolganini sanaydi. Har band uchun hozirgi holat va qayerdan boshlash
ko'rsatilgan.

**Holat sanasi:** 2026-08-02 · 1 283 hujjat · 22 513 chunk · 169 test

---

## 0. Hozir nima ishlayapti

Bularni qaytadan qilish kerak emas:

| | |
|---|---|
| Qidiruv | Gibrid (dense + sparse + RRF), `recall@5 = 0.95` asosiy to'plamda, `0.77` qiyin to'plamda |
| Javob | Manbali, kontekstda javob yo'q bo'lsa ochiq aytadi |
| Kirish | Google (popup oqimi, tirik hisob bilan tekshirilgan) va telefon + SMS kodi |
| Hisoblar | Tariflar, kvota, sarf hisobi, buyurtma oqimi, operator paneli |
| Xavfsizlik | Bearer token, API kalit, rate limit, body limit, root'siz konteyner |
| Avtomatik yangilanish | Scheduler konteyneri, har vazifadan oldin Qdrant snapshot |
| Deploy | `docker-compose.prod.yml` + Caddy (TLS), CI GitHub Actions'da |

---

## 1. To'siqlar — bularsiz ishga tushirib bo'lmaydi

| # | Ish | Hozir nima | Nima qilinadi | Qayerda |
|---|---|---|---|---|
| 1.1 | **SMS provayderi** | `SMS_PROVIDER=console` — kod faqat jurnalga yoziladi. Production'da tizim `console` ni **rad etadi** | eskiz.uz da hisob, shablon tasdig'i, `ESKIZ_EMAIL` / `ESKIZ_PASSWORD` | `backend/app/services/otp.py` |
| 1.2 | **Server va domen** | Hammasi lokal noutbukda. Caddy konfiguratsiyasi yozilgan, lekin **hech qachon ishlamagan** | VPS olish, `DOMAIN` ni `.env` ga yozish, prod compose'ni ko'tarish, TLS ishlaganini tekshirish | `deploy/Caddyfile`, `docker-compose.prod.yml` |
| 1.3 | **Shaxsiy ma'lumotlar joylashuvi** | Telefon raqami, e-pochta va suhbat tarixi saqlanadi. Serverni qayerda ijaraga olish hali tanlanmagan | O'zbekiston fuqarolarining shaxsiy ma'lumotlari mamlakat hududidagi serverda saqlanishi talabini **yurist bilan aniqlash** va shunga qarab hosting tanlash. Bu 1.2 dan oldin hal qilinishi kerak — keyin ko'chirish qimmat | — |
| 1.4 | **Huquqiy hujjatlar** | `docs/legal/` da uch fayl bor, tizim amalda nima qilishiga mos yozilgan, lekin **yuridik kuchga ega emas** | Yurist ko'rib chiqsin; `[KOMPANIYA NOMI]` kabi bo'sh joylar to'ldirilsin | `docs/legal/oferta.md`, `maxfiylik.md`, `saqlash.md` |
| 1.5 | **Production sozlamalari** | `.env` dev qiymatlarida | `AUTH_SECRET`, `QDRANT_API_KEY`, `ADMIN_API_KEY` to'ldirilsin; `CORS_ORIGINS` aniq domen; `ENVIRONMENT=production` | README 13-bo'lim |
| 1.6 | **LLM pullik tarifi** | Bepul tarif: model boshiga ~20 so'rov/kun, bitta savol 3 ta so'rov yeydi → **~40 savol/kun** | Gemini'da billing yoqilsin. Bepul tarifda 10 ta foydalanuvchi ham sig'maydi | `MONETIZATSIYA.md` 4-bo'lim |

---

## 2. Birinchi hafta ichida

To'siq emas, lekin ishga tushgandan keyin darhol kerak bo'ladi.

| # | Ish | Nega | Qayerda |
|---|---|---|---|
| 2.1 | **Monitoring va ogohlantirish** | Hozir **umuman yo'q**. Qdrant yiqilsa yoki kvota tugasa — hech kim bilmaydi, foydalanuvchi xato ko'radi | `/health` ni tashqi tekshiruvga ulash + xato bo'lganda telegram xabari |
| 2.2 | **To'lov integratsiyasi** | Buyurtma oqimi to'liq, lekin bankdan "to'landi" signali yo'q — operator qo'lda faollashtiradi. 10 ta buyurtmagacha chidasa bo'ladi, keyin yo'q | Payme/Click callback `orders.activate` ni chaqirsin · `MONETIZATSIYA.md` 5-bo'lim |
| 2.3 | **Zaxira nusxa tashqi joyda** | `scripts/backup.py` Qdrant snapshot va SQLite dump oladi, lekin **o'sha mashinada**. Disk yo'qolsa hammasi ketadi | Kunlik nusxa S3 yoki boshqa serverga · `scripts/backup.py` |
| 2.4 | **Tiklashni sinash** | Snapshot olinadi, lekin undan **hech qachon tiklanmagan**. Sinalmagan zaxira — zaxira emas | Toza muhitda snapshot'dan tiklab, qidiruv ishlashini tekshirish |
| 2.5 | **Yuklama testi** | Bir vaqtda bir nechta foydalanuvchi bilan **hech qachon sinalmagan**. Lokal embedding modeli 1.1 GB, har so'rovda CPU'da ishlaydi | 5–10 parallel savol bilan sinash; `EMBED_CONCURRENCY` va `UVICORN_WORKERS` ni shunga qarab sozlash |
| 2.6 | **Kechikish — 20–24 s** | 2026-08-02 da o'lchandi. Foydalanuvchi bu qadar kutmaydi | Rerank'ni lokal cross-encoder'ga o'tkazish: vaqt −15…25 s, xarajat −60% · `KAMCHILIKLAR.md` 3.7 |

---

## 3. Korpus

Hozirgi 1 283 hujjat quyidagicha taqsimlangan:

| Guruh | Nima | Soni |
|---|---|---|
| 1 | Konstitutsiya | 1 |
| 2 | Kodekslar | 20 |
| 3 | Qonunlar | 562 |
| 9 | Sud amaliyoti (Oliy sud, Plenum, iqtisodiy sud) | 700 |

**Yo'q:** Prezident hujjatlari (`act_type=3`), hukumat qarorlari (`act_type=4`),
idoraviy hujjatlar (`act_type=5`), xalqaro hujjatlar (`act_type=6`).

Amaliy savollarning katta qismi aynan nizom va tartiblarga tayanadi — ular hukumat
qarorlarida. Ya'ni korpus to'liq emas va tizim ba'zi savollarga "bazada topilmadi"
deydi, holbuki norma mavjud.

Har guruh uchun ketma-ketlik o'zgarmaydi:

```bash
python parser/run_discover.py --group 4
python parser/run_fetch.py --group 4
python parser/run_extract.py --group 4
python scripts/index.py --group 4
python eval/run.py            # recall pasaymaganini tekshir
```

Narxi: `Crawl-delay: 20` sababli yuklash sekin, embedding esa CPU'da ~2 chunk/s. Katta
guruhlar bir necha kun oladi — bir kechada bo'lmaydi. 4-guruhdan boshlang, 5-guruh eng
katta va eng kam qiymatli.

---

## 4. Sifat va texnik qarz

| # | Ish | Izoh |
|---|---|---|
| 4.1 | Metadata bazasi SQLite'ligicha | Dastlabki reja Postgres edi. Bir nechta worker bitta SQLite fayliga yozadi; WAL yoqilgan, lekin bu yuklama ostida sinalmagan |
| 4.2 | So'zlashuv tili bo'shlig'i | "Meni ishdan haydashdi" → MK 174-modda. Qiyin to'plamda `recall@5 = 0.33`. Sinonim lug'ati kerak · `KAMCHILIKLAR.md` 1.2 |
| 4.3 | Bitta savolda ikkita modda raqami | `detect_article_no()` faqat birinchisini oladi. Tuzatish kichik · 1.3 |
| 4.4 | Ikki kodeks chegarasidagi savollar | `recall@5 = 0.00`. Savolni bo'lish kerak · 1.4, 1.5 |
| 4.5 | Kirill hujjatlar sinalmagan | Transliteratsiya kodi yozilgan, lekin hech qachon ishlamagan — 1 283 hujjatning hammasi lotin yozuvida chiqdi · 3.4 |
| 4.6 | Eval yorlig'i bitta juftlik | To'g'ri javob bir nechta bo'lishi mumkin, eval buni xato deb sanaydi · 2.1 |
| 4.7 | README skrinshotlari eskirgan | `docs/ui-*.png` va `ui-tour.gif` eski logotipli interfeysni ko'rsatadi |

---

## 5. Tavsiya etilgan tartib

1. **1.3** (ma'lumot joylashuvi) — hosting tanlashdan oldin, aks holda keyin ko'chiriladi
2. **1.6 → 1.5 → 1.2** — pullik LLM, sozlamalar, server. Shundan keyin tizim tashqarida turadi
3. **1.1 va 1.4** — SMS va yurist. Ikkalasi tashqi tomonga bog'liq, parallel boshlang
4. **2.1 va 2.3** — monitoring va zaxira. Foydalanuvchi kelishidan oldin
5. **2.6** — kechikish. Birinchi foydalanuvchilar aynan shundan shikoyat qiladi
6. **3-bo'lim** — korpusni to'ldirish. Uzoq, lekin fon rejimida ketaveradi
7. **2.2** — to'lov. Qo'lda faollashtirish 10–20 buyurtmagacha yetadi
8. **4-bo'lim** — qidiruv sifati. Doimiy ish, tugamaydi

---

## 6. Ishga tushirish kuni tekshiriladigan ro'yxat

- [ ] `ENVIRONMENT=production`, barcha kalitlar to'ldirilgan
- [ ] `CORS_ORIGINS` — faqat o'z domeningiz
- [ ] `/health` `ok` qaytaradi, `points` soni kutilganday
- [ ] Google orqali kirish ishlaydi (Authorized JavaScript origins ga **production domen** qo'shilgan)
- [ ] Telefon orqali kirish ishlaydi, haqiqiy SMS keladi
- [ ] Qdrant tashqaridan ochiq emas (`127.0.0.1:6333`)
- [ ] Snapshot olindi va undan tiklash sinaldi
- [ ] `docs/legal/` yurist tasdig'idan o'tgan, bo'sh joylar to'ldirilgan
- [ ] Scheduler konteyneri tirik va vazifalar ro'yxatda (`docker logs`)
- [ ] Xato bo'lganda sizga xabar keladigan yo'l bor
