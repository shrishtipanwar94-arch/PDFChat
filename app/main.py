"""FastAPI app: API routes plus the static frontend."""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import cleanup, db, embeddings, llm, pdf, retrieval
from app.chunking import chunk_pages
from app.config import settings
from app.prompts import build_messages
from app.ratelimit import RateLimiter
from app.sessions import get_owned_document, parse_uuid, session_id_header

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SNIPPET_CHARS = 320
MAX_QUESTION_CHARS = 2000

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0, send_default_pii=False)

limiter = RateLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    cleanup_task = asyncio.create_task(cleanup.cleanup_loop())
    # Load the embedding model in the background so the first upload is not slow.
    warmup = asyncio.create_task(asyncio.to_thread(embeddings.get_model))
    if not llm.configured_providers():
        log.warning("No LLM provider configured: set a provider key or OLLAMA_URL in .env")
    try:
        yield
    finally:
        cleanup_task.cancel()
        warmup.cancel()
        db.close_pool()


app = FastAPI(title="RAG PDF Chat", lifespan=lifespan)


def rate_limited(session_id: uuid.UUID = Depends(session_id_header)) -> uuid.UUID:
    limiter.check(str(session_id))
    return session_id


class ChatRequest(BaseModel):
    documentId: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


# ---------- health / models ----------


@app.get("/api/health")
def health():
    try:
        with db.get_pool().connection() as conn:
            conn.execute("SELECT 1")
        database = "ok"
    except Exception:
        log.exception("Health check: database unavailable")
        database = "unavailable"
    providers = [p.name for p in llm.configured_providers()]
    status = "ok" if database == "ok" and providers else "degraded"
    return {"status": status, "database": database, "providers": providers}


@app.get("/api/models")
def models():
    return {
        "providers": [
            {"name": p.name, "model": p.model, "order": i + 1}
            for i, p in enumerate(llm.configured_providers())
        ]
    }


# ---------- documents ----------


def _index_document(document_id: uuid.UUID, data: bytes) -> dict:
    """Extract, chunk, embed and store. Returns the fields to update."""
    try:
        pages = pdf.extract_pages(data)
    except pdf.PDFError as exc:
        return {"status": "failed", "error": str(exc), "pages": None}

    if not pdf.has_text(pages):
        return {
            "status": "failed",
            "error": "No text found. This looks like a scanned PDF; OCR is not supported.",
            "pages": len(pages),
        }

    chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
    vectors = embeddings.embed_texts([c.content for c in chunks])
    retrieval.store_chunks(document_id, chunks, vectors)
    return {"status": "ready", "error": None, "pages": len(pages)}


@app.post("/api/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...), session_id: uuid.UUID = Depends(rate_limited)
):
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "The file is empty")
    if not pdf.looks_like_pdf(data):
        raise HTTPException(415, "The file is not a PDF")

    document_id = uuid.uuid4()
    filename = Path(file.filename or "document.pdf").name[:255]

    with db.get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO documents (id, session_id, filename, status) VALUES (%s, %s, %s, 'processing')",
            (document_id, session_id, filename),
        )

    try:
        result = await run_in_threadpool(_index_document, document_id, data)
    except Exception:
        log.exception("Indexing failed for %s", document_id)
        result = {"status": "failed", "error": "Indexing failed. Please try again.", "pages": None}

    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE documents SET status = %s, error = %s, pages = %s WHERE id = %s",
            (result["status"], result["error"], result["pages"], document_id),
        )

    return get_owned_document(document_id, session_id)


@app.get("/api/documents")
def list_documents(session_id: uuid.UUID = Depends(session_id_header)):
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.filename, d.pages, d.status, d.error, d.created_at,
                   (SELECT count(*) FROM chunks c WHERE c.document_id = d.id)
            FROM documents d
            WHERE d.session_id = %s
            ORDER BY d.created_at DESC
            """,
            (session_id,),
        ).fetchall()
    return {
        "documents": [
            {
                "id": str(r[0]),
                "filename": r[1],
                "pages": r[2],
                "status": r[3],
                "error": r[4],
                "createdAt": r[5].isoformat() if r[5] else None,
                "chunks": r[6],
            }
            for r in rows
        ]
    }


@app.delete("/api/documents/{document_id}", status_code=204)
def delete_document(document_id: str, session_id: uuid.UUID = Depends(session_id_header)):
    doc_id = parse_uuid(document_id, "document ID")
    with db.get_pool().connection() as conn:
        cur = conn.execute(
            "DELETE FROM documents WHERE id = %s AND session_id = %s", (doc_id, session_id)
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "Document not found")


# ---------- chat ----------


async def _prepare(req: ChatRequest, session_id: uuid.UUID) -> tuple[list[dict], list[dict]]:
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "The question is empty")
    doc_id = parse_uuid(req.documentId, "document ID")
    doc = get_owned_document(doc_id, session_id)
    if doc["status"] != "ready":
        raise HTTPException(409, f"Document is not ready (status: {doc['status']})")

    query_vector = await run_in_threadpool(embeddings.embed_query, question)
    passages = await run_in_threadpool(retrieval.search, doc_id, query_vector, settings.top_k)
    sources = [
        {
            "page": p["page"],
            "snippet": p["content"][:SNIPPET_CHARS] + ("…" if len(p["content"]) > SNIPPET_CHARS else ""),
            "score": round(1 - p["distance"], 4),
        }
        for p in passages
    ]
    return build_messages(question, passages), sources


@app.post("/api/chat")
async def chat(req: ChatRequest, session_id: uuid.UUID = Depends(rate_limited)):
    messages, sources = await _prepare(req, session_id)
    try:
        answer, provider = await llm.complete(messages)
    except llm.AllProvidersFailed as exc:
        log.error("%s", exc)
        raise HTTPException(503, "No LLM provider is available right now. Please try again.")
    return {"answer": answer.strip(), "provider": provider.name, "model": provider.model, "sources": sources}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, session_id: uuid.UUID = Depends(rate_limited)):
    messages, sources = await _prepare(req, session_id)

    async def events():
        yield _sse("sources", {"sources": sources})
        async for ev in llm.stream(messages):
            kind = ev.pop("type")
            yield _sse(kind, ev)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Static frontend last, so /api routes take precedence.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
