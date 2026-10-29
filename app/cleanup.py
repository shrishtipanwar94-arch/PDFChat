"""Deletes inactive sessions' documents (and, by cascade, their chunks)."""

import asyncio
import logging

from app.config import settings
from app.db import get_pool

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


def delete_inactive(ttl_hours: int | None = None) -> int:
    """Delete documents of sessions with no activity within ttl_hours.

    A session counts as active if any of its documents was used recently, so
    one old document does not disappear while its session is still in use.
    """
    ttl = settings.session_ttl_hours if ttl_hours is None else ttl_hours
    with get_pool().connection() as conn:
        cur = conn.execute(
            """
            DELETE FROM documents
            WHERE session_id IN (
              SELECT session_id FROM documents
              GROUP BY session_id
              HAVING max(last_active_at) < now() - make_interval(hours => %s)
            )
            """,
            (ttl,),
        )
        return cur.rowcount


async def cleanup_loop() -> None:
    while True:
        try:
            deleted = await asyncio.to_thread(delete_inactive)
            if deleted:
                log.info("Cleanup deleted %d inactive document(s)", deleted)
        except Exception:
            log.exception("Cleanup failed")
        await asyncio.sleep(INTERVAL_SECONDS)
