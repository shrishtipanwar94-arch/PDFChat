// Chat UI: documents sidebar, conversation, preferences.

import * as api from "./api.js";
import { addMessage, clearHistory, loadHistory } from "./history.js";

const PREFS_KEY = "ragPdfChat.prefs";
const $ = id => document.getElementById(id);

const els = {
  uploadForm: $("upload-form"), fileInput: $("file-input"), uploadBtn: $("upload-btn"),
  uploadSpinner: $("upload-spinner"), uploadError: $("upload-error"),
  docList: $("doc-list"), docEmpty: $("doc-empty"), activeDoc: $("active-doc"),
  messages: $("messages"), askForm: $("ask-form"), question: $("question"), askBtn: $("ask-btn"),
  clearHistory: $("clear-history"), streamToggle: $("stream-toggle"),
  themeToggle: $("theme-toggle"), providerStatus: $("provider-status"),
};

let documents = [];
let activeId = null;
let busy = false;

// ---------- preferences (localStorage) ----------

function loadPrefs() {
  try { return { stream: true, theme: "light", lastDocument: null, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; }
  catch { return { stream: true, theme: "light", lastDocument: null }; }
}
const prefs = loadPrefs();
function savePrefs() { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {} }

function applyTheme() {
  document.documentElement.dataset.bsTheme = prefs.theme;
  els.themeToggle.innerHTML = prefs.theme === "dark" ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon"></i>';
}

// ---------- rendering ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderSources(container, sources) {
  container.querySelector(".sources")?.remove();
  if (!sources?.length) return;
  const details = el("details", "sources mt-1");
  details.append(el("summary", null, `Sources (${sources.length})`));
  for (const s of sources) {
    const item = el("div", "source");
    item.append(el("span", "page", `Page ${s.page}: `), document.createTextNode(s.snippet));
    details.append(item);
  }
  container.append(details);
}

function renderMessage(msg) {
  const wrap = el("div", `msg msg-${msg.role}${msg.error ? " msg-error" : ""}`);
  const bubble = el("div", "bubble", msg.content);
  wrap.append(bubble);
  if (msg.role === "assistant") {
    if (msg.provider) wrap.append(el("div", "msg-meta", `Answered by ${msg.provider}`));
    renderSources(wrap, msg.sources);
  }
  els.messages.append(wrap);
  els.messages.scrollTop = els.messages.scrollHeight;
  return { wrap, bubble };
}

function renderEmptyChat(text) {
  els.messages.replaceChildren(el("p", "text-body-secondary text-center mt-5", text));
}

function renderDocuments() {
  els.docList.replaceChildren();
  els.docEmpty.classList.toggle("d-none", documents.length > 0);
  for (const doc of documents) {
    const li = el("li", "list-group-item list-group-item-action" + (doc.id === activeId ? " active" : ""));
    const icon = doc.status === "ready" ? "bi-file-earmark-pdf" : doc.status === "failed" ? "bi-exclamation-triangle text-danger" : "bi-hourglass-split";
    li.append(el("i", `bi ${icon}`));
    const name = el("span", "doc-name", doc.filename);
    name.title = doc.status === "failed" ? doc.error || "Failed" : `${doc.pages ?? "?"} pages`;
    li.append(name);
    const del = el("button", "btn btn-sm btn-outline-danger btn-delete");
    del.innerHTML = '<i class="bi bi-x"></i>';
    del.title = "Delete document";
    del.addEventListener("click", e => { e.stopPropagation(); removeDocument(doc); });
    li.append(del);
    li.addEventListener("click", () => selectDocument(doc.id));
    els.docList.append(li);
  }
}

function setAskEnabled(enabled) {
  els.question.disabled = !enabled;
  els.askBtn.disabled = !enabled;
}

// ---------- actions ----------

async function refreshDocuments() {
  documents = await api.listDocuments();
  renderDocuments();
}

async function selectDocument(id) {
  const doc = documents.find(d => d.id === id);
  if (!doc) return;
  activeId = id;
  prefs.lastDocument = id;
  savePrefs();
  renderDocuments();
  els.activeDoc.textContent = doc.filename;
  els.clearHistory.classList.toggle("d-none", doc.status !== "ready");

  if (doc.status === "failed") {
    setAskEnabled(false);
    renderEmptyChat(`This document could not be indexed: ${doc.error || "unknown error"}`);
    return;
  }
  if (doc.status !== "ready") {
    setAskEnabled(false);
    renderEmptyChat("This document is still being processed.");
    return;
  }
  setAskEnabled(!busy);
  const history = await loadHistory(id);
  if (!history.length) renderEmptyChat(`Ask anything about ${doc.filename} (${doc.pages} pages).`);
  else { els.messages.replaceChildren(); history.forEach(renderMessage); }
  els.question.focus();
}

async function removeDocument(doc) {
  if (!confirm(`Delete "${doc.filename}" and its chat history?`)) return;
  try {
    await api.deleteDocument(doc.id);
    await clearHistory(doc.id);
    if (activeId === doc.id) {
      activeId = null;
      els.activeDoc.textContent = "Select or upload a document";
      els.clearHistory.classList.add("d-none");
      setAskEnabled(false);
      renderEmptyChat("");
    }
    await refreshDocuments();
  } catch (err) {
    alert(err.message);
  }
}

async function upload(e) {
  e.preventDefault();
  const file = els.fileInput.files[0];
  els.uploadError.textContent = "";
  if (!file) { els.uploadError.textContent = "Choose a PDF first."; return; }

  els.uploadBtn.disabled = true;
  els.uploadSpinner.classList.remove("d-none");
  try {
    const doc = await api.uploadDocument(file);
    els.fileInput.value = "";
    await refreshDocuments();
    await selectDocument(doc.id);
    if (doc.status === "failed") els.uploadError.textContent = doc.error;
  } catch (err) {
    els.uploadError.textContent = err.message;
  } finally {
    els.uploadBtn.disabled = false;
    els.uploadSpinner.classList.add("d-none");
  }
}

async function submitQuestion(e) {
  e.preventDefault();
  const question = els.question.value.trim();
  if (!question || !activeId || busy) return;
  const documentId = activeId;

  if (els.messages.querySelector(".msg") === null) els.messages.replaceChildren();
  const userMsg = { role: "user", content: question };
  renderMessage(userMsg);
  addMessage(documentId, userMsg);
  els.question.value = "";
  autoGrow();

  busy = true;
  setAskEnabled(false);
  const { wrap, bubble } = renderMessage({ role: "assistant", content: "" });
  bubble.classList.add("typing");
  const answer = { role: "assistant", content: "", sources: [], provider: null };

  const fail = message => {
    wrap.classList.add("msg-error");
    answer.error = true;
    answer.content = answer.content ? `${answer.content}\n\n⚠ ${message}` : message;
    bubble.textContent = answer.content;
  };

  try {
    if (prefs.stream) {
      await api.askStream(documentId, question, {
        onSources: sources => { answer.sources = sources; },
        onProvider: p => { answer.provider = p.provider; },
        onToken: text => {
          answer.content += text;
          bubble.textContent = answer.content;
          els.messages.scrollTop = els.messages.scrollHeight;
        },
        onError: fail,
      });
    } else {
      const res = await api.ask(documentId, question);
      Object.assign(answer, { content: res.answer, sources: res.sources, provider: res.provider });
      bubble.textContent = res.answer;
    }
  } catch (err) {
    fail(err.message);
  } finally {
    bubble.classList.remove("typing");
    answer.content = answer.content.trim();
    if (answer.provider && !answer.error) wrap.append(el("div", "msg-meta", `Answered by ${answer.provider}`));
    renderSources(wrap, answer.sources);
    els.messages.scrollTop = els.messages.scrollHeight;
    addMessage(documentId, answer);
    busy = false;
    if (activeId === documentId) setAskEnabled(true);
    els.question.focus();
  }
}

function autoGrow() {
  els.question.style.height = "auto";
  els.question.style.height = Math.min(els.question.scrollHeight, 160) + "px";
}

// ---------- wiring ----------

els.uploadForm.addEventListener("submit", upload);
els.askForm.addEventListener("submit", submitQuestion);
els.question.addEventListener("input", autoGrow);
els.question.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); els.askForm.requestSubmit(); }
});
els.clearHistory.addEventListener("click", async () => {
  if (!activeId || !confirm("Clear this document's chat history on this device?")) return;
  await clearHistory(activeId);
  selectDocument(activeId);
});
els.streamToggle.checked = prefs.stream;
els.streamToggle.addEventListener("change", () => { prefs.stream = els.streamToggle.checked; savePrefs(); });
els.themeToggle.addEventListener("click", () => {
  prefs.theme = prefs.theme === "dark" ? "light" : "dark";
  savePrefs();
  applyTheme();
});

async function init() {
  applyTheme();
  renderEmptyChat("Upload a PDF to get started.");
  try {
    const { providers } = await api.getModels();
    els.providerStatus.textContent = providers.length
      ? `LLM: ${providers.map(p => p.name).join(" → ")}`
      : "No LLM provider configured";
  } catch {}
  try {
    await refreshDocuments();
    const last = documents.find(d => d.id === prefs.lastDocument) || documents[0];
    if (last) await selectDocument(last.id);
  } catch (err) {
    els.uploadError.textContent = err.message;
  }
}

init();
