import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pyotp
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.clients.question_service import QuestionRef, get_question_client
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.examiner import Role

SERVICE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_db_url() -> str:
    base, _, name = get_settings().database_url.rpartition("/")
    return f"{base}/{name}_test"


@pytest.fixture(scope="session")
def migrated_db(test_db_url: str) -> None:
    cfg = Config(SERVICE_ROOT / "alembic.ini")
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def engine(test_db_url: str, migrated_db: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    # Each test runs inside one outer transaction that is rolled back at the
    # end, so tests are isolated without re-migrating the database.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def auth(client: AsyncClient) -> "AuthHelper":
    return AuthHelper(client)


class AuthHelper:
    """Drives register → TOTP enrollment → login through the real API."""

    PASSWORD = "correct-horse-battery-staple"

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def register(self, email: str, org_name: str = "Test Org") -> dict[str, str]:
        response = await self.client.post(
            "/auth/register",
            json={"org_name": org_name, "email": email, "password": self.PASSWORD},
        )
        assert response.status_code == 201, response.text
        data: dict[str, str] = response.json()
        return data

    async def enroll(self, email: str, totp_secret: str) -> None:
        response = await self.client.post(
            "/auth/totp/verify",
            json={
                "email": email,
                "password": self.PASSWORD,
                "code": pyotp.TOTP(totp_secret).now(),
            },
        )
        assert response.status_code == 204, response.text

    async def login(self, email: str, totp_secret: str) -> dict[str, str]:
        response = await self.client.post(
            "/auth/login",
            json={
                "email": email,
                "password": self.PASSWORD,
                "totp_code": pyotp.TOTP(totp_secret).now(),
            },
        )
        assert response.status_code == 200, response.text
        data: dict[str, str] = response.json()
        return data

    async def register_and_login(
        self, email: str, org_name: str = "Test Org"
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Full flow; returns (register_payload, token_payload)."""
        registration = await self.register(email, org_name)
        await self.enroll(email, registration["totp_secret"])
        tokens = await self.login(email, registration["totp_secret"])
        return registration, tokens

    def bearer(self, tokens: dict[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens['access_token']}"}


class FakeQuestionClient:
    """Stand-in for the question service so exam tests stay hermetic. Records
    the Authorization header it was handed (to prove token forwarding) and
    returns canned published-question pools per topic."""

    def __init__(self) -> None:
        self.pools: dict[uuid.UUID, list[QuestionRef]] = {}
        self.seen_authorizations: list[str] = []

    def set_pool(self, topic_id: uuid.UUID, refs: list[QuestionRef]) -> None:
        self.pools[topic_id] = refs

    async def list_published_questions(
        self, *, authorization: str, topic_id: uuid.UUID, difficulty: int
    ) -> list[QuestionRef]:
        self.seen_authorizations.append(authorization)
        return [r for r in self.pools.get(topic_id, []) if r.difficulty == difficulty]


@pytest.fixture
def fake_question_client() -> FakeQuestionClient:
    return FakeQuestionClient()


@pytest.fixture
async def client(
    db_session: AsyncSession, fake_question_client: FakeQuestionClient
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_question_client] = lambda: fake_question_client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def mint_token(org_id: uuid.UUID, role: Role = Role.AUTHOR) -> str:
    """Mint an examiner access token directly (no DB row needed — blueprint
    endpoints read org_id/role from claims only)."""
    return create_access_token(examiner_id=uuid.uuid4(), org_id=org_id, role=role)


def auth_headers(org_id: uuid.UUID, role: Role = Role.AUTHOR) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(org_id, role)}"}


@pytest.fixture
def org_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def author(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, Role.AUTHOR)


@pytest.fixture
def reviewer(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, Role.REVIEWER)


@pytest.fixture
def other_org_author() -> dict[str, str]:
    return auth_headers(uuid.uuid4(), Role.AUTHOR)


def one_topic_blueprint(
    topic_id: uuid.UUID,
    *,
    difficulty_min: int = 1,
    difficulty_max: int = 3,
    question_count: int = 2,
    name: str = "Backend Screen",
) -> dict[str, object]:
    return {
        "name": name,
        "target_role": "Backend Engineer",
        "experience_band": "senior",
        "total_duration_minutes": 90,
        "topic_mix": [
            {
                "topic_id": str(topic_id),
                "weight": 100,
                "difficulty_min": difficulty_min,
                "difficulty_max": difficulty_max,
                "question_count": question_count,
            }
        ],
    }
