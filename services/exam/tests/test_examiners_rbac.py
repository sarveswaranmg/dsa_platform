from httpx import AsyncClient

from tests.conftest import AuthHelper


async def test_me_returns_own_examiner(auth: AuthHelper, client: AsyncClient) -> None:
    registration, tokens = await auth.register_and_login("me@example.com")
    response = await client.get("/examiners/me", headers=auth.bearer(tokens))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == registration["examiner_id"]
    assert body["email"] == "me@example.com"
    assert "password_hash" not in body
    assert "totp_secret" not in body


async def test_admin_creates_examiner_in_own_org(auth: AuthHelper, client: AsyncClient) -> None:
    registration, tokens = await auth.register_and_login("boss@example.com")
    response = await client.post(
        "/examiners",
        headers=auth.bearer(tokens),
        json={"email": "author@example.com", "password": auth.PASSWORD, "role": "author"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["org_id"] == registration["org_id"]
    assert body["role"] == "author"
    assert body["totp_secret"]  # admin hands this to the new examiner for enrollment


async def test_admin_lists_only_own_org(auth: AuthHelper, client: AsyncClient) -> None:
    _, tokens_a = await auth.register_and_login("admin-a@example.com", org_name="Org A")
    await auth.register_and_login("admin-b@example.com", org_name="Org B")

    response = await client.get("/examiners", headers=auth.bearer(tokens_a))
    assert response.status_code == 200
    emails = {e["email"] for e in response.json()}
    assert emails == {"admin-a@example.com"}


async def test_non_admin_role_denied(auth: AuthHelper, client: AsyncClient) -> None:
    _, admin_tokens = await auth.register_and_login("root@example.com")
    created = await client.post(
        "/examiners",
        headers=auth.bearer(admin_tokens),
        json={"email": "reviewer@example.com", "password": auth.PASSWORD, "role": "reviewer"},
    )
    assert created.status_code == 201
    secret = created.json()["totp_secret"]
    await auth.enroll("reviewer@example.com", secret)
    reviewer_tokens = await auth.login("reviewer@example.com", secret)

    # Reviewer can read their own identity...
    me = await client.get("/examiners/me", headers=auth.bearer(reviewer_tokens))
    assert me.status_code == 200
    # ...but admin-only endpoints are denied.
    denied_list = await client.get("/examiners", headers=auth.bearer(reviewer_tokens))
    assert denied_list.status_code == 403
    denied_create = await client.post(
        "/examiners",
        headers=auth.bearer(reviewer_tokens),
        json={"email": "sneaky@example.com", "password": auth.PASSWORD, "role": "admin"},
    )
    assert denied_create.status_code == 403


async def test_duplicate_examiner_email_conflict(auth: AuthHelper, client: AsyncClient) -> None:
    _, tokens = await auth.register_and_login("owner@example.com")
    response = await client.post(
        "/examiners",
        headers=auth.bearer(tokens),
        json={"email": "owner@example.com", "password": auth.PASSWORD, "role": "author"},
    )
    assert response.status_code == 409
