"""WebSocket handshake tests for the proctor channel (Phase 2 Slice 6). See
test_ws_candidate.py for why these are scoped to the handshake only (no DB
access), with the full connected flow proven via real-stack e2e
verification instead."""

import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token
from app.models.examiner import Role


def _token(role: Role) -> str:
    return create_access_token(examiner_id=uuid.uuid4(), org_id=uuid.uuid4(), role=role)


def test_missing_token_rejected(app: FastAPI) -> None:
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect(f"/sessions/{uuid.uuid4()}/proctor-ws"),
    ):
        pass


def test_non_proctor_role_rejected(app: FastAPI) -> None:
    token = _token(Role.ADMIN)
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect(f"/sessions/{uuid.uuid4()}/proctor-ws?token={token}"),
    ):
        pass


# The unknown-session case (valid proctor token, no such session) needs a DB
# read past the role check, which hits the cross-event-loop asyncpg
# limitation described in test_ws_candidate.py's module docstring — covered
# by real-stack e2e verification instead.
