"""Best-effort UI telemetry; never blocks document tools or graph execution."""

import asyncio
from datetime import datetime, timezone
import logging
import json
from time import monotonic
from uuid import uuid4

logger = logging.getLogger(__name__)


class ActivityStream:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=512)

    def emit(self, **event):
        event.update(type="agent-activity", timestamp=datetime.now(timezone.utc).isoformat())
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Activity buffer full; dropping UI event")

    async def send(self, sender):
        while True:
            event = await self.queue.get()
            try:
                # Keep each data-channel message small without truncating tool/page data.
                payload = json.dumps(event, ensure_ascii=True)
                if len(payload) <= 12000:
                    async with asyncio.timeout(2):
                        await sender(event)
                else:
                    transfer_id = str(uuid4())
                    chunks = [payload[i:i + 12000] for i in range(0, len(payload), 12000)]
                    for index, chunk in enumerate(chunks):
                        async with asyncio.timeout(2):
                            await sender({"type": "activity-chunk", "transfer_id": transfer_id,
                                          "index": index, "total": len(chunks), "data": chunk})
            except Exception:
                logger.debug("Activity client unavailable", exc_info=True)
            finally:
                self.queue.task_done()

    async def track(self, agent, name, arguments, operation, call_id=None, **metadata):
        event_id = call_id or str(uuid4())
        base = dict(id=event_id, agent=agent, name=name, arguments=arguments, **metadata)
        started = monotonic()
        self.emit(**base, status="running")
        try:
            result = await operation()
        except asyncio.CancelledError:
            self.emit(**base, status="cancelled", duration_ms=round((monotonic()-started)*1000))
            raise
        except Exception as error:
            self.emit(**base, status="error", output={"message": str(error)}, duration_ms=round((monotonic()-started)*1000))
            raise
        self.emit(**base, status="error" if isinstance(result, dict) and result.get("status") == "error" else "completed", output=result, duration_ms=round((monotonic()-started)*1000))
        return result
