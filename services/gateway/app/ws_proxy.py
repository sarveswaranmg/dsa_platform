"""WebSocket proxying at the edge (Phase 2 Slice 6). Real duplex relaying —
not the plain HTTP request/response `HttpForwarder` (`httpx` cannot proxy
WebSockets) — so candidate/proctor WS connections still go through the
gateway's auth/rate-limit layer, keeping "the gateway is the only
published entry point" invariant every prior slice has held.

The handshake is validated with the same `authorise(...)` primitives the
HTTP path uses (they take plain values, not a `Request`, so they're
reusable here unchanged) before the connection is accepted; a rejected
handshake is closed with a policy-violation code and never reaches the
upstream. Once accepted, two tasks pump frames in each direction until
either side closes.
"""

import asyncio
import contextlib
import logging

import websockets
from fastapi import FastAPI
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.auth import AuthFailed, authorise
from app.config import get_settings
from app.routing import Policy, Upstream, match_route

logger = logging.getLogger("gateway.ws")


def _upstream_base_url(upstream: Upstream) -> str:
    settings = get_settings()
    return {
        Upstream.EXAM: settings.exam_service_url,
        Upstream.QUESTION: settings.question_service_url,
        Upstream.AI: settings.ai_service_url,
    }[upstream]


def _upstream_ws_url(upstream: Upstream, path: str, query: str) -> str:
    base = _upstream_base_url(upstream)
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_base}{path}"
    if query:
        url = f"{url}?{query}"
    return url


async def _pump_client_to_upstream(
    client_ws: WebSocket, upstream_ws: "websockets.ClientConnection"
) -> None:
    try:
        while True:
            data = await client_ws.receive_text()
            await upstream_ws.send(data)
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass


async def _pump_upstream_to_client(
    upstream_ws: "websockets.ClientConnection", client_ws: WebSocket
) -> None:
    try:
        async for message in upstream_ws:
            await client_ws.send_text(message if isinstance(message, str) else message.decode())
    except websockets.exceptions.ConnectionClosed:
        pass


def register_ws_routes(app: FastAPI) -> None:
    @app.websocket("/{full_path:path}")
    async def gateway_ws(websocket: WebSocket, full_path: str) -> None:
        path = "/" + full_path
        route = match_route(path)
        if route is None or route.policy is Policy.BLOCKED or route.upstream is None:
            await websocket.close(code=1008)
            return

        token = websocket.query_params.get("token")
        client_ip = websocket.client.host if websocket.client else "unknown"
        try:
            authorise(route.policy, f"Bearer {token}" if token else None, client_ip)
        except AuthFailed as exc:
            logger.info("ws auth rejected %s: %s", path, exc.detail)
            await websocket.close(code=1008)
            return

        upstream_url = _upstream_ws_url(route.upstream, path, websocket.url.query)

        await websocket.accept()
        try:
            async with websockets.connect(upstream_url) as upstream_ws:
                client_task = asyncio.create_task(
                    _pump_client_to_upstream(websocket, upstream_ws)
                )
                upstream_task = asyncio.create_task(
                    _pump_upstream_to_client(upstream_ws, websocket)
                )
                done, pending = await asyncio.wait(
                    {client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        except OSError:
            logger.exception("could not reach upstream %s for %s", route.upstream, path)
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()
