const state = { agent: "umumiy", sessionId: null, busy: false, agentic: false, attachment: null };

const MAX_FILE_BYTES = 10 * 1024 * 1024;

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

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); closeList(); continue; }
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

/* ---------- welcome screen ---------- */

const SAMPLES = [
  { cat: "Imkoniyatlar", q: "Sen menga qanday yordam bera olasan?" },
  { cat: "Oila huquqi", q: "Nikoh qaysi yoshdan tuzilishi mumkin?" },
  { cat: "Modda bo'yicha", q: "Fuqarolik kodeksining 173-moddasi nima haqida?" },
  { cat: "Mehnat huquqi", q: "Ish haqi qanday muddatlarda to'lanishi kerak?" },
];

function greeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 11) return "Xayrli tong";
  if (hour >= 11 && hour < 18) return "Xayrli kun";
  return "Xayrli kech";
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
  SAMPLES.forEach((sample) => {
    const card = el("button", "sample");
    card.appendChild(el("span", "cat", sample.cat));
    card.appendChild(el("span", "q", sample.q));
    card.addEventListener("click", () => ask(sample.q));
    grid.appendChild(card);
  });
  empty.appendChild(grid);
  messages.appendChild(empty);
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

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    item.classList.add("active");
    $("view-" + item.dataset.view).classList.add("active");
    if (item.dataset.view === "docs") loadDocuments();
    closeSidebar();
  });
});

$("new-chat").addEventListener("click", () => {
  state.sessionId = null;
  clearAttachment();
  showEmptyState();
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  document.querySelector('.nav-item[data-view="chat"]').classList.add("active");
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $("view-chat").classList.add("active");
  closeSidebar();
  questionInput.focus();
});

async function loadAgents() {
  try {
    const response = await fetch("/api/agents");
    const data = await response.json();
    const box = $("agents");
    box.innerHTML = "";
    data.agents.forEach((agent) => {
      const button = el("button", "agent" + (agent.key === state.agent ? " active" : ""), agent.name);
      button.title = agent.description;
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
    const tag = el("span", "file-tag", fileName);
    bubble.appendChild(tag);
    bubble.appendChild(el("div", null, text));
  } else {
    bubble.textContent = text;
  }
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
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
    button.appendChild(el("b", null, sourceLabel(source)));
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
  }
}

async function readError(response) {
  try {
    const data = await response.json();
    if (data.detail) return data.detail;
  } catch (ignored) {}
  return "Server xatosi: " + response.status;
}

// tool calls interleave with generation, so this path has nothing to stream and the
// wait needs a visible explanation instead
async function askAgentic(question, attachment, wrap, bubble, typing) {
  const note = el("div", "thinking",
    attachment
      ? "Hujjat o'qilmoqda va baza qidirilmoqda..."
      : "O'ylanmoqda: baza qidirilmoqda, kerak bo'lsa lex.uz tekshiriladi...");
  bubble.appendChild(note);

  const response = await fetch("/api/chat/agentic", {
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
  bubble.innerHTML = renderMarkdown(data.answer || "Javob olinmadi.");
  renderSources(wrap, data.sources);
}

async function askStreaming(question, attachment, wrap, bubble, typing) {
  let answer = "";
  if (attachment) {
    bubble.appendChild(el("div", "thinking", "Hujjat o'qilmoqda va baza qidirilmoqda..."));
  }
  const response = await fetch("/api/chat", {
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
      } else if (eventMatch[1] === "token") {
        if (typing.isConnected) typing.remove();
        answer += payload.text;
        bubble.innerHTML = renderMarkdown(answer);
        scrollDown();
      } else if (eventMatch[1] === "sources") {
        renderSources(wrap, payload.sources);
      } else if (eventMatch[1] === "error") {
        throw new Error(payload.message);
      }
    }
  }
  if (!answer) bubble.textContent = "Javob olinmadi.";
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

/* ---------- documents ---------- */
let documentsCache = [];

async function loadDocuments() {
  if (documentsCache.length) return renderDocuments(documentsCache);
  const list = $("doc-list");
  list.innerHTML = "";
  list.appendChild(el("p", null, "Yuklanmoqda..."));
  try {
    const response = await fetch("/api/documents");
    documentsCache = await response.json();
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

/* ---------- modal ---------- */
function showModal(title, url, build) {
  $("modal-title").textContent = title;
  const link = $("modal-link");
  if (url) {
    link.href = url;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
  const body = $("modal-body");
  body.innerHTML = "";
  build(body);
  $("modal").hidden = false;
}

function openSource(source) {
  showModal(sourceLabel(source), source.source_url, (body) => {
    if (source.article_title) {
      const heading = el("p", null, source.article_title);
      heading.style.fontWeight = "600";
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
    const response = await fetch("/api/document/" + encodeURIComponent(docId));
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

$("modal-close").addEventListener("click", () => ($("modal").hidden = true));
$("modal").addEventListener("click", (event) => {
  if (event.target === $("modal")) $("modal").hidden = true;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("modal").hidden = true;
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

$("agentic").addEventListener("change", (event) => {
  state.agentic = event.target.checked;
});

showEmptyState();
loadAgents();
loadFreshness();
