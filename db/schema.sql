-- Idempotent: safe to run on every start.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id              UUID PRIMARY KEY,
  session_id      UUID NOT NULL,
  filename        TEXT NOT NULL,
  pages           INT,
  status          TEXT NOT NULL,           -- processing | ready | failed
  error           TEXT,                    -- reason when status = failed
  created_at      TIMESTAMPTZ DEFAULT now(),
  last_active_at  TIMESTAMPTZ DEFAULT now()  -- drives inactive-session cleanup
);

CREATE TABLE IF NOT EXISTS chunks (
  id           BIGSERIAL PRIMARY KEY,
  document_id  UUID REFERENCES documents(id) ON DELETE CASCADE,
  page         INT NOT NULL,
  position     INT NOT NULL,
  content      TEXT NOT NULL,
  embedding    vector(384) NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_session_id_idx ON documents (session_id);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);
