# RAG PDF Chat

Upload a PDF, ask questions about it, and get answers grounded in the document,
with the passages each answer came from shown alongside it.

One Python service does everything: it serves the frontend, extracts and chunks
the PDF, embeds the chunks, stores them in PostgreSQL with pgvector, retrieves
the most relevant passages for each question, and asks an LLM to answer from
those passages only. No login is required; each browser gets its own isolated
session.

---

## Features

- **PDF question answering** grounded in retrieved passages, not the model's general knowledge
- **Source snippets** with page numbers, so every answer can be checked against the document
- **Streaming answers** over Server-Sent Events, or a plain JSON response
- **LLM provider failover** across free-tier providers (Groq, OpenRouter, Gemini); Ollama for fully local runs
- **Anonymous session isolation**: each browser's documents and chunks are visible only to that session
- **Persistent vectors** in PostgreSQL + pgvector, so indexes survive a server restart
- **Rate limiting and cleanup** of inactive sessions' documents and chunks
- **Device-local chat history** (IndexedDB) and preferences (localStorage); nothing about the conversation is stored server-side beyond the session's documents

## Tech stack

| Component | Technology |
| --- | --- |
| Frontend | HTML, CSS, Bootstrap 5, vanilla JavaScript (served by FastAPI) |
| Backend | Python, FastAPI, Uvicorn |
| PDF extraction | PyMuPDF |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, 384 dimensions) |
| Database | PostgreSQL 16 + pgvector, via `psycopg` |
| LLM | Groq / OpenRouter / Gemini with failover; Ollama optional |
| Error tracking | Sentry (optional) |

## How it works

```
Upload                                   Question
  │                                         │
  ▼                                         ▼
Extract text per page (PyMuPDF)          Embed the question (same model)
  │                                         │
  ▼                                         ▼
Split into overlapping chunks            pgvector search: top-k chunks
  │                                      for this session's document
  ▼                                         │
Embed each chunk (MiniLM, 384-d)            ▼
  │                                      Prompt = instructions + chunks + question
  ▼                                         │
Store chunk text, page, vector              ▼
in PostgreSQL                            LLM (with provider failover)
                                            │
                                            ▼
                                         Answer + source snippets
                                         (streamed over SSE or as JSON)
```

**Chunking.** Text is split into chunks of about 800 characters with 120
characters of overlap, keeping the page number on every chunk. The overlap
stops a sentence that straddles a boundary from being lost to both chunks.

**Retrieval.** The question is embedded with the same model and compared to
the document's chunks by cosine distance. The top 5 are sent to the LLM.

```sql
SELECT id, page, content
FROM chunks
WHERE document_id = %s
ORDER BY embedding <=> %s
LIMIT 5;
```

Filtering by `document_id` in the same query is one reason for pgvector over a
separate vector store: the access check and the similarity search are one SQL
statement.

**Grounding.** The prompt tells the model to answer only from the supplied
passages and to say the answer is not in the document when it isn't. The
passages are returned with the answer so the user can verify it.

**Failover.** Providers are tried in order. A timeout, a 429 rate limit or a
5xx error moves to the next provider. If a provider fails after streaming has
started, the stream ends with an error event rather than silently switching
mid-answer, so the user never sees half of one model's answer joined to
another's.

## Project structure

```
rag-pdf-chat/
├── app/
│   ├── main.py            # FastAPI app, routes, static file serving
│   ├── config.py          # settings from environment variables
│   ├── db.py              # psycopg connection pool
│   ├── sessions.py        # session ID validation and ownership checks
│   ├── pdf.py             # text extraction per page
│   ├── chunking.py        # overlapping chunker
│   ├── embeddings.py      # sentence-transformers model, loaded once
│   ├── retrieval.py       # pgvector similarity search
│   ├── llm.py             # provider clients and failover
│   ├── prompts.py         # grounding prompt
│   ├── ratelimit.py       # per-session request rate limiting
│   └── cleanup.py         # deletes inactive sessions' data
├── static/
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── api.js         # fetch + SSE handling
│       ├── chat.js        # chat UI
│       └── history.js     # IndexedDB chat history
├── db/
│   └── schema.sql
├── tests/
├── eval/
│   ├── make_sample_pdf.py # builds the sample PDF the questions refer to
│   ├── questions.json     # hand-labelled question set
│   └── run_eval.py
├── docker-compose.yml     # PostgreSQL + pgvector
├── requirements.txt
├── .env.example
└── README.md
```

## Running locally

**Prerequisites:** Python 3.10+, Docker (for PostgreSQL + pgvector), and at
least one LLM provider key or a running Ollama.

```bash
docker compose up -d                      # PostgreSQL 16 with pgvector, on host port 5434
python -m venv venv
source venv/bin/activate                  # Windows: venv\Scriptsctivate
pip install -r requirements.txt

cp .env.example .env                      # add at least one provider key, or OLLAMA_URL

uvicorn app.main:app --reload
```

The schema in `db/schema.sql` is applied automatically, both by the database
container on first start and by the app on every start (it is idempotent), so
`psql` is not needed. To apply it by hand: `psql "$DATABASE_URL" -f db/schema.sql`.

Open http://localhost:8000. The embedding model downloads on first start
(about 90 MB).

For a fully local run with no API keys, set `OLLAMA_URL=http://localhost:11434`
and `OLLAMA_MODEL` to a model you have pulled (e.g. `ollama pull qwen2.5:3b`).

**Tests:** `pytest` runs the unit tests; the API tests in `tests/test_api.py`
also run when the database is reachable (the LLM is stubbed).

**Evaluation:** with the server running,

```bash
python eval/make_sample_pdf.py
python eval/run_eval.py
```

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | PostgreSQL connection string |
| `GROQ_API_KEY` | one provider | Groq |
| `OPENROUTER_API_KEY` | one provider | OpenRouter (`:free` models) |
| `GEMINI_API_KEY` | one provider | Gemini |
| `OLLAMA_URL` | optional | Local Ollama, e.g. `http://localhost:11434` |
| `OLLAMA_MODEL` | optional | Ollama model (default `qwen2.5:3b`) |
| `GROQ_MODEL` / `OPENROUTER_MODEL` / `GEMINI_MODEL` | optional | Override each provider's default model |
| `PROVIDER_ORDER` | optional | Failover order (default `groq,openrouter,gemini,ollama`); unconfigured providers are skipped |
| `RATE_LIMIT_PER_MINUTE` | optional | Uploads + questions per session per minute (default 30) |
| `MAX_UPLOAD_MB` | optional | Upload size limit (default 10) |
| `SESSION_TTL_HOURS` | optional | Inactive sessions are deleted after this (default 24) |
| `SENTRY_DSN` | optional | Error tracking |

## API

Every request carries an `X-Chat-Session-Id` header: a random UUID the browser
generates once and keeps in localStorage.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service and database status |
| POST | `/api/documents` | Upload and index a PDF |
| GET | `/api/documents` | This session's documents |
| DELETE | `/api/documents/{id}` | Delete a document and its chunks |
| POST | `/api/chat` | Ask a question, JSON response |
| POST | `/api/chat/stream` | Ask a question, SSE response |
| GET | `/api/models` | Available providers and models |

Example:

```http
POST /api/chat
X-Chat-Session-Id: 6f1c2e0a-...
Content-Type: application/json

{ "documentId": "b3e1...", "question": "What is the refund policy?" }
```

```json
{
  "answer": "Refunds are allowed within 30 days of purchase...",
  "provider": "groq",
  "sources": [
    { "page": 4, "snippet": "Customers may request a refund within 30 days..." }
  ]
}
```

## Database

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id          UUID PRIMARY KEY,
  session_id  UUID NOT NULL,
  filename    TEXT NOT NULL,
  pages       INT,
  status      TEXT NOT NULL,           -- processing | ready | failed
  error       TEXT,                    -- reason when status = failed
  created_at  TIMESTAMPTZ DEFAULT now(),
  last_active_at TIMESTAMPTZ DEFAULT now()  -- drives inactive-session cleanup
);

CREATE TABLE chunks (
  id           BIGSERIAL PRIMARY KEY,
  document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
  page         INT NOT NULL,
  position     INT NOT NULL,
  content      TEXT NOT NULL,
  embedding    vector(384) NOT NULL
);

CREATE INDEX ON documents (session_id);
CREATE INDEX ON chunks (document_id);
```

Search is exact (no approximate index). At the size of one user's documents
that is fast enough; an HNSW index would be the next step for millions of
chunks.

## Security

- Every document query checks that the document belongs to the requesting session.
- Uploads are checked by file signature and size, not by filename or MIME type alone.
- All SQL is parameterised.
- Provider keys stay on the server.
- PDF text is treated as untrusted: it goes into the prompt as quoted context, below the instructions, and cannot trigger any action.
- The session ID is an unguessable random UUID but is not authentication. Anyone holding it can read that session's documents, which is acceptable for an anonymous demo and not for private documents.

## Evaluation

`eval/run_eval.py` runs a hand-labelled question set against one sample PDF
(`eval/sample.pdf`, a 7-page fictional handbook built by `eval/make_sample_pdf.py`)
and reports retrieval and answer accuracy separately:

- **Retrieval:** did the top 5 chunks include the page that holds the answer?
- **Answer:** was the answer correct, and did the model say "not in the document" for questions with no answer?

| Measure | Result |
| --- | --- |
| Retrieval hit rate (top 5) | 20 / 20 |
| Correct answers | 20 / 20 |
| Correctly refused (answer not in PDF) | 5 / 5 |

The questions were written by the author, so read this as "does the pipeline
work", not as accuracy on arbitrary documents. Results above are from Ollama
with `qwen2.5:3b`; other models may score differently.

## Limitations

- **Text only.** Images and charts are ignored, and tables are read as plain text.
- **No OCR.** Scanned PDFs have no text layer, so nothing is extracted; the upload is marked `failed` with a message saying so.
- **One document per question.** Questions cannot span several uploaded PDFs.
- **Free-tier providers** can be slow or rate-limited; failover hides most of this, not all.

## Possible improvements

- OCR (Tesseract) for scanned PDFs
- Hybrid search: PostgreSQL full-text search combined with vector search
- Re-ranking the retrieved chunks before sending them to the LLM
- Questions across multiple documents
