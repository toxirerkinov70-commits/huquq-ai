# Qolgan vazifalar — yangi seans uchun topshiriq

Bu fayl loyihani davom ettiradigan yangi Claude Code seansi uchun yozilgan.
Avval `HOLAT.md` ni o'qing — u tizimning hozirgi holatini tushuntiradi.

**Sana:** 2026-07-28 · **Oxirgi commit:** `28daeac` · **12 bosqichdan 12 tasi yozilgan**

---

## 0. Boshlashdan oldin bilishingiz shart

Bu qoidalar tajribada olingan. Ularni buzsangiz ish qaytadan bajarilishi kerak
bo'ladi yoki loyiha to'xtaydi.

| # | Qoida | Nega |
|---|---|---|
| 1 | **lex.uz ga so'rovlar orasida 20 soniya kuting** | `robots.txt` da `Crawl-delay: 20`. Client buni avtomatik bajaradi. Tezlashtirsangiz IP bloklanadi. |
| 2 | **`HF_HUB_OFFLINE=1` qo'ying** | `sentence-transformers` har ishga tushganda Hugging Face Hub'ga versiya so'rovi yuboradi. Ketma-ket ko'p jarayon ishlatilsa Hub ulanishni yopadi va model lokal keshda bo'lsa ham yuklanmaydi. |
| 3 | **Embedding lokal modelda** | `EMBED_PROVIDER=local`. Gemini bepul tarifi kuniga 1 000 embedding — bu korpus uchun 20 kun. |
| 4 | **Embedding modelini o'zgartirsangiz butun kolleksiyani qayta quring** | `scripts/index.py --recreate`. Vektorlar boshqa fazoda bo'ladi. |
| 5 | **LLM kuniga 20 so'rov beradi (har model uchun alohida)** | Zanjirda 6 model ≈ 120 so'rov/kun. Eval'ni `ENABLE_QUERY_EXPANSION=false` bilan ishlating — u LLM'ga umuman tegmaydi. |
| 6 | **`data/raw/*.html` hech qachon o'zgartirilmaydi** | Asl manba. Parser xatosi topilsa `run_extract.py` ni qayta ishga tushiring, qayta yuklash shart emas. |
| 7 | **Indexatsiyadan oldin `bash scripts/backup.sh`** | Buzilgan yangilanishdan snapshot orqali qaytish mumkin. |
| 8 | **Host'da `index.py` ishlatishdan oldin backend konteynerini to'xtating** | Ikkalasi ham embedding modelini xotiraga yuklaydi, 8 GB da sig'maydi. |
| 9 | **Modern Standby** | Mashina uxlaganda fon jarayonlari o'ladi. Barcha skriptlar uzilishdan tiklanadi, lekin uzun ishlarni kuzatib turing. |
| 10 | **Har bosqichdan keyin commit** | CLAUDE.md talabi. |

---

## 1. Vazifalar jadvali

| # | Vazifa | Muhimligi | Vaqt |
|---|---|---|---|
| 1 | Agentik rejim live vositaga o'tmasligi | **yuqori** | dasturlash |
| 2 | Jadvalli moddalar (soliq stavkalari) | o'rtacha | dasturlash |
| 3 | Plenum qarorlarini to'liq topish | o'rtacha | ~1 soat |
| 4 | Frontend'da agentik rejim tugmasi | past | dasturlash |
| 5 | 545 sud qarorini indexlash (qaror kutilmoqda) | past | ~30 daqiqa |

---

## Vazifa 1 — Agentik rejim yaqin mavzuni javob o'rniga qo'yadi

**Eng muhim ochiq muammo.** 12-bosqich yozildi va ishlaydi, lekin bitta
holatda noto'g'ri xatti-harakat qiladi.

Takrorlash:

```bash
python -c "..."   # yoki:
curl -X POST http://localhost:8000/api/chat/agentic \
  -H 'Content-Type: application/json' \
  -d '{"question":"Bond omborlari faoliyatini tashkil etish tartibi qanday belgilangan?","stream":false}'
```

Kutilgan: "bond ombori" hukumat qarori bilan tartibga solinadi, u qamrovda yo'q →
model `search_lex_live` ni chaqirishi va hujjat nomini havolasi bilan
ko'rsatishi kerak.

Aslida: model bazadagi **"bojxona ombori"** (Bojxona kodeksi 176-modda) haqida
javob beradi va live vositani umuman chaqirmaydi.

Sinalgan va **yordam bermagan** yechim: `agentic.py` dagi `TOOL_RULES` ga
"yaqin mavzudagi natijani topilmadi deb hisobla" qoidasini qo'shish. Model
baribir o'zgarmadi.

Keyingi urinish uchun g'oyalar:
- Qoidani prompt'da emas, **kodda** majburlash: `search_legal_base` natijalarining
  eng yuqori skorini tekshirib, u chegaradan past bo'lsa tool javobiga
  "ichki bazada ishonchli natija yo'q, `search_lex_live` ni chaqiring" degan
  maslahatni qo'shish
- `search_legal_base` javobiga skorlarni ham qaytarish, model o'zi baholay olsin
- Savoldagi atamani (`bond ombori`) natijalar sarlavhalari bilan solishtirish

---

## Vazifa 2 — Jadvalli moddalar

70 savollik eval'da 4 ta xato qolgan, 3 tasi bir sinfdan: sarlavhasi umumiy
("Soliq stavkalari") va matni katta jadval bo'lgan moddalar.

| Savol | Modda |
|---|---|
| 33 | Soliq kodeksi 337 — banklar foyda solig'i |
| 67 | Soliq kodeksi 405 — ijtimoiy soliq |
| 69 | Soliq kodeksi 429 — yer solig'i |

Aniqlangan sabab: ma'lumot yo'qolmagan — `text_for_embedding` da bo'lim va bob
nomi bor ("XIV BO'LIM. IJTIMOIY SOLIQ"). Muammo reyting darajasida: yuzlab
raqamdan iborat jadval o'rtacha vektorni o'ziga tortadi.

Qilingan: `parser/lex/chunk.py` da `_embedding_body()` jadval matnini embedding
uchun 600 belgigacha qisqartiradi (saqlangan `text` to'liq qoladi).
Natija: recall@5 0.93 → 0.94, recall@10 0.96 → 0.99. Yordam berdi, hal qilmadi.

To'liq yechim chunking'ni o'zgartirishni talab qiladi: katta jadvalni bitta
chunk va bitta vektorda saqlash noto'g'ri, uni qatorlar guruhiga bo'lish kerak.
Bu `chunk.py` ni qayta yozish va butun korpusni qayta indexlash demak (~1.5 soat).

---

## Vazifa 3 — Plenum qarorlari

`/uz/search/court` tabidan 564 hujjat olindi, lekin ulardan atigi **4 tasi**
Oliy sud Plenumi qarori. Aslida ular ancha ko'p. Boshqa filtr yoki `act_type`
ostida bo'lishi mumkin — tekshirilmagan.

Tekshirish uchun: `/uz/search/all` da `query=plenum` yoki turli `act_type`
qiymatlari bilan sinab ko'ring. Har so'rov orasida 20 soniya.

Topilsa: reyestrga `group=6` bilan qo'shing, `run_fetch --group 6`,
`run_extract --group 6`, keyin faqat o'sha hujjatlarni indexlang.

---

## Vazifa 4 — Frontend'da agentik rejim

`/api/chat/agentic` endpoint ishlaydi, lekin frontend'da unga tugma yo'q.
Faqat `/api/chat` (streaming) ishlatiladi.

Diqqat: agentik yo'l streaming qilmaydi — vosita chaqiruvlari generatsiya bilan
aralashadi, shuning uchun javob bir bo'lak bo'lib keladi. Frontend'da
"o'ylanmoqda" holatini ko'rsatish kerak.

---

## Vazifa 5 — 545 sud qarori

Sud amaliyoti 564 hujjatdan 19 tasi indexlangan (4 Plenum + 15 sharh).
Qolgan 545 tasi alohida ish qarorlari — sarlavhasi shunchaki ish raqami
("4-1203-2301/1131-sonli iqtisodiy ish"). Ular umumiy norma o'rnatmaydi.

Chunklari diskda tayyor, qayta yuklash shart emas:

```bash
for d in $(cat data/g6_ids_qolgan.txt); do python scripts/index.py --doc-id="$d"; done
```

**Qaror egasi — loyiha egasi.** Qo'shilsa qidiruv shovqini oshadi, qo'shilmasa
sud amaliyoti tor qoladi.

---

## 2. Foydali buyruqlar

```bash
docker compose up -d                     # qdrant + backend
bash scripts/backup.sh                   # snapshot

ENABLE_QUERY_EXPANSION=false HF_HUB_OFFLINE=1 python eval/run.py
python eval/run.py --mode dense          # gibrid qancha foyda berayotganini ko'rish

python parser/run_update.py --window today --dry-run
python parser/run_update.py --doc-id=-25531
python scripts/index.py --chunk-ids data/update_chunks.txt

curl http://localhost:8000/api/updates
```

---

## 3. Kod xaritasi

| Fayl | Vazifa |
|---|---|
| `parser/lex/client.py` | HTTP client: robots.txt, kesh, backoff |
| `parser/lex/discover.py` | Qidiruv sahifalari, ASP.NET pagination |
| `parser/lex/extract.py` | HTML → Markdown, modda ajratish, sup raqamlar |
| `parser/lex/chunk.py` | Modda → chunk, preamble fallback, jadval qisqartirish |
| `parser/lex/watch.py` | Rasmiy e'lonlar tasmasi, qamrov bo'yicha tasniflash |
| `parser/lex/diff.py` | Ikki Markdown versiyani solishtirish |
| `parser/run_update.py` | Yangilanish orkestratori, xavfsizlik chegaralari |
| `backend/app/scheduler.py` | APScheduler: kunlik 06:00, haftalik, oylik |
| `backend/app/services/aliases.py` | Hujjat nomi detektori (reyestrdan) |
| `backend/app/services/retrieval.py` | Dense, sparse, RRF, modda detektori |
| `backend/app/services/generate.py` | System prompt, qisman javob qoidasi |
| `backend/app/services/tools.py` | 5 ta vosita, live lex.uz |
| `backend/app/services/agentic.py` | Function calling bilan javob |
| `scripts/index.py` | Qdrant indexatsiyasi, `--chunk-ids` bilan tanlab |
