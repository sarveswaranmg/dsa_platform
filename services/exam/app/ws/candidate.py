"""Candidate WebSocket channel (Phase 2 Slice 6). Native browser WebSocket
can't set custom headers on the handshake, so the candidate's exam token
travels as a query param instead of an Authorization header — decoded with
the same `decode_candidate_exam_token` the HTTP routes use, just called
directly instead of through the `HTTPBearer`/`Depends` extraction.

Pushes `verdict`/`followup_pushed` events live (via Redis pub/sub — see
app/services/session_events.py); accepts inbound `code_snapshot` frames
from the candidate's editor (sent every ~30s) and records them the same
way.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TokenInvalid
from app.core.redis import get_redis
from app.core.redis_keys import session_events_channel
from app.core.security import decode_candidate_exam_token
from app.db.session import get_db
from app.repositories import sessions as sessions_repo
from app.services import session_events

logger = logging.getLogger("exam.ws.candidate")

router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]


@router.websocket("/candidate/session/ws")
async def candidate_session_ws(websocket: WebSocket, session: DB, redis: RedisDep) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=1008)
        return
    try:
        payload = decode_candidate_exam_token(token)
        org_id = uuid.UUID(payload["org_id"])
        exam_id = uuid.UUID(payload["exam_id"])
    except (TokenInvalid, ValueError, KeyError):
        await websocket.close(code=1008)
        return

    exam_session = await sessions_repo.get_by_exam(session, org_id=org_id, exam_id=exam_id)
    if exam_session is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    channel = session_events_channel(exam_session.id)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    async def _forward_events() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await websocket.send_text(message["data"])

    forward_task = asyncio.create_task(_forward_events())
    try:
        while True:
            data = await websocket.receive_text()
            try:
                frame = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("dropping malformed candidate WS frame")
                continue
            if frame.get("type") == "code_snapshot":
                await session_events.emit(
                    session,
                    redis,
                    org_id=org_id,
                    session_id=exam_session.id,
                    type="code_snapshot",
                    payload={"ordinal": frame.get("ordinal"), "source": frame.get("source")},
                )
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await forward_task
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
