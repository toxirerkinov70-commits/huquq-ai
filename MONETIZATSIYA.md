# Monetizatsiya

Loyihadan qanday daromad olish mumkin, tizimning **o'zida nima qurilgan** va nima
qolgan. Hujjat ikki qismdan iborat: birinchisi — kodda mavjud tuzilma, ikkinchisi —
biznes rejasi. Ular ajratilgan, chunki birinchisi tayyor va tekshirilgan, ikkinchisi
esa qaror va tajriba masalasi.

**Sana:** 2026-08-01 · 1 283 hujjat · 22 513 chunk · recall@5 = 0.95

---

## Mundarija

1. [Tizimda nima qurilgan](#1-tizimda-nima-qurilgan)
2. [Birlik iqtisodiyoti](#2-birlik-iqtisodiyoti)
3. [Tariflar](#3-tariflar)
4. [Daromad yo'llari](#4-daromad-yollari)
5. [To'lovni ulash](#5-tolovni-ulash)
6. [Bosqichma-bosqich reja](#6-bosqichma-bosqich-reja)
7. [Kuzatiladigan ko'rsatkichlar](#7-kuzatiladigan-korsatkichlar)
8. [Risklar](#8-risklar)

---

## 1. Tizimda nima qurilgan

Monetizatsiyaning texnik poydevori loyihaga kiritildi. Hech qanday tarif, chegara yoki
hisob-kitob qo'lda hisoblanmaydi.

### 1.1 Ro'yxatdan o'tish va hisoblar

Kirish ekrani bank ilovasidagidek bosqichli:

```
Telefon raqam (+998, faqat mavjud operator kodlari)
  → SMS kod (6 xona, 3 daqiqa, 5 urinish, qayta yuborish taymeri)
  → Ism ("Xayrli kech, Toxirbek" shu yerdan keladi)
  → Ommaviy oferta — matn ko'rsatiladi, galochkasiz davom etib bo'lmaydi
  → Suhbat
```

Yoki bitta bosishda **Google** orqali. Har ikki yo'l ham bitta hisobga olib keladi:
telefon bilan ro'yxatdan o'tgan odam keyin Google bilan kirsa, pochtasi mos bo'lsa
o'sha hisob topiladi.

**Oferta darvozasi haqiqiy.** U faqat ekranda emas — `/api/chat` da ham tekshiriladi
(`403 terms_required`). Galochka — mijoz o'zi haqida aytgan da'vo, shuning uchun
serverda qayd etiladi: kim, qachon va **ofertaning qaysi versiyasini** qabul qilgani.
Ofertani o'zgartirsangiz `TERMS_VERSION` ni yangilaysiz — hamma qaytadan qabul qiladi.
Bu huquqiy xizmat uchun majburiy: aks holda hujjatda "roziман" deb yozilgan, lekin
odam ko'rmagan matn qoladi.

| Xavfsizlik chorasi | Nima uchun |
|---|---|
| Faqat `+998` va haqiqiy operator kodlari (20, 33, 50, 55, 77, 88, 90–99) | Chet el raqamlariga SMS yuborish — bevosita pul yo'qotish |
| Kod **xeshlab** saqlanadi (raqam bilan tuzlangan) | Baza nusxasi ro'yxatdan o'tayotgan hisoblarni bermasin |
| 60 s qayta yuborish oralig'i, kuniga 10 ta kod | SMS bombardimoniga qarshi |
| 5 ta urinish, keyin kod kuyadi | Kodni brute-force qilib bo'lmasin |
| `console` provayderi production'da **rad etiladi** | Jurnalga yozilgan kod — jurnalga kirgan har kim uchun ochiq eshik |

Ikki xil kirish yo'li bor:

| Usul | Kim uchun | Sarlavha |
|---|---|---|
| Bearer token | Brauzer, mobil | `Authorization: Bearer v1...` |
| API kalit | Integratsiya mijozi (Biznes tarifi) | `X-API-Key: hq_live_...` |

Kalitlar ochiq saqlanmaydi — faqat SHA-256 xeshi. Kalit bir marta, yaratilganda
ko'rsatiladi.

**Yaratuvchi hisobi.** `OWNER_EMAILS` dagi pochta bilan kirgan hisob avtomatik
`owner` tarifiga o'tadi: cheksiz savol, barcha rejimlar, API kalitlari. Bu tarif
narxlar sahifasida ko'rinmaydi va uni sotib bo'lmaydi.

### 1.2 Sarf o'lchovi (metering)

Har bir so'rov uchun **Meter** ochiladi va shu so'rov davomida qilingan barcha LLM
chaqiruvlari unga yig'iladi — quvurning qaysi qatlamida bo'lishidan qat'i nazar
(`rewrite` → `expand` → `rerank` → `generate`). Streaming javobda ham ishlaydi:
generator ichida meter qayta bog'lanadi.

Yozib boriladi: `user_id`, endpoint, tur, model, LLM chaqiruvlari soni, kirish/chiqish
tokenlari, **USD dagi xarajat**, kechikish.

```sql
-- usage_events jadvali
user_id | endpoint   | kind     | prompt_tokens | output_tokens | cost_usd | latency_ms | day
```

Avval token hisobi butun jarayon bo'yicha bitta global raqam edi — u xizmat qancha
sarflaganini aytardi, lekin **kim** sarflaganini emas. Hisob-faktura yozib bo'lmaydigan
holat.

### 1.3 Chegaralar

`backend/app/services/plans.py` — tariflar shu yerda, ma'lumot sifatida. Bitta joydan
uchta narsa boshqariladi: kvota tekshiruvi, narxlar sahifasi va testlar.

Chegara ishlashi:

```
Savol keldi
  → tarif aniqlanadi (muddati o'tgan bo'lsa avtomatik bepulga tushadi)
  → funksiya ruxsati (agentik rejim? fayl yuklash? fayl hajmi?)   → 402
  → kunlik savol chegarasi                                        → 429 + Retry-After
  → ish boshlanadi
```

Kunlik chegara **Toshkent vaqti** bo'yicha yarim tunda yangilanadi, UTC bo'yicha emas —
aks holda foydalanuvchining bepul limiti ertalab soat 5 da tiklanardi.

Salomlashish kunlik chegarani yemaydi (aks holda "salom" bepul foydalanuvchining 5 ta
savolidan birini yeb qo'yardi), lekin u ham bepul emas: uch baravar kengroq alohida
chegara qo'llanadi.

### 1.4 Operator paneli

`ADMIN_API_KEY` qo'yilgan bo'lsa ochiladi; qo'yilmagan bo'lsa endpointlar **umuman
mavjud emas** (401 emas, 404 — mavjudligini ham bildirmaydi).

| Endpoint | Nima beradi |
|---|---|
| `GET /api/admin/stats` | Faol foydalanuvchilar, savollar, xarajat, MRR, yalpi marja |
| `GET /api/admin/users` | Ro'yxat: tarif, bugungi faollik, umumiy xarajat |
| `GET /api/admin/users/{id}` | Bitta hisob: sarf tarixi, kalitlari |
| `POST /api/admin/users/plan` | Tarifni o'zgartirish (to'lov kelganda) |
| `POST /api/admin/users/status` | Hisobni bloklash |
| `POST /api/admin/users/service` | Integratsiya mijozi uchun hisob + kalit |

`stats` javobida `mrr_uzs` va `gross_margin_uzs` bor — ya'ni "bu oy qancha ishlab
topdim va qancha sarfladim" savoliga bitta so'rov bilan javob olinadi.

### 1.5 Foydalanuvchi tomoni

- Yon panelda tarif nomi, kunlik chegara va sarflangan ulush (progress bar)
- «Tariflar» oynasi — `GET /api/plans` dan o'qiydi, kodda takrorlanmaydi
- Chegara tugaganda yoki funksiya tarifga kirmasa — tushunarli xabar va tariflar oynasi
- `GET /api/usage` — foydalanuvchi o'z sarfini ko'ra oladi
- Ommaviy oferta va maxfiylik siyosati havolalari

---

## 2. Birlik iqtisodiyoti

### 2.1 Bitta savol nechaga tushadi

**Bu taxmin emas — ishlab turgan tizimda o'lchangan** (2026-08-01, `mehnat` rejimi,
hamroh qidiruvlar va rerank yoqilgan holda):

| | Qiymat |
|---|---:|
| Savol | "Ish beruvchi xodimni qanday hollarda ishdan bo'shatishi mumkin?" |
| Javob | 3 310 belgi, 4 manba |
| **Kirish token** | **10 563** |
| **Chiqish token** | **1 756** |
| **Xarajat** | **$0.00756 ≈ 97.5 so'm** |
| Birinchi token | 78.4 s |
| To'liq javob | 82.6 s |

Taqsimot (kod: `chat.py` → `_retrieve`):

| Chaqiruv | Ulushi | Izoh |
|---|---|---|
| `expand_query` | kichik | Aniq modda so'ralsa — o'tkazib yuboriladi |
| `rerank` | **~60%** | 20 nomzod × 900 belgi — **eng qimmat qism** |
| `generate_answer` | ~35% | 4 chunk × 2500 belgi |
| `rewrite_followup` | kichik | Faqat suhbat tarixi bo'lsa |

Narx `PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` sozlamalaridan olinadi
(standart 0.30 / 2.50 USD).

> ⚠️ **Hisob-faktura yozishdan oldin `ai.google.dev/pricing` dan tekshirib, `.env` da
> yangilang.** Tizim o'zgartirilgan narxni darhol hisobga oladi — kod o'zgartirish
> shart emas.

Haqiqiy raqamni istalgan payt tizimning o'zidan olish mumkin:
```bash
curl -s localhost:8000/api/admin/stats -H "X-Admin-Key: $ADMIN_API_KEY" | jq '.totals'
```

> **Eslatma — o'lchov qanday buzilgan edi.** Birinchi o'lchovda bitta savol 104 000
> token ko'rsatdi. Sabab: Gemini streaming'da har bo'lakda `usageMetadata` qaytaradi va
> undagi raqamlar **jamlanma**, ya'ni ularni qo'shib borish bitta javobni o'nlab marta
> hisoblab yuborardi. Tuzatildi (`llm.py`), test bilan qotirildi
> (`tests/test_llm_usage.py`). Agar bu topilmaganida, bu yerdagi barcha narxlar
> 10 barobar noto'g'ri bo'lardi.

### 2.2 Xarajat va kechikishni kamaytirish

**Kechikish xarajatdan muhimroq muammo.** 82 soniya — foydalanuvchi ketadigan vaqt.
Sabab: 5 ta embedding CPU'da + 3 ta ketma-ket LLM chaqiruvi. Kvota cheklovi emas —
jurnalda bitta ham 429 yo'q.

| Chora | Xarajatga ta'siri | Kechikishga ta'siri | Narxi |
|---|---|---|---|
| `rerank` ni lokal cross-encoder'ga o'tkazish (`BAAI/bge-reranker-v2-m3`) | −60% | −15…25 s | +600 MB RAM |
| `ENABLE_QUERY_EXPANSION=false` | −5% | −5…15 s | Sifat biroz tushadi |
| `ENABLE_RERANK=false` | −60% | −15…25 s | Sifat sezilarli tushadi |
| Hamroh qidiruvlarni (`facets`) parallel emas, shartli qilish | 0 | −5…10 s | Vaziyat tahlili to'liqligi |
| GPU li server (yoki embedding API) | 0 | −10…20 s | +$30–80/oy |
| System prompt uchun context caching | −20% | kichik | Ish |

Birinchi ikkitasi eng foydali nisbatga ega. **Ishga tushirishdan oldin lokal rerank'ni
qilish tavsiya etiladi** — u ham pulni, ham vaqtni bir yo'la kamaytiradi.

Xarajatning o'zi hozir muammo emas (97 so'm/savol), shuning uchun optimizatsiya
kechikish uchun qilinadi, pul uchun emas.

### 2.3 Doimiy xarajat

| Modda | Oyiga |
|---|---|
| VPS (4 vCPU, 8-16 GB RAM) | $20–40 |
| Domen + TLS (Caddy avtomatik) | ~$1 |
| Zaxira nusxa saqlash | $2–5 |
| **Jami** | **$25–50** |

### 2.4 Marja

Standart tarif (39 000 so'm) sotib olgan foydalanuvchi oyiga o'rtacha 100 ta savol
bersa:

```
Daromad:  39 000 so'm
Xarajat:  100 × 97.5 = 9 750 so'm
Marja:    29 250 so'm  (75%)
```

Chegarani **to'liq** ishlatsa (50 × 30 kun = 1 500 savol):
```
Xarajat: 146 000 so'm → zarar
```

Shuning uchun kunlik chegara — bu shunchaki qadoq emas, **xarajat nazorati**. Amalda
foydalanuvchilarning 95% chegaraning 10–20% ini ishlatadi. Buni faza 1 da o'lchash
kerak; `GET /api/admin/stats` da `top_users` aynan shuning uchun bor.

---

## 3. Tariflar

Kodda: `backend/app/services/plans.py`. O'zgartirish — bitta faylga tegish.

| | Bepul | Standart | Pro | Biznes |
|---|---|---|---|---|
| **Narx / oy** | 0 | 39 000 so'm | 99 000 so'm | 890 000 so'm |
| Kunlik savol | 5 | 50 | 300 | 2 000 |
| Agent rejimlari | ✅ | ✅ | ✅ | ✅ |
| Hujjat yuklash | ❌ | ✅ 10 MB | ✅ | ✅ |
| Agentik rejim (lex.uz jonli) | ❌ | ❌ | ✅ | ✅ |
| API kalitlari | ❌ | ❌ | ❌ | ✅ 10 ta |
| Suhbat tarixi | 14 kun | 6 oy | 1 yil | 3 yil |
| Qidiruv natijalari (max k) | 10 | 20 | 30 | 50 |

**Nega shunday chegaralangan:**

- *Agentik rejim Pro'dan* — u lex.uz ga real so'rov yuboradi (`Crawl-delay: 20`).
  Bepul tarifda ochib qo'yish IP blokiga olib keladi va butun loyihani to'xtatadi.
- *Hujjat yuklash Standartdan* — har fayl to'g'ridan-to'g'ri Gemini'ga ketadi, ya'ni
  eng qimmat operatsiya. Bepul tarifda bu cheksiz pul yo'qotish yo'li.
- *Bepulda 5 ta savol* — tanishish uchun yetarli, suiiste'mol uchun kam. Kuniga
  ~450 so'm/foydalanuvchi.

---

## 4. Daromad yo'llari

Real potensial bo'yicha tartiblangan.

### 🥇 1. B2B — korxona yuristlari va yuridik firmalar

**Eng ko'p pul shu yerda va ko'pchilik buni e'tibordan qoldiradi.**

Yakka fuqaro huquqiy savolga oyiga 39 000 so'm to'lashni istamaydi. Korxona yuristi
esa **bir soat vaqtini tejash uchun** $50 to'laydi — uning bir soati shundan qimmat.

Nima qo'shish kerak (hozir yo'q):
- Korxonaning **o'z hujjatlarini** indexlash — ichki nizomlar, shablon shartnomalar.
  Savol qonun + korxona qoidalari bo'yicha birga javob oladi. Texnik jihatdan bu
  mavjud quvurning `act_type` o'rniga `tenant_id` bilan ishlatilishi.
- Jamoa akkauntlari (bir hisob — bir necha foydalanuvchi)
- Shartnoma tekshirish hisoboti PDF shaklida

**Narx:** $80–300/oy (Biznes tarifi = 890 000 so'm ≈ $69, kattaroq mijozga alohida).
**Maqsad:** 12 oyda 20–30 mijoz → **oyiga $2 000–6 000**.

Bu erishish mumkin bo'lgan raqam va bitta odam uchun jiddiy daromad.

### 🥈 2. Hujjat generatsiyasi

**Hozir yo'q va eng katta yagona imkoniyat.**

Odam "qonun nima deydi" degan javobga pul to'lamaydi — u Google'da bepul. **"Menga
hozir kerak bo'lgan hujjatni yozib ber"** degan narsaga to'laydi:

- Mehnat shartnomasi, ijara shartnomasi, oldi-sotdi shartnomasi
- Sudga da'vo arizasi, shikoyat, e'tiroz
- Pretenziya, tushuntirish xati, ariza
- Buyruq va nizom shabloni

Korpus va normalar bor — hujjatni **normaga tayangan holda** yaratish texnik jihatdan
qiyin emas. Bir martalik to'lov (15 000–50 000 so'm) yoki Pro tarif ichida.

Bu funksiya B2C konversiyasini bir necha barobar oshiradi.

### 🥉 3. B2C obuna

Klassik freemium. O'zbekistonda B2C to'lov konversiyasi past — kutilganidan 3–5 barobar
kam bo'ladi.

**Realistik:** 5 000 ro'yxatdan o'tgan foydalanuvchidan 1–2% to'laydi = 50–100 obunachi
= oyiga **2–10 mln so'm ($150–800)**.

B2B'dan kam, lekin ishonch, portfolio va B2B uchun kirish nuqtasi yaratadi.

### 4. API sifatida sotish

Retrieval — tayyor mahsulot, `X-API-Key` bilan ishlaydi. Mijozlar:

| Mijoz turi | Nima uchun kerak |
|---|---|
| Buxgalteriya dasturlari (1C hamkorlari) | "Bu operatsiya soliq kodeksiga mos keladimi?" |
| HR/kadrlar platformalari | Mehnat kodeksi bo'yicha tekshiruv |
| Banklar, compliance | Normativ talablarni tekshirish |
| Advokatlik CRM'lari | Ish bo'yicha norma qidirish |

**Narx:** 1 000 so'rov uchun $30–80. Eng kam mehnat talab qiladigan daromad — API
allaqachon ishlaydi.

### 5. Institutsional yo'l

| Imkoniyat | Izoh |
|---|---|
| **IT Park rezidentligi** | Soliq imtiyozlari jiddiy. Daromad emas, lekin **xarajatni keskin kamaytiradi**. Birinchi qadamlardan biri. Shartlarni `it-park.uz` dan tekshiring |
| Adliya vazirligi, hokimliklar | Fuqarolarga huquqiy yordam — davlat dasturlariga mos. Sekin, lekin katta shartnoma |
| Xalqaro grantlar (UNDP, EI) | "Access to justice" yo'nalishi. $20k–100k |
| Universitetlar, huquq fakultetlari | Talabalar uchun litsenziya |

### 6. Kichik oqimlar

- **Telegram bot** — O'zbekistonda eng past kirish to'sig'i. API tayyor
- **SEO** — har modda uchun sahifa. Organik trafikning asosiy manbai
- **White-label** — advokatlik byurosi o'z brendi ostida: o'rnatish $1 000–3 000 + oylik

---

## 5. To'lovni ulash

**To'lovdan oldingi butun oqim tayyor va ishlaydi.** Yetishmayotgani — bankdan kelgan
"to'landi" signali.

Mijoz nima ko'radi:

```
Tariflar  →  karta bosiladi  →  Muddat: 1 / 3 / 6 / 12 oy
                                 (chegirma: 0% / 5% / 10% / 20%)
                              →  To'lov usuli: Payme · Click · Uzum · Bank o'tkazmasi
                              →  Buyurtma: HQ-3BA2FEA932, 111 000 so'm, "Kutilmoqda"
```

Buyurtma bazaga tushadi (`orders`), holati foydalanuvchiga Sozlamalar → Tarif
bo'limida ko'rinadi. Ikki marta bosilsa yangi buyurtma yaratilmaydi — bittasi qaytadi.

Operator to'lovni tasdiqlaydi:
```bash
curl -X POST http://localhost:8000/api/admin/orders/HQ-3BA2FEA932/confirm \
  -H "X-Admin-Key: $ADMIN_API_KEY"
```

Shu daqiqada tarif faollashadi, amal muddati qo'yiladi, funksiyalar ochiladi.
Muddatidan oldin uzaytirilsa — qolgan kunlar yo'qolmaydi, ustiga qo'shiladi.

**Bank ulanganda o'zgaradigan yagona narsa:** Payme/Click callback'i shu `confirm`
mantiqini (`orders.activate`) chaqiradi. Qolgan hamma narsa — narx, muddat, chegirma,
faollashtirish, tugash, avtomatik bepulga qaytish — allaqachon shu yerda.

Kerak bo'ladigan qo'shimchalar:
1. `POST /api/billing/payme` va `/api/billing/click` — provayder callback'lari va imzo tekshiruvi
2. `payments` jadvali — tranzaksiya tarixi (buyurtma bor, to'lov yozuvi hali yo'q)
3. To'lov usullarida `available: true` qilish (`routers/orders.py`)

---

## 6. Bosqichma-bosqich reja

### Faza 0 — Production hardening ✅ bajarildi

Sessiya egaligi, autentifikatsiya, rate limiting, kvota, metering, Qdrant himoyasi,
versiyalar, testlar, huquqiy hujjatlar, deploy tuzilmasi.

### Faza 1 — Yopiq beta (2026-08 → 2026-09)

- 50–100 taklif qilingan foydalanuvchi: huquqshunos tanishlar, talabalar, tadbirkorlar
- Bepul, lekin **usage hisobi ishlaydi** — kim qancha, qanday savol berayotgani o'lchanadi
- Har hafta 20 ta tasodifiy javobni **yurist bilan birga** tekshirish

> Bu fazaning asosiy maqsadi — **sifatni o'lchash**, foydalanuvchi yig'ish emas.
> `recall@5 = 0.95` — bu o'zi yozgan 73 ta savolda. Haqiqiy foydalanuvchi savollari
> butunlay boshqacha bo'ladi va bu raqam tushadi. Buni oldindan bilish kerak.

### Faza 2 — Ochiq ishga tushirish (2026-10 → 2026-11)

- Telegram bot + veb
- Payme/Click integratsiyasi, freemium tariflar yoqiladi
- **Hujjat generatsiyasi** — birinchi pulli funksiya
- SEO sahifalari

### Faza 3 — B2B (2026-12 → 2027-03)

- 5 ta korxonaga bepul pilot
- Korxona hujjatlarini indexlash
- Jamoa akkauntlari
- **Asosiy daromad manbai shu yerdan boshlanadi**

### Faza 4 — API va white-label (2027-04 dan)

Hujjatlashtirilgan API, hamkorlik dasturi, integratsiyalar.

---

## 7. Kuzatiladigan ko'rsatkichlar

Hammasi `GET /api/admin/stats` dan olinadi.

| Ko'rsatkich | Nima uchun | Xavfli chegara |
|---|---|---|
| **Bir savolning o'rtacha xarajati** | Marja shundan | > 0.02 USD — quvurni tekshiring |
| **Faol foydalanuvchi / kun** | O'sish | — |
| **Savol / foydalanuvchi / kun** | Chegara to'g'ri qo'yilganmi | > 20 — chegara past |
| **Yalpi marja** (`gross_margin_uzs`) | Biznes ishlayaptimi | < 50% — tarif noto'g'ri |
| **`top_users` xarajati** | Suiiste'mol | Bittasi jamining >20% i bo'lsa — tekshiring |
| **Konversiya (bepul → pullik)** | Mahsulot qiymati | < 1% — mahsulot yetarli emas |
| **p95 kechikish** (`avg_latency_ms`) | Tajriba | > 15 s — foydalanuvchi ketadi |

---

## 8. Risklar

| Risk | Og'irligi | Nima qilish |
|---|---|---|
| **Huquqiy javobgarlik** | 🔴 Yuqori | Oferta javobgarlikni cheklaydi, har javobda ogohlantirish bor. Sug'urta haqida o'ylash kerak |
| **Aniqlik haqiqiy savollarda pasayadi** | 🔴 Yuqori | Faza 1 da yurist bilan tekshiruv **majburiy** |
| **Shaxsiy ma'lumot chet el serveriga ketishi** | 🟠 O'rta-yuqori | Maxfiylik siyosatida ochiq yozilgan. Yurist bilan aniqlashtiring; kerak bo'lsa lokal LLM |
| **Raqobat (wakil.ai va boshqalar)** | 🟠 O'rta | Ustunlik: 1 283 hujjatli korpus + avtomatik yangilanish + modda raqami detektori. Takrorlash uchun haftalar kerak (lex.uz 20 s kechikish) |
| **Gemini'ga bog'liqlik** | 🟡 O'rta | Fallback zanjiri bor, lekin hammasi bitta provayder. Ikkinchi provayder abstraksiyasi kerak |
| **lex.uz strukturasi o'zgarishi** | 🟡 O'rta | Xavfsizlik chegaralari bor (50 hujjat/kun, 50% qisqarish) |
| **B2C konversiyasi past** | 🟡 O'rta | Shuning uchun B2B birinchi o'rinda |

---

## Bitta jumlada

**B2C chat — vitrina, pul B2B'da va hujjat generatsiyasida.** Loyihani "hamma uchun
bepul huquqiy chat" sifatida ishga tushiring — bu ishonch va trafik beradi — lekin
daromadni birinchi kundan korxona yuristlariga qaratilgan funksiyalardan qidiring.
