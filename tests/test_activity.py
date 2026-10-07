import asyncio
import json
import unittest
from voice_agent.activity import ActivityStream


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_is_unchanged_and_correlated(self):
        stream = ActivityStream()
        arguments = {"pattern": "climate"}
        result = {"facts": [{"subject": "A", "relation": "supports", "object": "B"}]}
        async def operation():
            return result
        actual = await stream.track("graph", "extract", arguments, operation, call_id="call-1")
        self.assertIs(actual, result)
        start, end = stream.queue.get_nowait(), stream.queue.get_nowait()
        self.assertEqual(start["id"], end["id"])
        self.assertEqual(start["status"], "running")
        self.assertEqual(end["status"], "completed")
        self.assertEqual(end["output"], result)
        self.assertEqual(end["arguments"], arguments)

    async def test_failure_is_reported_and_propagated(self):
        stream = ActivityStream()
        async def operation():
            raise ValueError("missing page")
        with self.assertRaises(ValueError):
            await stream.track("voice", "get_page", {}, operation)
        stream.queue.get_nowait()
        self.assertEqual(stream.queue.get_nowait()["status"], "error")

    async def test_cancellation_is_reported(self):
        stream = ActivityStream()
        async def operation():
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await stream.track("voice", "get_page", {}, operation)
        stream.queue.get_nowait()
        self.assertEqual(stream.queue.get_nowait()["status"], "cancelled")

    async def test_large_output_is_chunked_without_truncation(self):
        stream = ActivityStream()
        stream.emit(id="large", output="Document evidence café → " * 3000)
        sent = []
        async def sender(event):
            sent.append(event)
        task = asyncio.create_task(stream.send(sender))
        await asyncio.wait_for(stream.queue.join(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(e["data"]) <= 12000 for e in sent))
        decoded = json.loads(''.join(e["data"] for e in sent))
        self.assertEqual(decoded["output"], "Document evidence café → " * 3000)

    async def test_sender_failure_does_not_stop_following_events(self):
        stream = ActivityStream()
        seen = []
        async def sender(event):
            seen.append(event["id"])
            if event["id"] == "first":
                raise ConnectionError()
        stream.emit(id="first")
        stream.emit(id="second")
        task = asyncio.create_task(stream.send(sender))
        await asyncio.wait_for(stream.queue.join(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(seen, ["first", "second"])


if __name__ == '__main__':
    unittest.main()
