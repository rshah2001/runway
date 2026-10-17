"""Background Nessie → Tiger Data sync while the API runs (live mode only).

Anything created directly in Nessie shows up in the app within one interval, without anyone
running `python -m app.ingest`. A failed run is logged and retried next interval — it never takes
the API down. `/health` reports the last result.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

log = logging.getLogger(__name__)

STATUS: dict = {"runs": 0, "last_ok": None, "last_error": None}


async def run_periodically(
    job: Callable[[], None], interval: float, *, initial_delay: float = 0, min_sleep: float = 1.0
) -> None:
    """Run the blocking `job` in a worker thread every `interval` seconds until cancelled."""
    await asyncio.sleep(initial_delay)
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(job)
            STATUS["last_ok"], STATUS["last_error"] = datetime.now(UTC).isoformat(timespec="seconds"), None
        except Exception as e:
            log.exception("background sync failed")
            # type only: messages can carry the Nessie URL, whose ?key= is the API key. Details → server log.
            STATUS["last_error"] = type(e).__name__
        STATUS["runs"] += 1
        await asyncio.sleep(max(min_sleep, interval - (time.monotonic() - started)))  # never a busy loop
