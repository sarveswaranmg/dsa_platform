from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import auth, blueprints, candidate, examiners, exams, health
from app.core.exceptions import DomainError
from app.core.redis import close_redis
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()
    await close_redis()


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def create_app() -> FastAPI:
    app = FastAPI(title="exam-service", lifespan=lifespan)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(examiners.router)
    app.include_router(blueprints.router)
    app.include_router(exams.router)
    app.include_router(candidate.router)
    return app


app = create_app()
