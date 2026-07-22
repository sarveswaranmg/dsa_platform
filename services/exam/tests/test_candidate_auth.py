import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.core.exceptions import OIDCError
from app.core.security import create_invite_token, decode_invite_token
from app.oidc.google import VerifiedIdentity
from tests.conftest import FakeGoogleVerifier, one_topic_blueprint

CANDIDATE_EMAIL = "candidate@example.com"


async def _schedule(
    client: AsyncClient,
    author: dict[str, str],
    *,
    email: str = CANDIDATE_EMAIL,
    start_off: int = -1,
    end_off: int = 60,
) -> tuple[str, str]:
    blueprint_id = (
        await client.post(
            "/blueprints", headers=author, json=one_topic_blueprint(uuid.uuid4())
        )
    ).json()["id"]
    now = datetime.now(UTC)
    response = await client.post(
        "/exams",
        headers=author,
        json={
            "candidate_email": email,
            "blueprint_id": blueprint_id,
            "starts_at": (now + timedelta(minutes=start_off)).isoformat(),
            "ends_at": (now + timedelta(minutes=end_off)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    token = parse_qs(urlparse(body["invite_link"]).query)["token"][0]
    return body["id"], token


async def _exchange(client: AsyncClient, invite_token: str) -> Response:
    return await client.post(
        "/candidate/auth/exchange",
        json={"invite_token": invite_token, "google_id_token": "stub-google-id-token"},
    )


async def test_exchange_happy_issues_exam_token(
    client: AsyncClient, author: dict[str, str]
) -> None:
    exam_id, token = await _schedule(client, author)
    response = await _exchange(client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["exam_id"] == exam_id
    assert body["candidate_email"] == CANDIDATE_EMAIL
    assert body["exam_token"]

    # The exam-scoped token drives the candidate route.
    me = await client.get(
        "/candidate/exam", headers={"Authorization": f"Bearer {body['exam_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["exam_id"] == exam_id

    # Invite is now consumed.
    exam = await client.get(f"/exams/{exam_id}", headers=author)
    assert exam.json()["invite"]["status"] == "consumed"


async def test_exchange_consumes_the_prefixed_redis_key(
    client: AsyncClient, author: dict[str, str], redis_client: Redis
) -> None:
    _, token = await _schedule(client, author)
    jti = str(decode_invite_token(token)["jti"])
    assert await redis_client.exists(f"ex:invite:{jti}")

    assert (await _exchange(client, token)).status_code == 200
    assert not await redis_client.exists(f"ex:invite:{jti}")


async def test_exchange_tampered_token_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    _, token = await _schedule(client, author)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    response = await _exchange(client, tampered)
    assert response.status_code == 401


async def test_exchange_expired_window_rejected(client: AsyncClient) -> None:
    # Craft a syntactically valid invite token whose window already closed.
    past = datetime.now(UTC) - timedelta(hours=1)
    token = create_invite_token(
        jti=uuid.uuid4().hex,
        invite_id=uuid.uuid4(),
        exam_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        candidate_email=CANDIDATE_EMAIL,
        not_before=past - timedelta(hours=1),
        expires_at=past,
    )
    response = await _exchange(client, token)
    assert response.status_code == 401


async def test_exchange_email_mismatch_does_not_consume(
    client: AsyncClient, author: dict[str, str], fake_oidc_verifier: FakeGoogleVerifier
) -> None:
    _, token = await _schedule(client, author)
    # Google authenticates a different person.
    fake_oidc_verifier.identity = VerifiedIdentity(
        email="someone-else@example.com", email_verified=True
    )
    mismatch = await _exchange(client, token)
    assert mismatch.status_code == 403

    # The real candidate can still use the invite (it was not consumed).
    fake_oidc_verifier.identity = VerifiedIdentity(
        email=CANDIDATE_EMAIL, email_verified=True
    )
    ok = await _exchange(client, token)
    assert ok.status_code == 200


async def test_exchange_unverified_email_rejected(
    client: AsyncClient, author: dict[str, str], fake_oidc_verifier: FakeGoogleVerifier
) -> None:
    _, token = await _schedule(client, author)
    fake_oidc_verifier.identity = VerifiedIdentity(
        email=CANDIDATE_EMAIL, email_verified=False
    )
    response = await _exchange(client, token)
    assert response.status_code == 403


async def test_exchange_reused_token_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    _, token = await _schedule(client, author)
    assert (await _exchange(client, token)).status_code == 200
    assert (await _exchange(client, token)).status_code == 401  # single-use


async def test_exchange_bad_google_token_rejected(
    client: AsyncClient, author: dict[str, str], fake_oidc_verifier: FakeGoogleVerifier
) -> None:
    _, token = await _schedule(client, author)
    fake_oidc_verifier.error = OIDCError()
    response = await _exchange(client, token)
    assert response.status_code == 401


async def test_candidate_token_rejected_on_examiner_route(
    client: AsyncClient, author: dict[str, str]
) -> None:
    _, token = await _schedule(client, author)
    exam_token = (await _exchange(client, token)).json()["exam_token"]
    response = await client.get(
        "/examiners/me", headers={"Authorization": f"Bearer {exam_token}"}
    )
    assert response.status_code == 401


async def test_examiner_token_rejected_on_candidate_route(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.get("/candidate/exam", headers=author)
    assert response.status_code == 401


async def test_missing_token_on_candidate_route(client: AsyncClient) -> None:
    assert (await client.get("/candidate/exam")).status_code == 401
