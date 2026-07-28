import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Must run before any `app.*` import touches Settings: dev/test RS256 public
# key, committed at infra/dev-keys/ (see infra/dev-keys/README.md).
_DEV_KEYS = Path(__file__).resolve().parents[3] / "infra" / "dev-keys"
os.environ.setdefault("RS256_PUBLIC_KEY", (_DEV_KEYS / "rs256-public.pem").read_text())

# Unlike exam/question, ai's ingestion job (app/services/ingestion.py) opens
# its own DB session via the real app.db.session singleton — it's a
# fire-and-forget asyncio task, not something a request-scoped `get_db`
# override can reach. So tests can't use question's savepoint-rollback
# trick (a second connection can never see another connection's uncommitted
# work); instead this points the app's real engine at the `_test` database
# and cleans up with a truncate between tests.
_default_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://dsa:dsa@localhost:5433/ai")
_base, _, _name = _default_url.rpartition("/")
os.environ["DATABASE_URL"] = f"{_base}/{_name}_test"

import jwt
import pytest
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

from alembic import command
from app.clients.github import GitHubSignals, MockGitHubClient, get_github_client
from app.core import s3
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_engine
from app.llm.client import ExtractedProfile, MockLLMClient, get_llm_client
from app.main import create_app

SERVICE_ROOT = Path(__file__).resolve().parents[1]

# Test-only: signs fixture tokens with the dev private key so ai's
# verify-only code can be exercised end to end. Production ai code (app/)
# never imports a private key — only this test fixture does.
_test_private_key = load_pem_private_key(
    (_DEV_KEYS / "rs256-private.pem").read_bytes(), password=None
)
assert isinstance(_test_private_key, RSAPrivateKey)
_TEST_PRIVATE_KEY: RSAPrivateKey = _test_private_key


@pytest.fixture(scope="session")
def migrated_db() -> None:
    cfg = Config(SERVICE_ROOT / "alembic.ini")
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def _clean_db(migrated_db: None) -> AsyncIterator[None]:
    yield
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE candidate_profiles, generation_jobs, test_case_generation_jobs"
            )
        )


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
def app(redis_client: Redis) -> FastAPI:
    application = create_app()
    # Deterministic, no-network defaults; individual tests may override
    # get_llm_client/get_github_client further to exercise failure paths.
    application.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    application.dependency_overrides[get_github_client] = lambda: MockGitHubClient()
    application.dependency_overrides[get_redis] = lambda: redis_client
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture(scope="session")
def s3_bucket() -> None:
    """Ensure the bucket exists in localstack (make test starts it)."""
    s3.ensure_bucket()


def mint_token(org_id: uuid.UUID, role: str = "author", expires_in: int = 900) -> str:
    """Mint an examiner access token exactly as the exam service would."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "org_id": str(org_id),
        "role": role,
        "type": "examiner_access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, _TEST_PRIVATE_KEY, algorithm="RS256")


def auth_headers(org_id: uuid.UUID, role: str = "author") -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(org_id, role)}"}


@pytest.fixture
def org_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def admin(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, "admin")


@pytest.fixture
def author(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, "author")


@pytest.fixture
def reviewer(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, "reviewer")


@pytest.fixture
def other_org_author() -> dict[str, str]:
    return auth_headers(uuid.uuid4(), "author")


class RaisingGitHubClient:
    """Structurally matches GitHubClient — used to exercise the ingestion
    job's failure path without a real network call."""

    async def fetch_signals(self, handle: str) -> GitHubSignals:
        raise RuntimeError("github boom")


class RaisingLLMClient:
    """Structurally matches LLMClient — used to exercise the ingestion job's
    failure path without a real network call."""

    async def extract_profile(
        self, resume_text: str, github_signals: GitHubSignals | None
    ) -> ExtractedProfile:
        raise RuntimeError("llm boom")
