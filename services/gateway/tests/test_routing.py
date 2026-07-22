import pytest
from httpx import AsyncClient

from app.routing import Policy, Upstream, match_route
from tests.conftest import FakeForwarder, examiner_headers


def test_longest_prefix_wins() -> None:
    # /candidate/auth is public; /candidate is candidate-only.
    public = match_route("/candidate/auth/exchange")
    candidate = match_route("/candidate/session")
    assert public is not None and public.policy is Policy.PUBLIC
    assert candidate is not None and candidate.policy is Policy.CANDIDATE


def test_unknown_path_is_unmatched() -> None:
    assert match_route("/nope") is None


async def test_examiner_routes_reach_the_right_upstream(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    cases = [
        ("/blueprints", Upstream.EXAM),
        ("/exams", Upstream.EXAM),
        ("/submissions/x", Upstream.EXAM),
        ("/examiners/me", Upstream.EXAM),
        ("/topics", Upstream.QUESTION),
        ("/questions", Upstream.QUESTION),
    ]
    for path, upstream in cases:
        response = await client.get(path, headers=examiner_headers())
        assert response.status_code == 200, path
        assert forwarder.calls[-1]["upstream"] is upstream


async def test_path_query_and_body_are_preserved(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.post(
        "/questions/abc/test-cases?draft=1",
        headers=examiner_headers(),
        content=b'{"is_sample": true}',
    )
    assert response.status_code == 200
    call = forwarder.calls[-1]
    assert call["path"] == "/questions/abc/test-cases"
    assert call["query"] == "draft=1"
    assert call["body"] == b'{"is_sample": true}'  # forwarded byte-for-byte
    assert call["method"] == "POST"


async def test_healthz_is_public_and_local(
    client: AsyncClient, forwarder: FakeForwarder
) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert forwarder.calls == []  # served by the gateway, not proxied


@pytest.mark.parametrize(
    "path",
    [
        "/internal/published-questions",
        "/internal/question-versions/x/test-cases",
        "/internal/anything",
    ],
)
async def test_internal_endpoints_are_blocked_at_the_edge(
    client: AsyncClient, forwarder: FakeForwarder, path: str
) -> None:
    # These are unauthenticated service-to-service endpoints; the gateway must
    # never expose them, even with a valid examiner token.
    response = await client.get(path, headers=examiner_headers())
    assert response.status_code == 404
    assert forwarder.calls == []
