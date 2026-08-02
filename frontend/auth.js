/* Sign-in, registration, and the API layer everything else calls.
 *
 * Loaded before app.js. The chat never renders until this has an account with the offer
 * accepted, so no part of the application has to ask whether there is a user.
 */

const Huquq = (() => {
  const TOKEN_KEY = "huquq_token";
  const SESSION_KEY = "huquq_session_id";

  const state = { account: null, config: null, ready: false };
  const listeners = [];

  const $ = (id) => document.getElementById(id);

  /* ---------- transport ---------- */

  function token() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(value) {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  }

  function headers(extra) {
    const merged = Object.assign({}, extra || {});
    const current = token();
    if (current) merged.Authorization = "Bearer " + current;
    return merged;
  }

  /** fetch with the token attached; a dead token drops the user back to sign-in. */
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: headers(options.headers),
    });
    if (response.status === 401 && state.ready) {
      signOut();
      return response;
    }
    return response;
  }

  async function post(path, body) {
    const response = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail || {};
      const error = new Error(detail.message || "Xatolik yuz berdi.");
      error.code = detail.error;
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return data;
  }

  /* ---------- account ---------- */

  async function refreshAccount() {
    const response = await api("/api/account");
    if (!response.ok) return null;
    state.account = await response.json();
    listeners.forEach((fn) => fn(state.account));
    return state.account;
  }

  function account() {
    return state.account;
  }

  function onAccountChange(fn) {
    listeners.push(fn);
    if (state.account) fn(state.account);
  }

  function signOut() {
    setToken(null);
    localStorage.removeItem(SESSION_KEY);
    location.reload();
  }

  /* ---------- registration flow ---------- */

  const flow = {
    phone: "",
    name: "",
    step: "method",
    resendTimer: null,
    googleReady: false,
    googleClient: null,
  };

  function showStep(name) {
    flow.step = name;
    document.querySelectorAll(".auth-step").forEach((section) => {
      section.classList.toggle("active", section.dataset.authStep === name);
    });
    const order = { method: 1, code: 1, profile: 2, terms: 3 };
    const steps = $("auth-steps");
    steps.hidden = name === "method";
    steps.querySelectorAll(".dot").forEach((dot) => {
      dot.classList.toggle("on", Number(dot.dataset.step) <= (order[name] || 1));
    });
    const focusable = {
      method: "auth-phone",
      code: null,
      profile: "auth-name",
      terms: null,
    }[name];
    if (focusable) setTimeout(() => $(focusable).focus(), 60);
    if (name === "code") setTimeout(() => codeInputs()[0].focus(), 60);
    if (name === "terms") loadTerms();
  }

  function showError(step, message) {
    const box = $("auth-error-" + step);
    if (!box) return;
    box.textContent = message || "";
    box.hidden = !message;
  }

  /* phone entry */

  function digitsOnly(value) {
    return value.replace(/\D/g, "").slice(0, 9);
  }

  function formatPhone(digits) {
    const parts = [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7, 9)];
    return parts.filter(Boolean).join(" ");
  }

  function wirePhoneInput() {
    const input = $("auth-phone");
    input.addEventListener("input", () => {
      const digits = digitsOnly(input.value);
      input.value = formatPhone(digits);
      $("auth-send-code").disabled = digits.length !== 9;
      showError("method", "");
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !$("auth-send-code").disabled) sendCode();
    });
  }

  async function sendCode() {
    const button = $("auth-send-code");
    const digits = digitsOnly($("auth-phone").value);
    button.disabled = true;
    button.textContent = "Yuborilmoqda...";
    try {
      const data = await post("/api/auth/phone/start", { phone: "+998" + digits });
      flow.phone = "+998" + digits;
      $("auth-phone-masked").textContent = data.phone_masked;
      buildCodeInputs(data);
      startResendTimer(data.resend_in);
      // the console sender puts the code here so a developer can finish the flow
      const debug = $("auth-debug");
      debug.hidden = !data.debug_code;
      if (data.debug_code) debug.textContent = "Sinov rejimi — kod: " + data.debug_code;
      showStep("code");
    } catch (error) {
      showError("method", error.message);
      if (error.detail && error.detail.retry_after) {
        startResendTimer(error.detail.retry_after);
      }
    } finally {
      button.textContent = "Kod olish";
      button.disabled = digitsOnly($("auth-phone").value).length !== 9;
    }
  }

  /* code entry */

  function codeInputs() {
    return Array.from($("code-field").querySelectorAll("input"));
  }

  function buildCodeInputs(config) {
    const field = $("code-field");
    field.innerHTML = "";
    const length = (state.config && state.config.otp_length) || 6;
    for (let index = 0; index < length; index += 1) {
      const box = document.createElement("input");
      box.type = "text";
      box.inputMode = "numeric";
      box.maxLength = 1;
      box.autocomplete = index === 0 ? "one-time-code" : "off";
      field.appendChild(box);
    }
    const boxes = codeInputs();
    boxes.forEach((box, index) => {
      box.addEventListener("input", () => {
        box.value = box.value.replace(/\D/g, "").slice(0, 1);
        box.classList.toggle("filled", Boolean(box.value));
        if (box.value && index < boxes.length - 1) boxes[index + 1].focus();
        $("auth-verify").disabled = boxes.some((item) => !item.value);
        showError("code", "");
        if (boxes.every((item) => item.value)) verifyCode();
      });
      box.addEventListener("keydown", (event) => {
        if (event.key === "Backspace" && !box.value && index > 0) boxes[index - 1].focus();
      });
      box.addEventListener("paste", (event) => {
        const text = (event.clipboardData.getData("text") || "").replace(/\D/g, "");
        if (!text) return;
        event.preventDefault();
        boxes.forEach((item, position) => {
          item.value = text[position] || "";
          item.classList.toggle("filled", Boolean(item.value));
        });
        $("auth-verify").disabled = boxes.some((item) => !item.value);
        if (boxes.every((item) => item.value)) verifyCode();
      });
    });
    void config;
  }

  function startResendTimer(seconds) {
    const button = $("auth-resend");
    clearInterval(flow.resendTimer);
    let left = Math.max(0, Math.round(seconds || 0));
    const tick = () => {
      if (left <= 0) {
        clearInterval(flow.resendTimer);
        button.disabled = false;
        button.textContent = "Kodni qayta yuborish";
        return;
      }
      button.disabled = true;
      button.textContent = `Qayta yuborish ${left} s`;
      left -= 1;
    };
    tick();
    flow.resendTimer = setInterval(tick, 1000);
  }

  async function verifyCode() {
    const code = codeInputs().map((box) => box.value).join("");
    const button = $("auth-verify");
    button.disabled = true;
    button.textContent = "Tekshirilmoqda...";
    try {
      const data = await post("/api/auth/phone/verify", { phone: flow.phone, code });
      await onAuthenticated(data);
    } catch (error) {
      showError("code", error.message);
      codeInputs().forEach((box) => {
        box.value = "";
        box.classList.remove("filled");
      });
      codeInputs()[0].focus();
    } finally {
      button.textContent = "Tasdiqlash";
      button.disabled = codeInputs().some((box) => !box.value);
    }
  }

  /* google */

  // Google's own rendered button is deliberately not used. For this client Google
  // answers the button endpoint with 403 ("origin is not allowed") while accepting the
  // popup flow below from the very same origin — see KAMCHILIKLAR.md 3.9. So our button
  // opens the popup directly and the backend gets an access token instead of an ID one.
  function loadGoogle() {
    if (!state.config.google_enabled || flow.googleReady) return;
    flow.googleReady = true;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      const oauth2 = window.google && window.google.accounts && window.google.accounts.oauth2;
      if (!oauth2) return;
      flow.googleClient = oauth2.initTokenClient({
        client_id: state.config.google_client_id,
        scope: "openid email profile",
        callback: async (response) => {
          if (!response || !response.access_token) {
            showError("method", "Google kirishi yakunlanmadi.");
            return;
          }
          try {
            const data = await post("/api/auth/google", {
              access_token: response.access_token,
            });
            await onAuthenticated(data);
          } catch (error) {
            showError("method", error.message);
          }
        },
        error_callback: (error) => {
          // a closed popup is the user changing their mind, not a failure to report
          if (error && error.type === "popup_closed") return;
          showError("method", "Google oynasi ochilmadi. Popup blokerni tekshiring.");
        },
      });
    };
    script.onerror = () => {
      $("auth-google").hidden = true;
      $("auth-or").hidden = true;
    };
    document.head.appendChild(script);
  }

  function clickGoogle() {
    if (!flow.googleClient) {
      showError("method", "Google hali yuklanmoqda, bir lahza kuting.");
      return;
    }
    flow.googleClient.requestAccessToken();
  }

  /* profile and terms */

  function saveName() {
    // The name is held here and sent once, together with the acceptance. Posting it on
    // this step meant a request the server was bound to refuse — registration is not
    // complete until the offer is accepted — so a normal sign-up logged a 400.
    const name = $("auth-name").value.trim();
    if (name.length < 2) {
      showError("profile", "Ism kamida 2 ta harfdan iborat bo'lsin.");
      return;
    }
    flow.name = name;
    showError("profile", "");
    showStep("terms");
  }

  async function loadTerms() {
    const box = $("terms-box");
    if (box.dataset.loaded) return;
    try {
      const response = await fetch("/api/legal/oferta");
      const data = await response.json();
      box.innerHTML = window.renderMarkdown
        ? window.renderMarkdown(data.markdown)
        : data.markdown.replace(/[<>]/g, "");
      box.dataset.loaded = "1";
    } catch (error) {
      box.textContent = "Shartlarni yuklab bo'lmadi. Havola orqali oching.";
    }
  }

  async function finish() {
    const button = $("auth-finish");
    button.disabled = true;
    button.textContent = "Yakunlanmoqda...";
    try {
      const name = flow.name || $("auth-name").value.trim();
      await post("/api/auth/complete", { name: name || null, accept_terms: true });
      await enterApp();
    } catch (error) {
      showError("terms", error.message);
      button.disabled = false;
      button.textContent = "Qabul qilaman va boshlash";
    }
  }

  /* ---------- routing ---------- */

  async function onAuthenticated(auth) {
    setToken(auth.token);
    if (auth.needs_profile) {
      showStep("profile");
      return;
    }
    if (auth.needs_terms) {
      showStep("terms");
      return;
    }
    await enterApp();
  }

  async function enterApp() {
    await refreshAccount();
    state.ready = true;
    $("auth-screen").hidden = true;
    $("app-layout").hidden = false;
    document.dispatchEvent(new CustomEvent("huquq:ready", { detail: state.account }));
  }

  function showAuthScreen() {
    $("app-layout").hidden = true;
    $("auth-screen").hidden = false;
    showStep("method");
  }

  async function guest() {
    try {
      const data = await post("/api/auth/anon", {});
      setToken(data.token);
      showStep("terms");
    } catch (error) {
      showError("method", error.message);
    }
  }

  function wire() {
    wirePhoneInput();
    $("auth-send-code").addEventListener("click", sendCode);
    $("auth-back-method").addEventListener("click", () => showStep("method"));
    $("auth-verify").addEventListener("click", verifyCode);
    $("auth-resend").addEventListener("click", sendCode);
    $("auth-google").addEventListener("click", clickGoogle);
    $("auth-guest").addEventListener("click", guest);
    $("auth-save-name").addEventListener("click", saveName);
    $("auth-name").addEventListener("input", () => {
      $("auth-save-name").disabled = $("auth-name").value.trim().length < 2;
      showError("profile", "");
    });
    $("auth-name").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !$("auth-save-name").disabled) saveName();
    });
    $("terms-accept").addEventListener("change", (event) => {
      $("auth-finish").disabled = !event.target.checked;
    });
    $("auth-finish").addEventListener("click", finish);
    document.querySelectorAll("[data-legal]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        if (window.openLegal) window.openLegal(button.dataset.legal);
        else window.open("/api/legal/" + button.dataset.legal, "_blank");
      });
    });
  }

  async function boot() {
    try {
      state.config = await (await fetch("/api/auth/config")).json();
    } catch (error) {
      state.config = { google_enabled: false, allow_anonymous: true, otp_length: 6 };
    }
    wire();
    const google_on = state.config.google_enabled;
    // in development the button stays, disabled, carrying the reason it cannot work;
    // in production an unconfigured button is simply not shown
    const showGoogle = google_on || Boolean(state.config.google_hint);
    $("auth-google").hidden = !showGoogle;
    $("auth-or").hidden = !showGoogle;
    $("auth-guest").hidden = !state.config.allow_anonymous;
    if (!google_on && state.config.google_hint) {
      $("auth-google").disabled = true;
      $("auth-google").title = state.config.google_hint;
      $("auth-google").querySelector("span").textContent = "Google — sozlanmagan";
      const note = $("auth-config-note");
      note.textContent = state.config.google_hint;
      note.hidden = false;
    }
    if (state.config.sms_hint) {
      const hint = $("auth-sms-hint");
      hint.textContent = state.config.sms_hint;
      hint.hidden = false;
    }
    if (google_on) loadGoogle();

    if (token()) {
      const existing = await refreshAccount();
      if (existing && existing.accepted_terms) {
        await enterApp();
        return;
      }
      if (existing) {
        showAuthScreen();
        // the account exists but has not accepted the current offer
        showStep(existing.name ? "terms" : "profile");
        return;
      }
      setToken(null);
    }
    showAuthScreen();
  }

  return { api, post, account, refreshAccount, onAccountChange, signOut, boot, config: () => state.config };
})();

window.Huquq = Huquq;
