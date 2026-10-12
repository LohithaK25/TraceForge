import asyncio
import threading
import time

from traceforge_investigation.config import Settings
from traceforge_investigation.scheduler import detection_loop


def test_scheduler_runs_without_overlapping_and_stops_after_bounded_cycle():
    async def exercise():
        stop = asyncio.Event()
        state = {"active": 0, "maximum": 0, "calls": 0}

        def run_cycle():
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            time.sleep(0.05)
            state["calls"] += 1
            state["active"] -= 1

        task = asyncio.create_task(detection_loop(run_cycle, 30, stop))
        deadline = asyncio.get_running_loop().time() + 2
        while state["calls"] == 0 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        return state

    result = asyncio.run(exercise())
    assert result["calls"] == 1
    assert result["maximum"] == 1


def test_detection_interval_has_safe_bounds():
    try:
        Settings(detection_interval_seconds=4)
        raise AssertionError("expected too-short detection interval to fail")
    except ValueError as error:
        assert "DETECTION_INTERVAL_SECONDS" in str(error)
