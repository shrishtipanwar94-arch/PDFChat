// fetch + SSE handling. Every request carries the anonymous session ID.

const SESSION_KEY = "ragPdfChat.sessionId";

export function getSessionId() {
  let id = null;
  try { id = localStorage.getItem(SESSION_KEY); } catch {}
  if (!id) {
    id = crypto.randomUUID();
    try { localStorage.setItem(SESSION_KEY, id); } catch {}
  }
  return id;
}

function headers(extra = {}) {
  return { "X-Chat-Session-Id": getSessionId(), ...extra };
}

async function errorMessage(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map(d => d.msg).join("; ");
  } catch {}
  return `Request failed (${res.status})`;
}

async function request(path, options = {}) {
  const res = await fetch(path, { ...options, headers: headers(options.headers) });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.status === 204 ? null : res.json();
}

export const getHealth = () => request("/api/health");
export const getModels = () => request("/api/models");
export const listDocuments = () => request("/api/documents").then(r => r.documents);
export const deleteDocument = id => request(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });

export function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/documents", { method: "POST", body: form });
}

export function ask(documentId, question) {
  return request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ documentId, question }),
  });
}

/**
 * Stream an answer over SSE. EventSource only supports GET, so this reads the
 * POST response body and parses the event stream by hand.
 * handlers: { onSources, onProvider, onToken, onDone, onError }
 */
export async function askStream(documentId, question, handlers) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }),
    body: JSON.stringify({ documentId, question }),
  });
  if (!res.ok) throw new Error(await errorMessage(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const dispatch = raw => {
    let event = "message";
    const data = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;
    const payload = JSON.parse(data.join("\n"));
    switch (event) {
      case "sources": handlers.onSources?.(payload.sources); break;
      case "provider": handlers.onProvider?.(payload); break;
      case "token": handlers.onToken?.(payload.text); break;
      case "done": finished = true; handlers.onDone?.(payload); break;
      case "error": finished = true; handlers.onError?.(payload.message); break;
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      dispatch(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  }
  if (buffer.trim()) dispatch(buffer);
  if (!finished) handlers.onError?.("The connection closed before the answer finished.");
}
