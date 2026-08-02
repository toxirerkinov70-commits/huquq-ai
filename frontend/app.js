const state = {
  agent: "umumiy",
  sessionId: null,
  busy: false,
  agentic: false,
  attachment: null,
  account: null,
  plans: [],
};

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const THEME_KEY = "huquq_theme";
const SESSION_KEY = "huquq_session_id";
const TOKEN_KEY = "huquq_token";
const LANG_KEY = "huquq_lang";
const AGENTS_COLLAPSED_KEY = "huquq_agents_collapsed";

const $ = (id) => document.getElementById(id);
const messages = $("messages");
const chatScroll = $("chat-scroll");
const composer = $("composer");
const questionInput = $("question");
const sendButton = $("send");
const sidebar = $("sidebar");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- language ---------- */

// Only the chrome is translated here. Answers follow the language of the question,
// which the model handles on its own.
const STRINGS = {
  uz: {
    newChat: "Yangi suhbat",
    chat: "Suhbat",
    search: "Qidiruv",
    documents: "Hujjatlar",
    agents: "Agentlar",
    conversations: "Suhbatlar",
    agentMode: "Agent rejimi",
    upgrade: "Tariflar",
    offer: "Ommaviy oferta",
    privacy: "Maxfiylik",
    plansTitle: "Tariflar",
    plansNote: "Tarifni ko'tarish uchun bog'laning — to'lov tizimi ulanish bosqichida.",
    documentBase: "Hujjatlar bazasi",
    disclaimer:
      "Javoblar tavsiyaviy xarakterga ega, aniq huquqiy maslahat uchun yuristga murojaat qiling.",
    askPlaceholder: "Savolingizni yozing...",
    docSearchPlaceholder: "Hujjat nomi bo'yicha qidirish...",
    noSessions: "Suhbatlar hali yo'q",
    untitled: "Yangi suhbat",
    quotaLeft: (left, limit) => `Bugun: ${limit - left}/${limit} savol`,
    quotaUnlimited: "Cheksiz",
    quotaSpent: "Kunlik chegara tugadi",
    perMonth: "oyiga",
    free: "bepul",
    currentPlan: "Joriy tarif",
    loadError: "Yuklab bo'lmadi.",
    answerFailed: "Javob olinmadi.",
    thinking: "O'ylanmoqda: baza qidirilmoqda, kerak bo'lsa lex.uz tekshiriladi...",
    readingFile: "Hujjat o'qilmoqda va baza qidirilmoqda...",
    greetMorning: "Xayrli tong",
    greetDay: "Xayrli kun",
    greetEvening: "Xayrli kech",
    guest: "Mehmon",
    guestAccount: "Mehmon hisobi",
    phoneAccount: "Telefon raqam",
    retention: "Ma'lumot saqlash",
    setProfile: "Profil",
    setPlan: "Tarif",
    setLook: "Ko'rinish",
    setPrivacy: "Maxfiylik",
    setAbout: "Tizim haqida",
    profileSub: "Hisobingiz ma'lumotlari",
    planSub: "Joriy tarif, chegara va sarf",
    lookSub: "Mavzu, til va suhbat rejimi",
    privacySub: "Ma'lumotlaringiz va huquqiy hujjatlar",
    aboutSub: "Baza holati va versiya",
    name: "Ism",
    phone: "Telefon",
    accountType: "Hisob turi",
    status: "Holat",
    ownerAccount: "Yaratuvchi",
    ownerHint: "Barcha imkoniyatlar cheksiz ochiq",
    signOut: "Chiqish",
    signOutConfirm: "Hisobdan chiqasizmi?",
    dailyLimit: "Kunlik chegara",
    validUntil: "Amal qiladi",
    changePlan: "Tarifni o'zgartirish",
    usage30: "30 kunlik sarf",
    requests: "so'rov",
    orders: "Buyurtmalar",
    theme: "Mavzu",
    themeLight: "Kunduzgi",
    themeDark: "Tungi",
    themeSystem: "Tizim",
    language: "Til",
    languageHint: "Interfeys tili. Javob savol tilida beriladi.",
    on: "Yoqilgan",
    off: "O'chirilgan",
    agentModeHint: "Model qidiruvni o'zi boshqaradi, kerak bo'lsa lex.uz ni tekshiradi",
    historyKept: "Suhbat tarixi saqlanadi",
    days: "kun",
    open: "Ochish",
    eraseAll: "Barcha suhbatlarni o'chirish",
    eraseHint: "Qaytarib bo'lmaydi. Sarf jurnali hisob-kitob uchun qoladi.",
    eraseConfirm: "Barcha suhbatlar butunlay o'chiriladi. Davom etasizmi?",
    erased: "Suhbatlar o'chirildi",
    corpus: "Bazadagi moddalar",
    chunks: "parcha",
    lastUpdate: "So'nggi yangilanish",
    version: "Versiya",
    choosePlan: "Tanlash",
    checkout: "rasmiylashtirish",
    chooseTerm: "Muddatni tanlang",
    choosePayment: "To'lov usuli",
    comingSoon: "tez orada",
    plan: "Tarif",
    term: "Muddat",
    month: "oy",
    total: "Jami",
    placeOrder: "Buyurtma berish",
    orderHint: "To'lov tizimlari ulanmoqda. Buyurtma qabul qilinadi va bog'lanamiz.",
    orderPlaced: "Buyurtma qabul qilindi",
    orderPlacedSub: "Tez orada siz bilan bog'lanamiz va tarif faollashtiriladi.",
    orderNumber: "Buyurtma raqami",
    orderStatus_pending: "Kutilmoqda",
    orderStatus_paid: "To'langan",
    orderStatus_cancelled: "Bekor qilingan",
    close: "Yopish",
    loading: "Yuklanmoqda...",
    back: "Orqaga",
    rename: "Qayta nomlash",
    pin: "Yuqoriga qadash",
    unpin: "Qadashni bekor qilish",
    del: "O'chirish",
    deleteConfirm: "Bu suhbat o'chirilsinmi?",
  },
  ru: {
    newChat: "Новый диалог",
    chat: "Диалог",
    search: "Поиск",
    documents: "Документы",
    agents: "Агенты",
    conversations: "Диалоги",
    agentMode: "Режим агента",
    upgrade: "Тарифы",
    offer: "Публичная оферта",
    privacy: "Конфиденциальность",
    plansTitle: "Тарифы",
    plansNote: "Для повышения тарифа свяжитесь с нами — платёжная система подключается.",
    documentBase: "База документов",
    disclaimer:
      "Ответы носят рекомендательный характер, для точной консультации обратитесь к юристу.",
    askPlaceholder: "Напишите ваш вопрос...",
    docSearchPlaceholder: "Поиск по названию документа...",
    noSessions: "Диалогов пока нет",
    untitled: "Новый диалог",
    quotaLeft: (left, limit) => `Сегодня: ${limit - left}/${limit} вопросов`,
    quotaUnlimited: "Без ограничений",
    quotaSpent: "Дневной лимит исчерпан",
    perMonth: "в месяц",
    free: "бесплатно",
    currentPlan: "Текущий тариф",
    loadError: "Не удалось загрузить.",
    answerFailed: "Ответ не получен.",
    thinking: "Идёт поиск по базе, при необходимости проверяется lex.uz...",
    readingFile: "Документ читается, идёт поиск по базе...",
    greetMorning: "Доброе утро",
    greetDay: "Добрый день",
    greetEvening: "Добрый вечер",
    guest: "Гость",
    guestAccount: "Гостевой аккаунт",
    phoneAccount: "Номер телефона",
    retention: "Хранение данных",
    setProfile: "Профиль",
    setPlan: "Тариф",
    setLook: "Оформление",
    setPrivacy: "Конфиденциальность",
    setAbout: "О системе",
    profileSub: "Данные вашего аккаунта",
    planSub: "Текущий тариф, лимит и расход",
    lookSub: "Тема, язык и режим диалога",
    privacySub: "Ваши данные и правовые документы",
    aboutSub: "Состояние базы и версия",
    name: "Имя",
    phone: "Телефон",
    accountType: "Тип аккаунта",
    status: "Статус",
    ownerAccount: "Создатель",
    ownerHint: "Все возможности открыты без ограничений",
    signOut: "Выйти",
    signOutConfirm: "Выйти из аккаунта?",
    dailyLimit: "Дневной лимит",
    validUntil: "Действует до",
    changePlan: "Сменить тариф",
    usage30: "Расход за 30 дней",
    requests: "запросов",
    orders: "Заказы",
    theme: "Тема",
    themeLight: "Светлая",
    themeDark: "Тёмная",
    themeSystem: "Системная",
    language: "Язык",
    languageHint: "Язык интерфейса. Ответ даётся на языке вопроса.",
    on: "Включён",
    off: "Выключен",
    agentModeHint: "Модель сама ведёт поиск и при необходимости проверяет lex.uz",
    historyKept: "История хранится",
    days: "дней",
    open: "Открыть",
    eraseAll: "Удалить все диалоги",
    eraseHint: "Необратимо. Журнал расхода остаётся для расчётов.",
    eraseConfirm: "Все диалоги будут удалены безвозвратно. Продолжить?",
    erased: "Диалоги удалены",
    corpus: "Статей в базе",
    chunks: "фрагментов",
    lastUpdate: "Последнее обновление",
    version: "Версия",
    choosePlan: "Выбрать",
    checkout: "оформление",
    chooseTerm: "Выберите срок",
    choosePayment: "Способ оплаты",
    comingSoon: "скоро",
    plan: "Тариф",
    term: "Срок",
    month: "мес.",
    total: "Итого",
    placeOrder: "Оформить заказ",
    orderHint: "Платёжные системы подключаются. Заказ принят, мы свяжемся с вами.",
    orderPlaced: "Заказ принят",
    orderPlacedSub: "Мы свяжемся с вами и активируем тариф.",
    orderNumber: "Номер заказа",
    orderStatus_pending: "Ожидает",
    orderStatus_paid: "Оплачен",
    orderStatus_cancelled: "Отменён",
    close: "Закрыть",
    loading: "Загрузка...",
    back: "Назад",
    rename: "Переименовать",
    pin: "Закрепить",
    unpin: "Открепить",
    del: "Удалить",
    deleteConfirm: "Удалить этот диалог?",
  },
};

let lang = localStorage.getItem(LANG_KEY) === "ru" ? "ru" : "uz";

function t(key, ...args) {
  const value = (STRINGS[lang] || STRINGS.uz)[key];
  return typeof value === "function" ? value(...args) : value;
}

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const value = t(node.dataset.i18n);
    if (value) node.textContent = value;
  });
  questionInput.placeholder = t("askPlaceholder");
  const docQuery = $("doc-query");
  if (docQuery) docQuery.placeholder = t("docSearchPlaceholder");
  const globalQuery = $("global-query");
  if (globalQuery) globalQuery.placeholder = t("docSearchPlaceholder");
  renderQuota();
}

function setLanguage(next) {
  lang = next === "ru" ? "ru" : "uz";
  localStorage.setItem(LANG_KEY, lang);
  applyLanguage();
}

/* ---------- theme ---------- */

function themePref() {
  return localStorage.getItem(THEME_KEY) || "system";
}

function applyTheme() {
  const pref = themePref();
  const dark =
    pref === "dark" ||
    (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

function setTheme(pref) {
  localStorage.setItem(THEME_KEY, pref);
  applyTheme();
  renderSettings();
}

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
applyTheme();

/* ---------- api and account ---------- */

const api = (path, options) => Huquq.api(path, options);

function account() {
  return Huquq.account();
}

async function loadAccount() {
  await Huquq.refreshAccount();
}

Huquq.onAccountChange(() => {
  renderQuota();
  renderAccountRow();
  if (!$("settings-modal").hidden) renderSettings();
});

function renderQuota() {
  const data = account();
  if (!data) return;
  const quota = data.quota;
  const line = $("account-plan");
  if (quota.daily_limit <= 0) {
    line.textContent = `${data.plan.name} · ${t("quotaUnlimited").toLowerCase()}`;
  } else if (quota.remaining > 0) {
    line.textContent = `${data.plan.name} · ${quota.used_today}/${quota.daily_limit}`;
  } else {
    line.textContent = `${data.plan.name} · ${t("quotaSpent").toLowerCase()}`;
  }
  line.classList.toggle("spent", quota.daily_limit > 0 && quota.remaining === 0);
}

function renderAccountRow() {
  const data = account();
  if (!data) return;
  const label = data.name || data.phone_display || data.email || t("guest");
  $("account-name").textContent = label;
  const avatar = $("avatar");
  avatar.innerHTML = "";
  if (data.picture) {
    const image = document.createElement("img");
    image.src = data.picture;
    image.alt = "";
    image.referrerPolicy = "no-referrer";
    avatar.appendChild(image);
  } else {
    avatar.textContent = (label || "?").trim().charAt(0).toUpperCase();
  }
}

function noteQuotaUsed(snapshot) {
  const data = account();
  if (!data || !snapshot) return;
  data.quota = { ...data.quota, ...snapshot };
  renderQuota();
}

/* ---------- toast ---------- */

let toastTimer = null;

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 3200);
}

/* ---------- legal texts ---------- */

async function openLegal(name, back) {
  const titles = { oferta: t("offer"), maxfiylik: t("privacy"), saqlash: t("retention") };
  const title = titles[name] || name;
  showModal(title, null, (body) => body.appendChild(el("p", null, t("loading"))), back);
  try {
    const response = await fetch("/api/legal/" + name);
    const data = await response.json();
    showModal(title, null, (body) => {
      body.innerHTML = renderMarkdown(data.markdown);
    }, back);
  } catch (error) {
    showModal(title, null, (body) => body.appendChild(el("p", "error", t("loadError"))), back);
  }
}
window.openLegal = openLegal;

/* ---------- settings ---------- */

function money(amount) {
  // thousands separated by a space, the way prices are written here — the browser's
  // uz-UZ locale gives commas, which read as a decimal point to a local reader
  const grouped = String(Math.round(Number(amount) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return grouped + " so'm";
}

function settingsRow(label, valueNode, hint) {
  const row = el("div", "set-row");
  const left = el("div");
  left.appendChild(el("div", "set-label", label));
  if (hint) left.appendChild(el("p", "set-hint", hint));
  row.appendChild(left);
  if (valueNode) row.appendChild(valueNode);
  return row;
}

function segmented(options, current, onPick) {
  const box = el("div", "seg");
  options.forEach(([value, label]) => {
    const button = el("button", value === current ? "active" : null, label);
    button.addEventListener("click", () => onPick(value));
    box.appendChild(button);
  });
  return box;
}

function renderProfilePane() {
  const pane = $("pane-profile");
  const data = account();
  pane.innerHTML = "";
  if (!data) return;

  pane.appendChild(el("h3", null, t("setProfile")));
  pane.appendChild(el("p", "pane-sub", t("profileSub")));

  const nameValue = el("div", "set-value", data.name || "—");
  pane.appendChild(settingsRow(t("name"), nameValue));
  pane.appendChild(settingsRow(t("phone"), el("div", "set-value", data.phone_display || "—")));
  pane.appendChild(settingsRow("Email", el("div", "set-value", data.email || "—")));

  const kindLabels = { anon: t("guestAccount"), phone: t("phoneAccount"), google: "Google", service: "Service" };
  pane.appendChild(
    settingsRow(t("accountType"), el("div", "set-value", kindLabels[data.kind] || data.kind))
  );

  if (data.is_owner) {
    const badge = el("span", "owner-badge", "★ " + t("ownerAccount"));
    pane.appendChild(settingsRow(t("status"), badge, t("ownerHint")));
  }

  const actions = el("div", "set-row");
  actions.appendChild(el("div", "set-label", t("signOut")));
  const out = el("button", "btn danger", t("signOut"));
  out.addEventListener("click", () => {
    if (confirm(t("signOutConfirm"))) Huquq.signOut();
  });
  actions.appendChild(out);
  pane.appendChild(actions);
}

async function renderPlanPane() {
  const pane = $("pane-plan");
  const data = account();
  pane.innerHTML = "";
  if (!data) return;

  pane.appendChild(el("h3", null, t("setPlan")));
  pane.appendChild(el("p", "pane-sub", t("planSub")));

  const planValue = el("div", "set-value", data.plan.name);
  pane.appendChild(settingsRow(t("currentPlan"), planValue, data.plan.tagline));
  pane.appendChild(
    settingsRow(
      t("dailyLimit"),
      el(
        "div",
        "set-value",
        data.plan.daily_questions > 0 ? `${data.quota.used_today} / ${data.plan.daily_questions}` : t("quotaUnlimited")
      )
    )
  );
  if (data.plan_expires_at) {
    pane.appendChild(settingsRow(t("validUntil"), el("div", "set-value", data.plan_expires_at.slice(0, 10))));
  }

  const upgrade = el("button", "btn primary", t("upgrade"));
  upgrade.addEventListener("click", () => {
    $("settings-modal").hidden = true;
    openPlans(() => openSettings("plan"));
  });
  pane.appendChild(settingsRow(t("changePlan"), upgrade));

  const usageRow = el("div", "set-value", "…");
  pane.appendChild(settingsRow(t("usage30"), usageRow));
  try {
    const response = await api("/api/usage?days=30");
    const usage = await response.json();
    usageRow.textContent = `${usage.totals.events} ${t("requests")} · ${money(Math.round(usage.cost_uzs))}`;
  } catch (error) {
    usageRow.textContent = "—";
  }

  const orders = await loadOrders();
  if (orders.length) {
    pane.appendChild(el("h3", null, t("orders")));
    orders.slice(0, 5).forEach((order) => {
      const row = el("div", "set-row");
      const left = el("div");
      left.appendChild(el("div", "set-label", `${order.plan_name} · ${order.months} ${t("month")}`));
      left.appendChild(el("p", "set-hint", `${order.id} · ${money(order.amount_uzs)}`));
      row.appendChild(left);
      row.appendChild(el("span", "order-status " + order.status, t("orderStatus_" + order.status)));
      pane.appendChild(row);
    });
  }
}

function renderLookPane() {
  const pane = $("pane-look");
  pane.innerHTML = "";
  pane.appendChild(el("h3", null, t("setLook")));
  pane.appendChild(el("p", "pane-sub", t("lookSub")));

  pane.appendChild(
    settingsRow(
      t("theme"),
      segmented(
        [["light", t("themeLight")], ["dark", t("themeDark")], ["system", t("themeSystem")]],
        themePref(),
        setTheme
      )
    )
  );
  pane.appendChild(
    settingsRow(
      t("language"),
      segmented([["uz", "O'zbekcha"], ["ru", "Русский"]], lang, (value) => {
        setLanguage(value);
        renderSettings();
      }),
      t("languageHint")
    )
  );

  const agenticToggle = el("button", "btn" + (state.agentic ? " primary" : ""), state.agentic ? t("on") : t("off"));
  agenticToggle.addEventListener("click", () => {
    setAgentic(!state.agentic);
    renderLookPane();
  });
  pane.appendChild(settingsRow(t("agentMode"), agenticToggle, t("agentModeHint")));
}

function renderPrivacyPane() {
  const pane = $("pane-privacy");
  const data = account();
  pane.innerHTML = "";
  pane.appendChild(el("h3", null, t("setPrivacy")));
  pane.appendChild(el("p", "pane-sub", t("privacySub")));

  if (data) {
    pane.appendChild(
      settingsRow(t("historyKept"), el("div", "set-value", `${data.plan.history_days} ${t("days")}`))
    );
  }

  ["oferta", "maxfiylik", "saqlash"].forEach((name) => {
    const open = el("button", "btn", t("open"));
    open.addEventListener("click", () => {
      $("settings-modal").hidden = true;
      openLegal(name, () => openSettings("privacy"));
    });
    pane.appendChild(settingsRow(t(name === "oferta" ? "offer" : name === "maxfiylik" ? "privacy" : "retention"), open));
  });

  const erase = el("button", "btn danger", t("eraseAll"));
  erase.addEventListener("click", async () => {
    if (!confirm(t("eraseConfirm"))) return;
    const response = await api("/api/account/data", { method: "DELETE" });
    if (response.ok) {
      localStorage.removeItem(SESSION_KEY);
      state.sessionId = null;
      toast(t("erased"));
      loadSessions();
      showEmptyState();
    }
  });
  pane.appendChild(settingsRow(t("eraseAll"), erase, t("eraseHint")));
}

async function renderAboutPane() {
  const pane = $("pane-about");
  pane.innerHTML = "";
  pane.appendChild(el("h3", null, t("setAbout")));
  pane.appendChild(el("p", "pane-sub", t("aboutSub")));

  const health = el("div", "set-value", "…");
  pane.appendChild(settingsRow(t("corpus"), health));
  try {
    const data = await (await fetch("/health")).json();
    health.textContent = `${(data.points || 0).toLocaleString("uz-UZ")} ${t("chunks")}`;
  } catch (error) {
    health.textContent = "—";
  }

  const fresh = el("div", "set-value", $("freshness").textContent || "—");
  pane.appendChild(settingsRow(t("lastUpdate"), fresh));
  pane.appendChild(settingsRow(t("version"), el("div", "set-value", "1.1.0")));
}

function renderSettings() {
  renderProfilePane();
  renderPlanPane();
  renderLookPane();
  renderPrivacyPane();
  renderAboutPane();
}

function openSettings(pane) {
  $("settings-modal").hidden = false;
  renderSettings();
  if (pane) selectSettingsPane(pane);
}

function selectSettingsPane(name) {
  document.querySelectorAll("#settings-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.pane === name);
  });
  document.querySelectorAll(".settings-pane").forEach((section) => {
    section.classList.toggle("active", section.dataset.pane === name);
  });
}

document.querySelectorAll("#settings-nav button").forEach((button) => {
  button.addEventListener("click", () => selectSettingsPane(button.dataset.pane));
});
$("open-settings").addEventListener("click", () => openSettings("profile"));
$("settings-close").addEventListener("click", () => ($("settings-modal").hidden = true));
$("settings-modal").addEventListener("click", (event) => {
  if (event.target === $("settings-modal")) $("settings-modal").hidden = true;
});

/* ---------- plans ---------- */

let plansCache = [];
// remembered so the checkout can step back to the pricing list, and the pricing list
// back to wherever it was opened from
let plansBack = null;

async function openPlans(back) {
  const grid = $("plans-grid");
  grid.innerHTML = "";
  plansBack = back || plansBack;
  setBack("plans-modal", plansBack);
  $("plans-modal").hidden = false;
  $("plans-note").textContent = t("plansNote");
  try {
    if (!plansCache.length) {
      plansCache = await (await fetch("/api/plans")).json();
    }
  } catch (error) {
    grid.appendChild(el("p", "error", t("loadError")));
    return;
  }
  const data = account();
  const currentKey = data ? data.plan.key : null;
  plansCache.forEach((plan) => {
    const card = el("div", "plan-card" + (plan.key === currentKey ? " current" : ""));
    card.appendChild(el("h3", null, plan.name));
    card.appendChild(
      el("p", "plan-price", plan.price_uzs ? money(plan.price_uzs) + " / " + t("perMonth") : t("free"))
    );
    card.appendChild(el("p", "plan-tagline", plan.tagline));
    const list = el("ul", "plan-features");
    plan.features.forEach((feature) => list.appendChild(el("li", null, feature)));
    card.appendChild(list);
    if (plan.key === currentKey) {
      card.appendChild(el("span", "plan-badge", t("currentPlan")));
    } else if (plan.purchasable) {
      card.appendChild(el("div", "plan-cta", t("choosePlan") + " →"));
      card.addEventListener("click", () => openCheckout(plan));
    }
    grid.appendChild(card);
  });
}

$("plans-close").addEventListener("click", () => {
  plansBack = null;
  $("plans-modal").hidden = true;
});
$("plans-modal").addEventListener("click", (event) => {
  if (event.target === $("plans-modal")) {
    plansBack = null;
    $("plans-modal").hidden = true;
  }
});

/* ---------- checkout ---------- */

const checkout = { plan: null, months: 1, provider: null, quote: null, methods: [] };

async function loadOrders() {
  try {
    const response = await api("/api/orders");
    return response.ok ? await response.json() : [];
  } catch (error) {
    return [];
  }
}

async function openCheckout(plan) {
  checkout.plan = plan;
  checkout.months = 1;
  checkout.provider = null;
  $("plans-modal").hidden = true;
  setBack("checkout-modal", () => openPlans());
  $("checkout-modal").hidden = false;
  $("checkout-title").textContent = plan.name + " — " + t("checkout");
  const body = $("checkout-body");
  body.innerHTML = "";
  body.appendChild(el("p", "pane-sub", t("loading")));

  try {
    const [quote, methods] = await Promise.all([
      api("/api/plans/" + plan.key + "/quote").then((r) => r.json()),
      fetch("/api/payment-methods").then((r) => r.json()),
    ]);
    checkout.quote = quote;
    checkout.methods = methods;
    renderCheckout();
  } catch (error) {
    body.innerHTML = "";
    body.appendChild(el("p", "error", t("loadError")));
  }
}

function renderCheckout() {
  const body = $("checkout-body");
  body.innerHTML = "";

  body.appendChild(el("div", "set-label", t("chooseTerm")));
  const terms = el("div", "term-list");
  checkout.quote.options.forEach((option) => {
    const row = el("label", "term-option" + (option.months === checkout.months ? " selected" : ""));
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "term";
    radio.checked = option.months === checkout.months;
    radio.addEventListener("change", () => {
      checkout.months = option.months;
      renderCheckout();
    });
    row.appendChild(radio);

    const main = el("div", "term-main");
    const name = el("div", "term-name");
    name.textContent = option.months + " " + t("month");
    if (option.discount_percent) {
      name.appendChild(el("span", "term-save", "−" + option.discount_percent + "%"));
    }
    main.appendChild(name);
    main.appendChild(el("div", "term-per", money(option.per_month_uzs) + " / " + t("perMonth")));
    row.appendChild(main);
    row.appendChild(el("div", "term-total", money(option.amount_uzs)));
    terms.appendChild(row);
  });
  body.appendChild(terms);

  body.appendChild(el("div", "set-label", t("choosePayment")));
  const list = el("div", "pay-list");
  checkout.methods.forEach((method) => {
    const row = el(
      "div",
      "pay-option" + (method.available ? "" : " disabled") + (checkout.provider === method.key ? " selected" : "")
    );
    const info = el("div");
    info.appendChild(el("div", "pay-name", method.name));
    info.appendChild(el("div", "pay-desc", method.description));
    row.appendChild(info);
    if (!method.available) row.appendChild(el("span", "pay-soon", t("comingSoon")));
    if (method.available) {
      row.addEventListener("click", () => {
        checkout.provider = method.key;
        renderCheckout();
      });
    }
    list.appendChild(row);
  });
  body.appendChild(list);

  const selected = checkout.quote.options.find((option) => option.months === checkout.months);
  const summary = el("div", "order-summary");
  const line = (label, value, className) => {
    const row = el("div", "row" + (className ? " " + className : ""));
    row.appendChild(el("span", null, label));
    row.appendChild(el("span", null, value));
    return row;
  };
  summary.appendChild(line(t("plan"), checkout.plan.name));
  summary.appendChild(line(t("term"), checkout.months + " " + t("month")));
  summary.appendChild(line(t("total"), money(selected.amount_uzs), "total"));
  body.appendChild(summary);

  const confirm = el("button", "auth-primary", t("placeOrder"));
  confirm.addEventListener("click", placeOrder);
  body.appendChild(confirm);
  body.appendChild(el("p", "set-hint", t("orderHint")));
}

async function placeOrder() {
  try {
    const order = await Huquq.post("/api/orders", {
      plan: checkout.plan.key,
      months: checkout.months,
      provider: checkout.provider,
    });
    renderOrderPlaced(order);
    loadAccount();
  } catch (error) {
    toast(error.message);
  }
}

function renderOrderPlaced(order) {
  const body = $("checkout-body");
  body.innerHTML = "";
  body.appendChild(el("h3", null, t("orderPlaced")));
  body.appendChild(el("p", "pane-sub", t("orderPlacedSub")));

  const summary = el("div", "order-summary");
  const line = (label, valueNode) => {
    const row = el("div", "row");
    row.appendChild(el("span", null, label));
    row.appendChild(valueNode);
    return row;
  };
  summary.appendChild(line(t("orderNumber"), el("span", "order-code", order.id)));
  summary.appendChild(line(t("plan"), el("span", null, order.plan_name)));
  summary.appendChild(line(t("term"), el("span", null, order.months + " " + t("month"))));
  summary.appendChild(line(t("status"), el("span", "order-status " + order.status, t("orderStatus_" + order.status))));
  const total = el("div", "row total");
  total.appendChild(el("span", null, t("total")));
  total.appendChild(el("span", null, money(order.amount_uzs)));
  summary.appendChild(total);
  body.appendChild(summary);

  const close = el("button", "auth-primary", t("close"));
  close.addEventListener("click", () => ($("checkout-modal").hidden = true));
  body.appendChild(close);
}

$("checkout-close").addEventListener("click", () => {
  plansBack = null;
  $("checkout-modal").backTo = null;
  $("checkout-modal").hidden = true;
});
$("checkout-modal").addEventListener("click", (event) => {
  if (event.target === $("checkout-modal")) {
    plansBack = null;
    $("checkout-modal").backTo = null;
    $("checkout-modal").hidden = true;
  }
});

/* ---------- minimal markdown (input is escaped first, so innerHTML stays safe) ---------- */

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function inlineMd(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

// a row of a pipe table, and the |---|---| line that separates the header from it
const TABLE_ROW = /^\s*\|(.+)\|\s*$/;
const TABLE_RULE = /^\s*\|[\s:|-]+\|\s*$/;
const QUOTE_RE = /^\s*(?:&gt;|>)\s?(.*)/;

function tableCells(line) {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => inlineMd(cell.trim()));
}

function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  let html = "";
  let list = null;
  let para = [];

  const flushPara = () => {
    if (para.length) { html += "<p>" + para.join("<br>") + "</p>"; para = []; }
  };
  const closeList = () => {
    if (list) { html += "</" + list + ">"; list = null; }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trimEnd();
    if (!line.trim()) { flushPara(); closeList(); continue; }

    // Tables carry the numbers in this domain — fines, rates, deadlines, retention
    // periods. Left unhandled they printed as rows of pipe characters.
    if (TABLE_ROW.test(line) && TABLE_RULE.test(lines[index + 1] || "")) {
      flushPara();
      closeList();
      const head = tableCells(line);
      let body = "";
      let cursor = index + 2;
      while (cursor < lines.length && TABLE_ROW.test(lines[cursor])) {
        body += "<tr>" + tableCells(lines[cursor]).map((c) => `<td>${c}</td>`).join("") + "</tr>";
        cursor += 1;
      }
      html +=
        '<div class="md-table"><table><thead><tr>' +
        head.map((c) => `<th>${c}</th>`).join("") +
        "</tr></thead><tbody>" + body + "</tbody></table></div>";
      index = cursor - 1;
      continue;
    }

    // a rule and a quoted note are both common in the legal texts; unhandled they
    // printed as literal dashes and angle brackets
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushPara();
      closeList();
      html += "<hr>";
      continue;
    }
    // the lines were escaped first, so a quote marker arrives here as &gt;
    const quote = line.match(QUOTE_RE);
    if (quote) {
      flushPara();
      closeList();
      const block = [inlineMd(quote[1])];
      while (index + 1 < lines.length) {
        const next = lines[index + 1].match(QUOTE_RE);
        if (!next) break;
        block.push(inlineMd(next[1]));
        index += 1;
      }
      html += "<blockquote>" + block.join("<br>") + "</blockquote>";
      continue;
    }

    const heading = line.match(/^#{1,4}\s+(.*)/);
    const bullet = line.match(/^\s*[-*•]\s+(.*)/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (heading) { flushPara(); closeList(); html += "<h3>" + inlineMd(heading[1]) + "</h3>"; continue; }
    if (bullet) {
      flushPara();
      if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
      html += "<li>" + inlineMd(bullet[1]) + "</li>";
      continue;
    }
    if (numbered) {
      flushPara();
      if (list !== "ol") { closeList(); html += "<ol>"; list = "ol"; }
      html += "<li>" + inlineMd(numbered[1]) + "</li>";
      continue;
    }
    closeList();
    para.push(inlineMd(line));
  }
  flushPara();
  closeList();
  return html;
}

// the registration screen renders the offer with the same renderer the answers use
window.renderMarkdown = renderMarkdown;

// the interface shows its own advisory block, so a model-written copy is dropped
function stripDisclaimer(text) {
  return text
    .replace(/\n*\**\s*Javoblar tavsiyaviy xarakterga ega[^\n]*$/i, "")
    .trim();
}

function disclaimerBlock() {
  const box = el("div", "answer-disclaimer");
  box.innerHTML =
    '<svg viewBox="0 0 24 24" width="15" height="15"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 8v.5M12 11.5V16" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>';
  box.appendChild(el("span", null, t("disclaimer")));
  return box;
}

// once a conversation starts every answer carries the notice, so the one under the
// composer would repeat it a second time on the same screen
function syncComposerNotice() {
  const notice = $("composer-disclaimer");
  if (notice) notice.hidden = Boolean(messages.querySelector(".msg"));
}

/* ---------- welcome screen ---------- */

const AGENT_MODE_INFO = `Agent rejimi yoqilganda javob topish jarayonini modelning o'zi boshqaradi.

**Oddiy rejim** — har savol bir xil yo'ldan o'tadi: baza qidiruvi, saralash, javob. Tez ishlaydi, javob oqim bilan keladi.

**Agent rejimi** — modelga 5 ta vosita beriladi va u qaysi birini, qachon ishlatishni o'zi hal qiladi:
- **Ichki qidiruv** — qonun bazasi bo'ylab gibrid qidiruv, asosiy vosita
- **Modda matni** — kerakli moddaning to'liq matnini oladi
- **Hujjat mundarijasi** — "bu kodeksda nima bor?" savollari uchun
- **lex.uz holat tekshiruvi** — hujjatning amaldagi holatini real vaqtda tekshiradi
- **lex.uz jonli qidiruv** — bazada topilmagan tushunchani lex.uz dan qidiradi

**Asosiy afzalligi:** savolingizdagi tushuncha bazada umuman bo'lmasa, tizim javobni o'ylab topmaydi — lex.uz dan jonli qidiradi va topilgan hujjatni havolasi bilan ko'rsatadi. Bunday manbalar "real vaqtda tekshirildi" belgisi bilan ajratiladi, hujjatning o'zi esa keyingi yangilanishda bazaga qo'shiladi.

**Narxi:** sekinroq ishlaydi va javob oqim bilan emas, bir bo'lak bo'lib keladi.

Rejim chap paneldagi **Agent rejimi** halqasi orqali yoqiladi va o'chiriladi.`;

function greeting() {
  const hour = new Date().getHours();
  const part =
    hour >= 5 && hour < 11 ? "greetMorning" : hour >= 11 && hour < 18 ? "greetDay" : "greetEvening";
  const data = account();
  // greeting somebody by name is the difference between a tool and a service; an
  // account without one is greeted plainly rather than as "guest"
  const name = data && data.name ? data.name.split(/\s+/)[0] : "";
  return name ? `${t(part)}, ${name}` : t(part);
}

function showEmptyState() {
  messages.innerHTML = "";
  const empty = el("div", "empty");
  empty.id = "empty";
  empty.appendChild(el("h1", null, greeting()));
  empty.appendChild(
    el("p", "sub", "Umumiy, jinoyat, fuqarolik, soliq, mehnat, shartnoma va sud masalalari bo'yicha savol bering. Hujjat yuklab tahlil qildirishingiz ham mumkin.")
  );
  const grid = el("div", "samples");

  const agentCard = el("button", "sample");
  agentCard.appendChild(el("span", "cat", "Agent rejimi"));
  agentCard.appendChild(el("span", "q", "Agent rejimi nima va qachon kerak?"));
  agentCard.addEventListener("click", showAgentInfo);
  grid.appendChild(agentCard);

  const capabilities = el("button", "sample");
  capabilities.appendChild(el("span", "cat", "Imkoniyatlar"));
  capabilities.appendChild(el("span", "q", "Sen menga qanday yordam bera olasan?"));
  capabilities.addEventListener("click", () => ask("Sen menga qanday yordam bera olasan?"));
  grid.appendChild(capabilities);

  empty.appendChild(grid);
  messages.appendChild(empty);
  syncComposerNotice();
}

function showAgentInfo() {
  showModal("Agent rejimi", null, (body) => {
    body.classList.add("md");
    body.innerHTML = renderMarkdown(AGENT_MODE_INFO);
  });
}

/* ---------- sidebar ---------- */

function closeSidebar() {
  sidebar.classList.remove("open");
  $("backdrop").hidden = true;
}

$("menu-btn").addEventListener("click", () => {
  sidebar.classList.add("open");
  $("backdrop").hidden = false;
});
$("backdrop").addEventListener("click", closeSidebar);
$("drawer-close").addEventListener("click", closeSidebar);

function activateView(view) {
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const item = document.querySelector(`.nav-item[data-view="${view}"]`);
  if (item) item.classList.add("active");
  $("view-" + view).classList.add("active");
}

document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
  item.addEventListener("click", () => {
    activateView(item.dataset.view);
    if (item.dataset.view === "docs") loadDocuments();
    closeSidebar();
  });
});

const agentsSection = document.querySelector(".agents-section");
// seven modes fill a phone's sidebar on their own and push the conversations out of
// sight, so on a small screen the list starts folded — until the user says otherwise
const agentsPref = localStorage.getItem(AGENTS_COLLAPSED_KEY);
const foldAgents = agentsPref === null ? window.innerWidth <= 860 : agentsPref === "1";
if (foldAgents) agentsSection.classList.add("collapsed");
$("agents-toggle").addEventListener("click", () => {
  const collapsed = agentsSection.classList.toggle("collapsed");
  localStorage.setItem(AGENTS_COLLAPSED_KEY, collapsed ? "1" : "0");
  $("agents-toggle").setAttribute("aria-expanded", String(!collapsed));
});

function startNewChat() {
  state.sessionId = null;
  localStorage.removeItem(SESSION_KEY);
  clearAttachment();
  showEmptyState();
  activateView("chat");
  highlightActiveSession();
  closeSidebar();
  questionInput.focus();
}

$("new-chat").addEventListener("click", startNewChat);

// Each mode gets a mark and a colour drawn from what it is about, so the list can be
// found by eye. The paths are inline rather than a sprite because there are seven.
const AGENT_LOOK = {
  umumiy: {
    color: "#6366f1",
    path: "M12 3 4 6.5V12c0 5 3.4 8.4 8 9.5 4.6-1.1 8-4.5 8-9.5V6.5L12 3z",
  },
  jinoyat: {
    color: "#ef4444",
    path: "M12 2.5 3.5 6v6c0 5 3.6 8.6 8.5 9.9 4.9-1.3 8.5-4.9 8.5-9.9V6L12 2.5zM9.5 12l1.8 1.9 3.4-3.6",
  },
  fuqarolik: {
    color: "#0ea5e9",
    path: "M12 3v18M4.5 7.5h15M6.5 7.5 3 15h7l-3.5-7.5zM17.5 7.5 14 15h7l-3.5-7.5zM8 21h8",
  },
  soliq: {
    color: "#22c55e",
    path: "M7 3h10a1 1 0 0 1 1 1v17l-3-2-3 2-3-2-3 2V4a1 1 0 0 1 1-1zM9.5 8h5M9.5 12h5M9.5 16h3",
  },
  mehnat: {
    color: "#f59e0b",
    path: "M4 8h16v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8zM9 8V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V8M4 13h16",
  },
  shartnoma: {
    color: "#a855f7",
    path: "M7 3h7l4 4v14H7V3zM14 3v4h4M9.5 12.5h5M9.5 16h3",
  },
  sud: {
    color: "#14b8a6",
    path: "M12 4v16M6 20h12M5 9h14M8 9l-3 5.5h6L8 9zM16 9l-3 5.5h6L16 9z",
  },
};

function agentIcon(key) {
  const look = AGENT_LOOK[key] || AGENT_LOOK.umumiy;
  const holder = el("span", "agent-icon");
  holder.style.setProperty("--agent-color", look.color);
  holder.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="' + look.path + '"/></svg>';
  return holder;
}

async function loadAgents() {
  try {
    const response = await fetch("/api/agents");
    const data = await response.json();
    const box = $("agents");
    box.innerHTML = "";
    data.agents.forEach((agent) => {
      const look = AGENT_LOOK[agent.key] || AGENT_LOOK.umumiy;
      const button = el("button", "agent" + (agent.key === state.agent ? " active" : ""));
      button.style.setProperty("--agent-color", look.color);
      button.title = agent.description;
      button.appendChild(agentIcon(agent.key));
      button.appendChild(el("span", null, agent.name));
      button.addEventListener("click", () => {
        state.agent = agent.key;
        document.querySelectorAll(".agent").forEach((a) => a.classList.remove("active"));
        button.classList.add("active");
        closeSidebar();
      });
      box.appendChild(button);
    });
  } catch (error) {
    console.error("agents", error);
  }
}

/* ---------- sessions ---------- */

function highlightActiveSession() {
  document.querySelectorAll(".session-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.sessionId === state.sessionId);
  });
}

const ICONS = {
  dots: "M12 6.2h.01M12 12h.01M12 17.8h.01",
  pin: "M15 3.5 20.5 9l-3.4 1.2-3.6 3.6-.7 4.3-6.9-6.9 4.3-.7 3.6-3.6L15 3.5zM7.9 16.1 3.5 20.5",
  pencil: "M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3z",
  trash: "M4 7h16M9.5 7V5h5v2M6.5 7l1 13h9l1-13M10.5 11v5M13.5 11v5",
};

function icon(name, size = 15) {
  const span = document.createElement("span");
  span.innerHTML =
    `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="' +
    ICONS[name] + '"/></svg>';
  return span.firstChild;
}

let openMenu = null;

function closeRowMenu() {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
  }
  document.querySelectorAll('.s-menu[aria-expanded="true"]').forEach((button) => {
    button.setAttribute("aria-expanded", "false");
  });
}

document.addEventListener("click", closeRowMenu);
window.addEventListener("resize", closeRowMenu);

function showRowMenu(anchor, items) {
  closeRowMenu();
  const menu = el("div", "row-menu");
  items.forEach((item) => {
    if (item === "-") {
      menu.appendChild(document.createElement("hr"));
      return;
    }
    const button = el("button", item.danger ? "danger" : null);
    button.appendChild(icon(item.icon));
    button.appendChild(el("span", null, item.label));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeRowMenu();
      item.run();
    });
    menu.appendChild(button);
  });
  document.body.appendChild(menu);

  const box = anchor.getBoundingClientRect();
  const width = menu.offsetWidth;
  const height = menu.offsetHeight;
  menu.style.left = Math.min(box.left, window.innerWidth - width - 10) + "px";
  menu.style.top =
    (box.bottom + height > window.innerHeight ? box.top - height - 4 : box.bottom + 4) + "px";
  openMenu = menu;
  anchor.setAttribute("aria-expanded", "true");
}

function startRename(row, session) {
  const title = row.querySelector(".s-title");
  const input = el("input", "s-rename");
  input.value = session.title || "";
  input.maxLength = 120;
  row.replaceChild(input, title);
  input.focus();
  input.select();

  const finish = async (save) => {
    const value = input.value.trim();
    input.replaceWith(title);
    if (!save || !value || value === session.title) return;
    const response = await api("/api/sessions/" + encodeURIComponent(session.id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: value }),
    });
    if (response.ok) loadSessions();
  };

  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

async function togglePin(session) {
  const response = await api("/api/sessions/" + encodeURIComponent(session.id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned: !session.pinned }),
  });
  if (response.ok) loadSessions();
}

async function loadSessions() {
  try {
    const response = await api("/api/sessions");
    const items = await response.json();
    const box = $("sessions");
    box.innerHTML = "";
    if (!items.length) {
      box.appendChild(el("div", "session-empty", t("noSessions")));
      return;
    }
    items.forEach((session) => {
      const row = el("div", "session-item");
      row.dataset.sessionId = session.id;
      row.setAttribute("role", "button");

      if (session.pinned) {
        const mark = el("span", "s-pin");
        mark.appendChild(icon("pin", 12));
        row.appendChild(mark);
      }

      const title = el("span", "s-title", session.title || t("untitled"));
      row.title = session.title || "";
      row.appendChild(title);

      const menu = el("button", "s-menu");
      menu.setAttribute("aria-expanded", "false");
      menu.setAttribute("aria-label", "Menyu");
      menu.appendChild(icon("dots", 16));
      menu.addEventListener("click", (event) => {
        event.stopPropagation();
        if (menu.getAttribute("aria-expanded") === "true") {
          closeRowMenu();
          return;
        }
        showRowMenu(menu, [
          { icon: "pencil", label: t("rename"), run: () => startRename(row, session) },
          {
            icon: "pin",
            label: session.pinned ? t("unpin") : t("pin"),
            run: () => togglePin(session),
          },
          "-",
          {
            icon: "trash",
            label: t("del"),
            danger: true,
            run: () => {
              if (confirm(t("deleteConfirm"))) removeSession(session.id);
            },
          },
        ]);
      });
      row.appendChild(menu);

      row.addEventListener("click", () => {
        openSession(session.id);
        closeSidebar();
      });
      box.appendChild(row);
    });
    highlightActiveSession();
  } catch (error) {
    console.error("sessions", error);
  }
}

async function removeSession(sessionId) {
  try {
    await api("/api/sessions/" + encodeURIComponent(sessionId), { method: "DELETE" });
  } catch (error) {
    console.error("delete session", error);
  }
  if (sessionId === state.sessionId) startNewChat();
  loadSessions();
}

function renderAssistantMessage(content, sources) {
  const wrap = el("div", "msg bot");
  const bubble = el("div", "bubble");
  bubble.innerHTML = renderMarkdown(stripDisclaimer(content));
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  renderSources(wrap, sources);
  wrap.appendChild(disclaimerBlock());
  syncComposerNotice();
}

async function openSession(sessionId) {
  try {
    const response = await api("/api/sessions/" + encodeURIComponent(sessionId));
    if (!response.ok) throw new Error("session missing");
    const data = await response.json();
    state.sessionId = sessionId;
    localStorage.setItem(SESSION_KEY, sessionId);
    messages.innerHTML = "";
    data.messages.forEach((message) => {
      if (message.role === "user") {
        const fileMatch = message.content.match(/^\[Fayl: (.+?)\]\s*/);
        addUserMessage(
          fileMatch ? message.content.slice(fileMatch[0].length) : message.content,
          fileMatch ? fileMatch[1] : null
        );
      } else {
        renderAssistantMessage(message.content, message.sources);
      }
    });
    if (!data.messages.length) showEmptyState();
    activateView("chat");
    highlightActiveSession();
    chatScroll.scrollTop = chatScroll.scrollHeight;
  } catch (error) {
    localStorage.removeItem(SESSION_KEY);
    state.sessionId = null;
    showEmptyState();
  }
}

/* ---------- attachments ---------- */

const EXT_MIMES = {
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  txt: "text/plain",
  md: "text/markdown",
};

function clearAttachment() {
  state.attachment = null;
  $("file-input").value = "";
  $("attach-chip").hidden = true;
}

$("attach").addEventListener("click", () => $("file-input").click());
$("attach-remove").addEventListener("click", clearAttachment);

$("file-input").addEventListener("change", () => {
  const file = $("file-input").files[0];
  if (!file) return;
  if (file.size > MAX_FILE_BYTES) {
    alert("Fayl hajmi 10 MB dan oshmasligi kerak.");
    clearAttachment();
    return;
  }
  const ext = file.name.split(".").pop().toLowerCase();
  const mime = file.type || EXT_MIMES[ext] || "";
  const reader = new FileReader();
  reader.onload = () => {
    state.attachment = { name: file.name, mime, data: reader.result.split(",")[1] };
    $("attach-name").textContent = file.name;
    $("attach-chip").hidden = false;
  };
  reader.readAsDataURL(file);
});

/* ---------- chat ---------- */

function addUserMessage(text, fileName) {
  const empty = $("empty");
  if (empty) empty.remove();
  const wrap = el("div", "msg user");
  const bubble = el("div", "bubble");
  if (fileName) {
    bubble.appendChild(el("span", "file-tag", fileName));
    bubble.appendChild(el("div", null, text));
  } else {
    bubble.textContent = text;
  }
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  syncComposerNotice();
  scrollDown();
}

function addBotMessage() {
  const wrap = el("div", "msg bot");
  const bubble = el("div", "bubble");
  const typing = el("span", "typing");
  typing.innerHTML = "<i></i><i></i><i></i>";
  bubble.appendChild(typing);
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  scrollDown();
  return { wrap, bubble, typing };
}

// a source found live on lex.uz names a document but no article, so the article suffix
// has to stay optional
function sourceLabel(source) {
  const title = source.doc_title || "Hujjat";
  return source.article_no ? `${title}, ${source.article_no}-modda` : title;
}

function renderSources(wrap, sources) {
  if (!sources || !sources.length) return;
  const box = el("div", "sources");
  box.appendChild(el("div", "sources-title", "Manbalar"));
  sources.forEach((source) => {
    const button = el("button", "source");
    if (source.source_url) {
      const link = el("a", "source-link", sourceLabel(source));
      link.href = source.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.addEventListener("click", (event) => event.stopPropagation());
      button.appendChild(link);
    } else {
      button.appendChild(el("b", "source-link", sourceLabel(source)));
    }
    if (source.live) button.appendChild(el("span", "live-badge", "real vaqtda tekshirildi"));
    if (source.article_title) button.appendChild(el("span", null, source.article_title));
    button.addEventListener("click", () => openSource(source));
    box.appendChild(button);
  });
  wrap.appendChild(box);
  scrollDown();
}

function scrollDown() {
  chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: "smooth" });
}

function setBusy(busy) {
  state.busy = busy;
  sendButton.disabled = busy;
}

async function ask(question) {
  if (!question.trim() || state.busy) return;
  setBusy(true);
  const attachment = state.attachment;
  clearAttachment();
  addUserMessage(question, attachment ? attachment.name : null);
  const { wrap, bubble, typing } = addBotMessage();

  try {
    if (state.agentic) {
      await askAgentic(question, attachment, wrap, bubble, typing);
    } else {
      await askStreaming(question, attachment, wrap, bubble, typing);
    }
  } catch (error) {
    if (typing.isConnected) typing.remove();
    bubble.classList.add("error");
    bubble.textContent = "Xatolik: " + error.message;
  } finally {
    setBusy(false);
    loadSessions();
  }
}

async function readError(response) {
  let detail = null;
  try {
    const data = await response.json();
    detail = data.detail;
  } catch (ignored) {}

  // a plan or quota refusal is not a failure to report as one: the user is told what
  // is in the way and shown the tariffs
  if (detail && typeof detail === "object") {
    if (detail.error === "quota_exceeded" || detail.error === "feature_not_in_plan") {
      loadAccount();
      setTimeout(openPlans, 400);
    }
    return detail.message || detail.error || "Server xatosi: " + response.status;
  }
  if (typeof detail === "string") return detail;
  if (response.status === 413) return "Fayl juda katta.";
  if (response.status === 429) return "Juda ko'p so'rov yuborildi. Bir oz kuting.";
  return "Server xatosi: " + response.status;
}

// tool calls interleave with generation, so this path has nothing to stream and the
// wait needs a visible explanation instead
async function askAgentic(question, attachment, wrap, bubble, typing) {
  const note = el("div", "thinking", attachment ? t("readingFile") : t("thinking"));
  bubble.appendChild(note);

  const response = await api("/api/chat/agentic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      agent: state.agent,
      session_id: state.sessionId,
      stream: false,
      attachment,
    }),
  });
  if (!response.ok) throw new Error(await readError(response));

  const data = await response.json();
  if (typing.isConnected) typing.remove();
  state.sessionId = data.session_id;
  localStorage.setItem(SESSION_KEY, data.session_id);
  bubble.innerHTML = renderMarkdown(stripDisclaimer(data.answer || t("answerFailed")));
  if (data.document) wrap.appendChild(window.HuquqDraft.preview(data.document));
  renderSources(wrap, data.sources);
  wrap.appendChild(disclaimerBlock());
  loadAccount();
}

async function askStreaming(question, attachment, wrap, bubble, typing) {
  let answer = "";
  if (attachment) {
    bubble.appendChild(el("div", "thinking", t("readingFile")));
  }
  const response = await api("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      agent: state.agent,
      session_id: state.sessionId,
      stream: true,
      attachment,
    }),
  });
  if (!response.ok) throw new Error(await readError(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();

    for (const part of parts) {
      const eventMatch = part.match(/^event: (.+)$/m);
      const dataMatch = part.match(/^data: (.+)$/m);
      if (!eventMatch || !dataMatch) continue;
      const payload = JSON.parse(dataMatch[1]);

      if (eventMatch[1] === "meta") {
        state.sessionId = payload.session_id;
        localStorage.setItem(SESSION_KEY, payload.session_id);
      } else if (eventMatch[1] === "token") {
        if (typing.isConnected) typing.remove();
        answer += payload.text;
        bubble.innerHTML = renderMarkdown(answer);
        scrollDown();
      } else if (eventMatch[1] === "document") {
        if (typing.isConnected) typing.remove();
        wrap.appendChild(window.HuquqDraft.preview(payload.document));
        scrollDown();
      } else if (eventMatch[1] === "sources") {
        renderSources(wrap, payload.sources);
      } else if (eventMatch[1] === "done") {
        noteQuotaUsed(payload.quota);
      } else if (eventMatch[1] === "error") {
        throw new Error(payload.message);
      }
    }
  }
  if (!answer) {
    bubble.textContent = t("answerFailed");
    return;
  }
  bubble.innerHTML = renderMarkdown(stripDisclaimer(answer));
  wrap.appendChild(disclaimerBlock());
  scrollDown();
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = questionInput.value;
  questionInput.value = "";
  questionInput.style.height = "auto";
  ask(text);
});

questionInput.addEventListener("input", () => {
  questionInput.style.height = "auto";
  questionInput.style.height = Math.min(questionInput.scrollHeight, 180) + "px";
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

/* ---------- agentic ring toggle ---------- */

function setAgentic(on) {
  state.agentic = on;
  $("agentic").classList.toggle("on", on);
  $("agentic").setAttribute("aria-pressed", String(on));
}

$("agentic").addEventListener("click", () => setAgentic(!state.agentic));

/* ---------- documents ---------- */
let documentsCache = [];

async function ensureDocuments() {
  if (!documentsCache.length) {
    const response = await api("/api/documents");
    documentsCache = await response.json();
  }
  return documentsCache;
}

async function loadDocuments() {
  const list = $("doc-list");
  if (!documentsCache.length) {
    list.innerHTML = "";
    list.appendChild(el("p", null, "Yuklanmoqda..."));
  }
  try {
    await ensureDocuments();
    renderDocuments(documentsCache);
  } catch (error) {
    list.innerHTML = "";
    list.appendChild(el("p", "error", "Hujjatlarni yuklab bo'lmadi."));
  }
}

function renderDocuments(items) {
  const list = $("doc-list");
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("p", null, "Hujjat topilmadi."));
    return;
  }
  items.forEach((doc) => {
    const card = el("button", "doc");
    card.appendChild(el("h3", null, doc.title));
    const bits = [doc.adopted_date, doc.articles ? doc.articles + " modda" : null]
      .filter(Boolean)
      .join(" · ");
    card.appendChild(el("p", null, bits));
    card.addEventListener("click", () => openDocument(doc.doc_id));
    list.appendChild(card);
  });
}

$("doc-query").addEventListener("input", (event) => {
  const needle = event.target.value.toLowerCase();
  renderDocuments(documentsCache.filter((doc) => doc.title.toLowerCase().includes(needle)));
});

/* ---------- global search ---------- */

function openGlobalSearch() {
  $("search-modal").hidden = false;
  $("global-query").value = "";
  renderSearchResults("");
  closeSidebar();
  ensureDocuments().then(() => renderSearchResults($("global-query").value));
  $("global-query").focus();
}

function closeGlobalSearch() {
  $("search-modal").hidden = true;
}

function renderSearchResults(needle) {
  const box = $("search-results");
  box.innerHTML = "";
  const query = needle.trim().toLowerCase();
  if (!query) {
    box.appendChild(el("p", "search-note", "Hujjat nomini yozing — masalan, \"mehnat kodeksi\"."));
    return;
  }
  const matches = documentsCache
    .filter((doc) => doc.title.toLowerCase().includes(query))
    .slice(0, 30);
  if (!matches.length) {
    box.appendChild(el("p", "search-note", "Hech narsa topilmadi."));
    return;
  }
  matches.forEach((doc) => {
    const row = el("button", "search-hit");
    row.appendChild(document.createTextNode(doc.title));
    const bits = [doc.adopted_date, doc.articles ? doc.articles + " modda" : null]
      .filter(Boolean)
      .join(" · ");
    if (bits) row.appendChild(el("small", null, bits));
    row.addEventListener("click", () => {
      closeGlobalSearch();
      openDocument(doc.doc_id);
    });
    box.appendChild(row);
  });
}

$("nav-search").addEventListener("click", openGlobalSearch);
$("search-close").addEventListener("click", closeGlobalSearch);
$("search-modal").addEventListener("click", (event) => {
  if (event.target === $("search-modal")) closeGlobalSearch();
});
$("global-query").addEventListener("input", (event) => renderSearchResults(event.target.value));

/* ---------- modal ---------- */
/* ---------- going back one step ----------
   Opening something from inside settings used to close settings for good, so leaving
   the document dropped the user in the chat. Each screen now remembers where it was
   opened from and offers a way back to exactly that place. */

function setBack(modalId, run) {
  const modal = $(modalId);
  modal.dataset.hasBack = run ? "1" : "";
  modal.backTo = run || null;

  const head = modal.querySelector(".modal-head");
  const existing = head.querySelector(".modal-back");
  if (existing) existing.remove();
  if (!run) return;

  const button = el("button", "modal-back");
  button.innerHTML =
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M15 5l-7 7 7 7"/></svg>';
  button.appendChild(el("span", null, t("back")));
  button.addEventListener("click", () => closeModal(modalId));
  head.prepend(button);
}

/** Close a screen: step back to where it was opened from, or simply close. */
function closeModal(modalId) {
  const modal = $(modalId);
  const back = modal.backTo;
  modal.hidden = true;
  modal.backTo = null;
  if (back) back();
}

function showModal(title, url, build, back) {
  $("modal-title").textContent = title;
  const link = $("modal-link");
  if (url) {
    link.href = url;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
  setBack("modal", back);
  const body = $("modal-body");
  body.className = "modal-body";
  body.innerHTML = "";
  build(body);
  $("modal").hidden = false;
}

function openSource(source) {
  showModal(sourceLabel(source), source.source_url, (body) => {
    if (source.article_title) {
      const heading = el("p", null, source.article_title);
      heading.style.fontWeight = "700";
      body.appendChild(heading);
    }
    // a live hit carries no text of its own: the base does not hold the document yet
    body.appendChild(
      el(
        "p",
        null,
        source.snippet ||
          (source.live
            ? "Bu hujjat lex.uz da real vaqtda topildi, uning matni bazada yo'q. To'liq matnni havola orqali oching."
            : "")
      )
    );
  });
}

async function openDocument(docId) {
  showModal("Yuklanmoqda...", null, (body) => body.appendChild(el("p", null, "...")));
  try {
    const response = await api("/api/document/" + encodeURIComponent(docId));
    const doc = await response.json();
    showModal(doc.title, doc.url, (body) => {
      doc.articles_list.forEach((article) => {
        const row = el("div", "article");
        const link = el("a", null, `${article.article_no}-modda. ${article.article_title || ""}`);
        link.href = article.source_url;
        link.target = "_blank";
        link.rel = "noopener";
        row.appendChild(link);
        body.appendChild(row);
      });
      if (!doc.articles_list.length) body.appendChild(el("p", null, "Moddalar topilmadi."));
    });
  } catch (error) {
    showModal("Xatolik", null, (body) =>
      body.appendChild(el("p", "error", "Hujjatni ochib bo'lmadi."))
    );
  }
}

// the × closes; stepping back is what the ← is for, so tapping outside or pressing
// Escape leaves the whole stack rather than walking it
$("modal-close").addEventListener("click", () => {
  $("modal").backTo = null;
  $("modal").hidden = true;
});
$("modal").addEventListener("click", (event) => {
  if (event.target === $("modal")) {
    $("modal").backTo = null;
    $("modal").hidden = true;
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  // one step at a time: Escape backs out of the deepest screen that is open
  const open = ["checkout-modal", "modal", "plans-modal", "settings-modal"].find(
    (id) => !$(id).hidden
  );
  if (open) {
    closeModal(open);
    return;
  }
  closeGlobalSearch();
});

async function loadFreshness() {
  try {
    const response = await fetch("/api/updates?limit=1");
    const data = await response.json();
    if (!data.latest) return;
    const report = data.reports[0];
    const parts = [`So'nggi yangilanish: ${data.latest}`];
    if (report.changed) parts.push(`${report.changed} hujjat o'zgardi`);
    if (report.new) parts.push(`${report.new} yangi hujjat`);
    $("freshness").textContent = parts.join(" · ");
  } catch (error) {
    // the badge is informational; a failure here must not disturb the chat
  }
}

/* ---------- startup ---------- */

// auth.js decides whether the chat may be shown at all, and fires this once it has an
// account with the offer accepted
document.addEventListener("huquq:ready", async () => {
  applyLanguage();
  renderQuota();
  renderAccountRow();

  const savedSession = localStorage.getItem(SESSION_KEY);
  if (savedSession) {
    await openSession(savedSession);
  } else {
    showEmptyState();
  }
  loadAgents();
  loadSessions();
  loadFreshness();
});

Huquq.boot();
