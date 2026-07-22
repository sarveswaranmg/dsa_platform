from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import health, internal, questions, test_cases, topics
from app.core import s3
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("question")
    if get_settings().env == "dev":
        s3.ensure_bucket()  # localstack/MinIO bootstrap; prod buckets exist
    yield
    await dispose_engine()


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def create_app() -> FastAPI:
    app = FastAPI(title="question-service", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(health.router)
    app.include_router(topics.router)
    app.include_router(questions.router)
    app.include_router(test_cases.router)
    app.include_router(internal.router)
    return app


app = create_app()
