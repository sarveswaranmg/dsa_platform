import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Must run before any `app.*` import touches Settings: dev/test RS256 public
# key, committed at infra/dev-keys/ (see infra/dev-keys/README.md).
_DEV_KEYS = Path(__file__).resolve().parents[3] / "infra" / "dev-keys"
os.environ.setdefault("RS256_PUBLIC_KEY", (_DEV_KEYS / "rs256-public.pem").read_text())

import jwt
import pytest
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core import s3
from app.core.config import get_settings
from app.db.session import get_db
from app.main import create_app

SERVICE_ROOT = Path(__file__).resolve().parents[1]

# Test-only: signs fixture tokens with the dev private key so question's
# verify-only code can be exercised end to end. Production question code
# (app/) never imports a private key — only this test fixture does.
_test_private_key = load_pem_private_key(
    (_DEV_KEYS / "rs256-private.pem").read_bytes(), password=None
)
assert isinstance(_test_private_key, RSAPrivateKey)
_TEST_PRIVATE_KEY: RSAPrivateKey = _test_private_key


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
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
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
def author(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, "author")


@pytest.fixture
def reviewer(org_id: uuid.UUID) -> dict[str, str]:
    return auth_headers(org_id, "reviewer")


@pytest.fixture
def other_org_author() -> dict[str, str]:
    return auth_headers(uuid.uuid4(), "author")


QUESTION_DEFAULTS: dict[str, Any] = {
    "title": "Two Sum",
    "statement_md": "Given an array...",
    "constraints_md": "1 <= n <= 10^5",
    "difficulty": 2,
    "time_limit_ms": 2000,
    "memory_limit_mb": 256,
    "starter_code": {"python": "def solve():\n    pass\n"},
}


async def create_question_api(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/questions", headers=headers, json={**QUESTION_DEFAULTS, **overrides}
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data
