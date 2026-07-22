from httpx import AsyncClient

from tests.conftest import FakeForwarder, candidate_headers, examiner_headers


async def test_public_routes_need_no_token(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    assert (await client.post("/auth/login", json={})).status_code == 200
    assert (
        await client.post("/candidate/auth/exchange", json={})
    ).status_code == 200
    assert len(forwarder.calls) == 2


async def test_examiner_route_rejects_missing_token(client: AsyncClient) -> None:
    assert (await client.get("/blueprints")).status_code == 401


async def test_candidate_token_cannot_reach_examiner_route(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.get("/blueprints", headers=candidate_headers())
    assert response.status_code == 401
    assert forwarder.calls == []  # never forwarded


async def test_examiner_token_cannot_reach_candidate_route(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.get("/candidate/session", headers=examiner_headers())
    assert response.status_code == 401
    assert forwarder.calls == []


async def test_candidate_route_accepts_candidate_token(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.get("/candidate/session", headers=candidate_headers())
    assert response.status_code == 200
    assert forwarder.calls[-1]["path"] == "/candidate/session"


async def test_garbage_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/blueprints", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_non_bearer_scheme_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/blueprints", headers={"Authorization": "Basic abc"}
    )
    assert response.status_code == 401
