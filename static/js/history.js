// Device-local chat history in IndexedDB, one list of messages per document.
// Falls back to an in-memory store if IndexedDB is unavailable (private mode).

const DB_NAME = "ragPdfChat";
const STORE = "messages";

let dbPromise = null;
const memory = new Map();

function openDb() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      if (!("indexedDB" in window)) return reject(new Error("no indexedDB"));
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const store = req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
        store.createIndex("documentId", "documentId");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }).catch(() => null);
  }
  return dbPromise;
}

function tx(db, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const result = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(result?.result ?? result);
    t.onerror = () => reject(t.error);
  });
}

export async function loadHistory(documentId) {
  const db = await openDb();
  if (!db) return [...(memory.get(documentId) || [])];
  const rows = await tx(db, "readonly", s => s.index("documentId").getAll(documentId));
  return rows.sort((a, b) => a.createdAt - b.createdAt);
}

export async function addMessage(documentId, message) {
  const record = { ...message, documentId, createdAt: Date.now() };
  const db = await openDb();
  if (!db) {
    if (!memory.has(documentId)) memory.set(documentId, []);
    memory.get(documentId).push(record);
    return;
  }
  await tx(db, "readwrite", s => s.add(record));
}

export async function clearHistory(documentId) {
  memory.delete(documentId);
  const db = await openDb();
  if (!db) return;
  const rows = await tx(db, "readonly", s => s.index("documentId").getAllKeys(documentId));
  await tx(db, "readwrite", s => rows.forEach(k => s.delete(k)));
}
