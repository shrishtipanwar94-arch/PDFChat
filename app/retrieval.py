"""pgvector similarity search, plus storing a document's chunks."""

import uuid

import numpy as np

from app.chunking import Chunk
from app.db import get_pool


def store_chunks(document_id: uuid.UUID, chunks: list[Chunk], vectors: np.ndarray) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (document_id, page, position, content, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (document_id, c.page, c.position, c.content, vec)
                    for c, vec in zip(chunks, vectors)
                ],
            )


def search(document_id: uuid.UUID, query_vector: np.ndarray, k: int = 5) -> list[dict]:
    """Top-k chunks of one document by cosine distance.

    The caller has already checked that the document belongs to the session;
    the document_id filter keeps the search inside that document.
    """
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, page, content, embedding <=> %s AS distance
            FROM chunks
            WHERE document_id = %s
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (query_vector, document_id, query_vector, k),
        ).fetchall()
    return [
        {"id": r[0], "page": r[1], "content": r[2], "distance": float(r[3])} for r in rows
    ]
