const state = { agent: "umumiy", sessionId: null, busy: false };

const $ = (id) => document.getElementById(id);
const messages = $("messages");
const composer = $("composer");
const questionInput = $("question");
const sendButton = $("send");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    $("view-" + tab.dataset.view).classList.add("active");
    if (tab.dataset.view === "docs") loadDocuments();
  });
});

/* ---------- agents ---------- */
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
      });
      box.appendChild(button);
    });
  } catch (error) {
    console.error("agents", error);
  }
}

/* ---------- chat ---------- */
function addUserMessage(text) {
  const empty = $("empty");
  if (empty) empty.remove();
  const wrap = el("div", "msg user");
  wrap.appendChild(el("div", "bubble", text));
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

function renderSources(wrap, sources) {
  if (!sources || !sources.length) return;
  const box = el("div", "sources");
  box.appendChild(el("div", "sources-title", "Manbalar"));
  sources.forEach((source) => {
    const button = el("button", "source");
    const title = el("b", null, `${source.doc_title || ""}, ${source.article_no}-modda`);
    button.appendChild(title);
    if (source.article_title) button.appendChild(el("span", null, source.article_title));
    button.addEventListener("click", () => openSource(source));
    box.appendChild(button);
  });
  wrap.appendChild(box);
  scrollDown();
}

function scrollDown() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function setBusy(busy) {
  state.busy = busy;
  sendButton.disabled = busy;
}

async function ask(question) {
  if (!question.trim() || state.busy) return;
  setBusy(true);
  addUserMessage(question);
  const { wrap, bubble, typing } = addBotMessage();
  let answer = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        agent: state.agent,
        session_id: state.sessionId,
        stream: true,
      }),
    });
    if (!response.ok) throw new Error("Server xatosi: " + response.status);

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
          bubble.textContent = answer;
          scrollDown();
        } else if (eventMatch[1] === "sources") {
          renderSources(wrap, payload.sources);
        } else if (eventMatch[1] === "error") {
          throw new Error(payload.message);
        }
      }
    }
    if (!answer) bubble.textContent = "Javob olinmadi.";
  } catch (error) {
    if (typing.isConnected) typing.remove();
    bubble.classList.add("error");
    bubble.textContent = "Xatolik: " + error.message;
  } finally {
    setBusy(false);
  }
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
  questionInput.style.height = Math.min(questionInput.scrollHeight, 160) + "px";
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

document.querySelectorAll(".sample").forEach((button) => {
  button.addEventListener("click", () => ask(button.textContent));
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
  showModal(
    `${source.doc_title}, ${source.article_no}-modda`,
    source.source_url,
    (body) => {
      if (source.article_title) {
        const heading = el("p", null, source.article_title);
        heading.style.fontWeight = "600";
        body.appendChild(heading);
      }
      body.appendChild(el("p", null, source.snippet || ""));
    }
  );
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

loadAgents();
loadFreshness();
