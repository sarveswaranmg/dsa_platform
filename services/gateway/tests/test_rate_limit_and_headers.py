from httpx import AsyncClient

from app.config import get_settings
from tests.conftest import CountingRateLimiter, FakeForwarder, examiner_headers


async def test_exceeding_the_window_returns_429(
    client: AsyncClient, rate_limiter: CountingRateLimiter
) -> None:
    limit = get_settings().rate_limit_default
    sub = "examiner-1"
    for _ in range(limit):
        assert (
            await client.get("/blueprints", headers=examiner_headers(sub))
        ).status_code == 200
    blocked = await client.get("/blueprints", headers=examiner_headers(sub))
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


async def test_auth_endpoints_have_a_tighter_budget(
    client: AsyncClient,
) -> None:
    # The strict auth limit is far below the default, so login floods trip fast.
    limit = get_settings().rate_limit_auth
    for _ in range(limit):
        assert (await client.post("/auth/login", json={})).status_code == 200
    assert (await client.post("/auth/login", json={})).status_code == 429


async def test_identities_have_separate_budgets(client: AsyncClient) -> None:
    limit = get_settings().rate_limit_default
    for _ in range(limit):
        await client.get("/blueprints", headers=examiner_headers("busy"))
    # A different examiner is unaffected by the first one's spending.
    assert (
        await client.get("/blueprints", headers=examiner_headers("fresh"))
    ).status_code == 200


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers.get("x-request-id")


async def test_inbound_request_id_is_preserved_and_forwarded(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.get(
        "/blueprints",
        headers={**examiner_headers(), "X-Request-ID": "trace-123"},
    )
    assert response.headers["x-request-id"] == "trace-123"
    # And it's handed to the upstream so its logs share the id.
    assert forwarder.calls[-1]["headers"]["x-request-id"] == "trace-123"


async def test_cors_preflight_is_answered(client: AsyncClient) -> None:
    response = await client.options(
        "/blueprints",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"] == "http://localhost:5173"
    )
