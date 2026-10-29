"""Session ID validation and document ownership checks.

The session ID is a random UUID the browser generates once. It isolates one
browser's documents from another's, but it is not authentication.
"""

import uuid

from fastapi import Header, HTTPException

from app.db import get_pool


def parse_uuid(value: str | None, what: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {what}")


def session_id_header(
    x_chat_session_id: str | None = Header(default=None, alias="X-Chat-Session-Id"),
) -> uuid.UUID:
    if not x_chat_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Chat-Session-Id header")
    return parse_uuid(x_chat_session_id, "session ID")


def get_owned_document(document_id: uuid.UUID, session_id: uuid.UUID) -> dict:
    """Return the document if it belongs to this session; 404 otherwise.

    A document owned by another session is reported as not found, so a session
    cannot learn whether someone else's document ID exists.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE documents SET last_active_at = now()
            WHERE id = %s AND session_id = %s
            RETURNING id, filename, pages, status, error, created_at
            """,
            (document_id, session_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(row[0]),
        "filename": row[1],
        "pages": row[2],
        "status": row[3],
        "error": row[4],
        "createdAt": row[5].isoformat() if row[5] else None,
    }
