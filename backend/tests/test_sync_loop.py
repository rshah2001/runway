"""The background sync must survive failures and keep its schedule."""

import asyncio

from app import sync_loop


def test_loop_keeps_running_after_a_failure_and_reports_status() -> None:
    calls = []

    def job() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Nessie down")

    async def run() -> None:
        task = asyncio.create_task(sync_loop.run_periodically(job, interval=0, min_sleep=0))
        while sync_loop.STATUS["runs"] < 2:
            await asyncio.sleep(0.01)
        task.cancel()

    sync_loop.STATUS.update(runs=0, last_ok=None, last_error=None)
    asyncio.run(run())
    assert len(calls) >= 2  # the failure did not stop the loop
    assert sync_loop.STATUS["last_ok"] is not None and sync_loop.STATUS["last_error"] is None
