import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_refresh_token
from app.models.examiner import Role
from app.repositories import refresh_tokens as refresh_tokens_repo
from tests.conftest import AuthHelper


async def test_register_creates_org_admin_with_totp(auth: AuthHelper) -> None:
    data = await auth.register("admin@example.com")
    assert data["role"] == "admin"
    assert data["totp_secret"]
    assert data["totp_provisioning_uri"].startswith("otpauth://totp/")
    assert uuid.UUID(data["org_id"])
    assert uuid.UUID(data["examiner_id"])


async def test_register_duplicate_email_conflict(auth: AuthHelper, client: AsyncClient) -> None:
    await auth.register("dupe@example.com")
    response = await client.post(
        "/auth/register",
        json={"org_name": "Other", "email": "dupe@example.com", "password": auth.PASSWORD},
    )
    assert response.status_code == 409


async def test_totp_verify_wrong_code(auth: AuthHelper, client: AsyncClient) -> None:
    await auth.register("enroll@example.com")
    response = await client.post(
        "/auth/totp/verify",
        json={"email": "enroll@example.com", "password": auth.PASSWORD, "code": "000000"},
    )
    assert response.status_code == 401


async def test_login_before_totp_enrollment_rejected(
    auth: AuthHelper, client: AsyncClient
) -> None:
    data = await auth.register("unenrolled@example.com")
    response = await client.post(
        "/auth/login",
        json={
            "email": "unenrolled@example.com",
            "password": auth.PASSWORD,
            "totp_code": pyotp.TOTP(data["totp_secret"]).now(),
        },
    )
    assert response.status_code == 403


async def test_login_happy_path(auth: AuthHelper) -> None:
    _, tokens = await auth.register_and_login("happy@example.com")
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


async def test_login_wrong_password(auth: AuthHelper, client: AsyncClient) -> None:
    data = await auth.register("wrongpw@example.com")
    await auth.enroll("wrongpw@example.com", data["totp_secret"])
    response = await client.post(
        "/auth/login",
        json={
            "email": "wrongpw@example.com",
            "password": "definitely-not-the-password",
            "totp_code": pyotp.TOTP(data["totp_secret"]).now(),
        },
    )
    assert response.status_code == 401


async def test_login_bad_totp(auth: AuthHelper, client: AsyncClient) -> None:
    data = await auth.register("badtotp@example.com")
    await auth.enroll("badtotp@example.com", data["totp_secret"])
    response = await client.post(
        "/auth/login",
        json={"email": "badtotp@example.com", "password": auth.PASSWORD, "totp_code": "000000"},
    )
    assert response.status_code == 401


async def test_expired_access_token_rejected(auth: AuthHelper, client: AsyncClient) -> None:
    registration, _ = await auth.register_and_login("expired@example.com")
    expired = create_access_token(
        examiner_id=uuid.UUID(registration["examiner_id"]),
        org_id=uuid.UUID(registration["org_id"]),
        role=Role.ADMIN,
        expires_in=-10,
    )
    response = await client.get(
        "/examiners/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401


async def test_garbage_access_token_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/examiners/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/examiners/me")
    assert response.status_code == 401


async def test_refresh_rotation(auth: AuthHelper, client: AsyncClient) -> None:
    _, tokens = await auth.register_and_login("rotate@example.com")
    response = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # The new refresh token works.
    response = await client.post(
        "/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert response.status_code == 200


async def test_refresh_reuse_revokes_all_sessions(
    auth: AuthHelper, client: AsyncClient
) -> None:
    _, tokens = await auth.register_and_login("reuse@example.com")
    first = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    successor = first.json()

    # Replaying the already-rotated token must fail...
    reused = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401
    # ...and must also kill the successor (assume-compromise policy).
    after = await client.post("/auth/refresh", json={"refresh_token": successor["refresh_token"]})
    assert after.status_code == 401


async def test_expired_refresh_token_rejected(
    auth: AuthHelper, client: AsyncClient, db_session: AsyncSession
) -> None:
    registration, _ = await auth.register_and_login("stale@example.com")
    raw = "stale-refresh-token-value"
    await refresh_tokens_repo.create_refresh_token(
        db_session,
        examiner_id=uuid.UUID(registration["examiner_id"]),
        org_id=uuid.UUID(registration["org_id"]),
        token_hash=hash_refresh_token(raw),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    response = await client.post("/auth/refresh", json={"refresh_token": raw})
    assert response.status_code == 401


async def test_unknown_refresh_token_rejected(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh", json={"refresh_token": "never-issued"})
    assert response.status_code == 401


async def test_logout_revokes_refresh_token(auth: AuthHelper, client: AsyncClient) -> None:
    _, tokens = await auth.register_and_login("logout@example.com")
    response = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 204
    response = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401
