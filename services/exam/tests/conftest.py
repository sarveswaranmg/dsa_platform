import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pyotp
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.clients.question_service import (
    PublishedQuestionRef,
    QuestionRef,
    TestCaseKeys,
    VersionContent,
    get_question_client,
)
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.examiner import Role
from app.notifications.email import EmailMessage, get_email_sender
from app.oidc.google import VerifiedIdentity, get_oidc_verifier

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
    """Stand-in for the question service so exam tests stay hermetic. Serves
    the examiner-plane sampling pool (token-forwarding) and the candidate-plane
    internal endpoints (published questions, version content, test-case keys)."""

    def __init__(self) -> None:
        self.pools: dict[uuid.UUID, list[QuestionRef]] = {}
        self.internal_pools: dict[uuid.UUID, list[PublishedQuestionRef]] = {}
        self.versions: dict[uuid.UUID, VersionContent] = {}
        self.test_case_keys: dict[uuid.UUID, list[TestCaseKeys]] = {}
        self.seen_authorizations: list[str] = []

    def set_pool(self, topic_id: uuid.UUID, refs: list[QuestionRef]) -> None:
        self.pools[topic_id] = refs

    def set_internal_pool(
        self, topic_id: uuid.UUID, refs: list[PublishedQuestionRef]
    ) -> None:
        self.internal_pools[topic_id] = refs

    def set_version(self, content: VersionContent) -> None:
        self.versions[content.version_id] = content
        # One sample case + one hidden case, so run (samples only) and submit
        # (everything) are distinguishable.
        self.test_case_keys.setdefault(
            content.version_id,
            [
                TestCaseKeys(
                    ordinal=1,
                    input_s3_key="in1",
                    expected_output_s3_key="out1",
                    is_sample=True,
                ),
                TestCaseKeys(
                    ordinal=2,
                    input_s3_key="in2",
                    expected_output_s3_key="out2",
                    is_sample=False,
                ),
            ],
        )

    async def list_published_questions(
        self, *, authorization: str, topic_id: uuid.UUID, difficulty: int
    ) -> list[QuestionRef]:
        self.seen_authorizations.append(authorization)
        return [r for r in self.pools.get(topic_id, []) if r.difficulty == difficulty]

    async def list_published_questions_internal(
        self, *, org_id: uuid.UUID, topic_id: uuid.UUID, difficulty: int
    ) -> list[PublishedQuestionRef]:
        return [
            r for r in self.internal_pools.get(topic_id, []) if r.difficulty == difficulty
        ]

    async def get_version_content(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionContent:
        from app.core.exceptions import NotFound

        content = self.versions.get(version_id)
        if content is None:
            raise NotFound("Question version not found")
        return content

    async def list_version_test_cases(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[TestCaseKeys]:
        return self.test_case_keys.get(version_id, [])


@pytest.fixture
def fake_question_client() -> FakeQuestionClient:
    return FakeQuestionClient()


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class FakeGoogleVerifier:
    """Injectable OIDC verifier: tests set the identity it returns or an error
    it raises, so every candidate-auth path is exercised without Google."""

    def __init__(self) -> None:
        self.identity = VerifiedIdentity(email="candidate@example.com", email_verified=True)
        self.error: Exception | None = None

    async def verify(self, id_token: str) -> VerifiedIdentity:
        if self.error is not None:
            raise self.error
        return self.identity


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def fake_oidc_verifier() -> FakeGoogleVerifier:
    return FakeGoogleVerifier()


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))


@pytest.fixture
def fake_publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    # Real Redis (up under `make test`) on a throwaway DB index, flushed
    # around each test so single-use state never leaks between tests.
    url = get_settings().redis_url.rsplit("/", 1)[0] + "/15"
    client = Redis.from_url(url, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_email_sender: FakeEmailSender,
    fake_oidc_verifier: FakeGoogleVerifier,
    redis_client: Redis,
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_question_client] = lambda: fake_question_client
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    app.dependency_overrides[get_oidc_verifier] = lambda: fake_oidc_verifier
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
