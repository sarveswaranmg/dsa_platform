"""WebSocket handshake tests for the candidate channel (Phase 2 Slice 6).

Scope note: Starlette's `TestClient` runs the ASGI app in its own
background thread with a separate event loop, so an asyncpg connection
created via this suite's savepoint-based `db_session` fixture (bound to
the main test loop) cannot safely be shared with it — mixing the two
raises "attached to a different loop" from asyncpg. httpx's `ASGITransport`
(used by the `client`/`AsyncClient` fixture everywhere else in this suite)
doesn't support the websocket ASGI scope at all, so it can't substitute
either. These tests therefore cover the token-handshake logic, which needs
no DB access (rejected before any query) — the full connected flow
(session lookup, code_snapshot recording, event forwarding) is proven via
the documented real-stack end-to-end verification instead.
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_missing_token_rejected(app: FastAPI) -> None:
    # No token query param — the server closes the handshake before
    # accepting, which the test client surfaces as a disconnect right at
    # connect time.
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/candidate/session/ws"),
    ):
        pass


def test_invalid_token_rejected(app: FastAPI) -> None:
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/candidate/session/ws?token=not-a-real-token"),
    ):
        pass
