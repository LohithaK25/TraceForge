from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("traceforge.investigation")


async def detection_loop(
    run_cycle: Callable[[], object],
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    """Run one cycle at a time, then wait a fixed interval; no dashboard request drives work."""
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_cycle)
        except Exception:
            # Engine emits the safe failure code; never include upstream or database exception text here.
            logger.error("detection_scheduler_cycle_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
