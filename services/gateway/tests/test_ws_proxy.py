import asyncio
import threading
import uuid
from collections.abc import Iterator

import pytest
import websockets
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from tests.conftest import candidate_headers, examiner_headers


def _token_from_header(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def test_missing_token_rejected(app: FastAPI) -> None:
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/exams/foo/ws"),
    ):
        pass


def test_wrong_plane_token_rejected(app: FastAPI) -> None:
    # /exams is EXAMINER-plane; a candidate token must never reach it.
    token = _token_from_header(candidate_headers())
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect(f"/exams/foo/ws?token={token}"),
    ):
        pass


def test_blocked_path_rejected(app: FastAPI) -> None:
    token = _token_from_header(examiner_headers())
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect(f"/internal/whatever?token={token}"),
    ):
        pass


def test_unmatched_path_rejected(app: FastAPI) -> None:
    token = _token_from_header(examiner_headers())
    with (
        TestClient(app) as test_client,
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect(f"/nowhere/ws?token={token}"),
    ):
        pass


@pytest.fixture
def fake_upstream_ws() -> Iterator[str]:
    """A minimal echo server standing in for exam's WebSocket hub — proves
    the gateway relays real frames both ways, without needing exam running.

    Runs in its own OS thread with its own event loop: Starlette's
    `TestClient` drives the gateway app from a background thread too (a
    sync call from the test blocks the main thread while it does), so an
    upstream server living on the main thread's loop would never get to
    accept the connection while that call is in flight.
    """

    async def echo(connection: "websockets.ServerConnection") -> None:
        async for message in connection:
            assert isinstance(message, str)
            await connection.send(f"echo:{message}")

    ready = threading.Event()
    stop_event = threading.Event()
    port_holder: dict[str, int] = {}

    def run_server() -> None:
        async def main() -> None:
            async with websockets.serve(echo, "127.0.0.1", 0) as server:
                port_holder["port"] = server.sockets[0].getsockname()[1]
                ready.set()
                while not stop_event.is_set():
                    await asyncio.sleep(0.05)

        asyncio.run(main())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    assert ready.wait(timeout=5), "fake upstream server never started"
    try:
        yield f"http://127.0.0.1:{port_holder['port']}"
    finally:
        stop_event.set()
        thread.join(timeout=5)


def test_relays_frames_both_ways(
    app: FastAPI, fake_upstream_ws: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "exam_service_url", fake_upstream_ws)
    token = _token_from_header(examiner_headers())

    with (
        TestClient(app) as test_client,
        test_client.websocket_connect(f"/sessions/{uuid.uuid4()}/ws?token={token}") as ws,
    ):
        ws.send_text("hello")
        reply = ws.receive_text()
        assert reply == "echo:hello"
