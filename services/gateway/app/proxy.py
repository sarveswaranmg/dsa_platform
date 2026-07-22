"""Forwards an accepted request to its upstream service."""

from typing import Protocol

import httpx

from app.config import get_settings
from app.routing import Upstream

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class Forwarder(Protocol):
    async def forward(
        self,
        *,
        upstream: Upstream,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body: bytes,
    ) -> httpx.Response: ...


class HttpForwarder:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    def _base_url(self, upstream: Upstream) -> str:
        settings = get_settings()
        return {
            Upstream.EXAM: settings.exam_service_url,
            Upstream.QUESTION: settings.question_service_url,
        }[upstream]

    async def forward(
        self,
        *,
        upstream: Upstream,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body: bytes,
    ) -> httpx.Response:
        url = f"{self._base_url(upstream)}{path}"
        if query:
            url = f"{url}?{query}"
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.lower() not in _HOP_BY_HOP
        }
        return await self._client.request(
            method, url, headers=forwarded, content=body
        )
