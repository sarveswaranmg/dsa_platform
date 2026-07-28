"""Proctor live-view WebSocket channel (Phase 2 Slice 6). Observer-only: a
proctor joins a session and receives every event as it's emitted (code
snapshots, submissions, verdicts, follow-ups) — it never accepts inbound
frames as anything but noise, so a proctor can never mutate session state
over this connection.

Same query-param token convention as the candidate channel (native browser
WebSocket can't set custom headers), but decodes an examiner access token
and requires the PROCTOR role.
"""

import asyncio
import contextlib
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TokenInvalid
from app.core.redis import get_redis
from app.core.redis_keys import session_events_channel
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.examiner import Role
from app.repositories import sessions as sessions_repo

logger = logging.getLogger("exam.ws.proctor")

router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]


@router.websocket("/sessions/{session_id}/proctor-ws")
async def proctor_session_ws(
    websocket: WebSocket, session_id: uuid.UUID, session: DB, redis: RedisDep
) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=1008)
        return
    try:
        payload = decode_access_token(token)
        org_id = uuid.UUID(payload["org_id"])
        role = Role(payload["role"])
    except (TokenInvalid, ValueError, KeyError):
        await websocket.close(code=1008)
        return
    if role != Role.PROCTOR:
        await websocket.close(code=1008)
        return

    exam_session = await sessions_repo.get_by_id(session, org_id=org_id, session_id=session_id)
    if exam_session is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    channel = session_events_channel(session_id)
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
            await websocket.receive_text()  # observer-only: inbound frames are ignored
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await forward_task
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
