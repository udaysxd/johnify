import asyncio
from typing import AsyncIterator, Dict, Set, Optional

class SSEBroker:
    """
    Simple in-memory pub/sub broker for Server-Sent Events.
    Channels are keyed by user_id (int) so each user only receives their own updates.
    """
    def __init__(self) -> None:
        self._channels: Dict[int, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        # Store the main event loop so background threads can publish via run_coroutine_threadsafe
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            self._loop = loop
        except Exception:
            self._loop = None

    async def subscribe(self, user_id: int) -> AsyncIterator[str]:
        try:
            user_id = int(user_id)
            if user_id <= 0:
                raise ValueError("Invalid user_id")
                
            queue: asyncio.Queue = asyncio.Queue()
            async with self._lock:
                self._channels.setdefault(user_id, set()).add(queue)
                
            try:
                # Yield an initial comment to open the stream
                yield ": connected\n\n"
                # Heartbeat every ~25s to keep intermediaries from closing idle connections
                heartbeat_interval = 25.0
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                        # data must be a string already formatted as SSE event lines
                        yield data
                    except asyncio.TimeoutError:
                        # Send SSE comment as heartbeat
                        yield ": ping\n\n"
            finally:
                async with self._lock:
                    try:
                        if user_id in self._channels:
                            self._channels[user_id].discard(queue)
                            if not self._channels[user_id]:
                                self._channels.pop(user_id, None)
                    except Exception as e:
                        print(f"Error cleaning up SSE channel for user {user_id}: {e}")
                        
        except (ValueError, TypeError) as e:
            # Handle invalid user_id
            error_msg = f"Invalid user_id: {user_id}"
            print(f"SSE Error: {error_msg}")
            yield f"event: error\ndata: {error_msg}\n\n"
            return
        except Exception as e:
            error_msg = f"Internal server error: {str(e)}"
            print(f"SSE Error: {error_msg}")
            yield f"event: error\ndata: {error_msg}\n\n"
            return

    async def publish_json(self, user_id: int, event: str, payload: dict) -> None:
        import json
        data_line = f"data: {json.dumps(payload, ensure_ascii=False)}\n"
        event_line = f"event: {event}\n"
        msg = event_line + data_line + "\n"
        async with self._lock:
            queues = list(self._channels.get(int(user_id), set()))
        for q in queues:
            try:
                q.put_nowait(msg)
            except Exception:
                # Best-effort; drop if queue is full or closed
                pass

    # Thread-safe helper for background tasks running outside the main event loop
    def publish_json_threadsafe(self, user_id: int, event: str, payload: dict) -> None:
        try:
            loop = self._loop
            if loop and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(self.publish_json(int(user_id), event, payload), loop)
                # Optionally wait a tiny bit to surface exceptions early
                fut.result(timeout=2)
            else:
                # Fallback: attempt to get a running loop and schedule
                loop2 = asyncio.get_running_loop()
                loop2.create_task(self.publish_json(int(user_id), event, payload))
        except RuntimeError:
            # No running loop; last resort: create a new loop just to no-op safely
            try:
                asyncio.run(self.publish_json(int(user_id), event, payload))
            except Exception:
                pass

# Global broker instance
broker = SSEBroker()
