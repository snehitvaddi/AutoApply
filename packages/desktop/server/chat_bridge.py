"""
Smart Chat Bridge — "Dumb Display" + /btw Questions.

Architecture:
  1. STATUS FEED: Polls SQLite every 5s for new applications/queue changes.
     Shows Telegram-style notifications in the chat.
  2. USER QUESTIONS: Sends /btw <message> to the Terminal PTY session.
     /btw is instant, doesn't interrupt Claude's work, doesn't add to history.

No ANSI parsing. No raw terminal output. Clean, human-friendly chat.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from fastapi import WebSocket, WebSocketDisconnect

from . import local_data

logger = logging.getLogger(__name__)


async def chat_websocket(ws: WebSocket):
    """
    Chat WebSocket handler.

    Sends two types of messages:
    - {"type": "activity", "entries": [...]} — status feed from SQLite
    - {"type": "btw_response", "data": "..."} — response to /btw question
    - {"type": "system", "data": "..."} — system messages
    """
    await ws.accept()

    from .pty_terminal import session_manager

    # Track what we've already sent
    last_check_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
    last_queue_count = local_data.get_queue_count()

    # Send initial status
    await ws.send_json({
        "type": "system",
        "data": "Connected to ApplyLoop. You'll see live status updates here.",
    })

    # Send recent activity (last 20)
    recent = local_data.get_recent_activity(limit=20)
    if recent:
        await ws.send_json({"type": "activity", "entries": recent})

    # ANSI stripper for /btw responses
    _ansi_re = re.compile(
        r'\x1b\[[0-9;?]*[a-zA-Z]'
        r'|\x1b\][^\x07]*\x07'
        r'|\x1b\([A-Z]'
        r'|\x1b[=><=<>]'
        r'|\x1b'
    )

    async def _status_feed():
        """Poll SQLite every 5s and send new activity to chat."""
        nonlocal last_check_time, last_queue_count
        try:
            while True:
                await asyncio.sleep(5)

                # Check for new applications
                new_entries = local_data.get_recent_activity(since=last_check_time, limit=10)
                if new_entries:
                    last_check_time = new_entries[0].get("applied_at", last_check_time)
                    await ws.send_json({"type": "activity", "entries": new_entries})

                # Check queue count changes
                current_queue = local_data.get_queue_count()
                if current_queue != last_queue_count:
                    diff = current_queue - last_queue_count
                    if diff > 0:
                        await ws.send_json({
                            "type": "queue_update",
                            "data": f"+{diff} jobs added to queue ({current_queue} total)",
                            "count": current_queue,
                        })
                    elif diff < 0:
                        await ws.send_json({
                            "type": "queue_update",
                            "data": f"{abs(diff)} jobs processed ({current_queue} remaining)",
                            "count": current_queue,
                        })
                    last_queue_count = current_queue

                # Check PTY session status
                if session_manager.pty.is_alive:
                    idle = time.time() - session_manager.pty.last_output_at if session_manager.pty.last_output_at else 0
                    if idle > 900:  # 15 min
                        await ws.send_json({
                            "type": "session_idle",
                            "data": f"Session idle for {int(idle/60)}m",
                            "idle_minutes": int(idle / 60),
                        })

        except Exception as e:
            logger.debug(f"Status feed ended: {e}")

    feed_task = asyncio.create_task(_status_feed())

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action", "message")

            if action == "message":
                user_input = msg.get("message", "").strip()
                if not user_input:
                    continue

                # Check if PTY session is alive
                if not session_manager.pty.is_alive:
                    await ws.send_json({
                        "type": "btw_response",
                        "data": "No active session. Start one from the Terminal tab or session dropdown.",
                    })
                    continue

                # Send /btw command to the PTY
                btw_cmd = f"/btw {user_input}\n"
                session_manager.pty.write(btw_cmd.encode("utf-8"))

                # Wait briefly for response, then capture PTY output
                await ws.send_json({"type": "thinking", "data": "Asking Claude..."})

                # Subscribe to PTY output temporarily to capture /btw response
                queue = session_manager.pty.subscribe()
                response_chunks = []
                try:
                    # Collect output for up to 30 seconds
                    deadline = time.time() + 30
                    blank_count = 0
                    while time.time() < deadline:
                        try:
                            data = await asyncio.wait_for(queue.get(), timeout=2.0)
                            text = data.decode("utf-8", errors="replace")
                            clean = _ansi_re.sub("", text)
                            clean = re.sub(r'[\r\x00-\x08\x0e-\x1f]', '', clean)
                            stripped = clean.strip()
                            if stripped:
                                response_chunks.append(stripped)
                                blank_count = 0
                            else:
                                blank_count += 1
                                # Two consecutive blanks after some content = response done
                                if response_chunks and blank_count >= 2:
                                    break
                        except asyncio.TimeoutError:
                            if response_chunks:
                                break  # Got response, timeout means done
                finally:
                    session_manager.pty.unsubscribe(queue)

                # Clean up the response
                full_response = "\n".join(response_chunks)
                # Remove /btw echo and noise
                lines = full_response.split("\n")
                clean_lines = []
                for line in lines:
                    if line.startswith("/btw"):
                        continue
                    if "bypass permissions" in line.lower():
                        continue
                    if "ctrl+" in line.lower() or "shift+tab" in line.lower():
                        continue
                    if "esc to" in line.lower():
                        continue
                    if len(line.strip()) < 2:
                        continue
                    clean_lines.append(line)

                response = "\n".join(clean_lines).strip()
                if not response:
                    response = "Claude is busy. Your message was sent — check back shortly."

                await ws.send_json({"type": "btw_response", "data": response})

            elif action == "status":
                # Return current stats
                stats = local_data.get_stats()
                await ws.send_json({"type": "stats", "data": stats})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Chat WS closed: {e}")
    finally:
        feed_task.cancel()
