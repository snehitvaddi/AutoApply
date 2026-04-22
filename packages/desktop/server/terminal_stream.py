"""WebSocket endpoint for streaming worker terminal output."""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .process_manager import worker

logger = logging.getLogger(__name__)


async def terminal_websocket(ws: WebSocket):
    """Stream worker stdout to the connected WebSocket client."""
    await ws.accept()

    # Send buffer backfill — snapshot first; writer thread appends
    # concurrently and iterating the live deque races.
    for line in list(worker.output_buffer):
        await ws.send_json({"type": "line", "data": line})

    # Subscribe to live output
    queue = worker.subscribe()
    try:
        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_json({"type": "line", "data": line})
            except asyncio.TimeoutError:
                # Send keepalive ping
                await ws.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Terminal WS closed: {e}")
    finally:
        worker.unsubscribe(queue)
