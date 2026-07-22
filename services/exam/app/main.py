import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import (
    auth,
    blueprints,
    candidate,
    examiners,
    exams,
    health,
    results,
)
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.messaging.consumer import run_verdict_consumer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("exam")
    stop = asyncio.Event()
    consumer_task: asyncio.Task[None] | None = None
    if get_settings().enable_verdict_consumer:
        consumer_task = asyncio.create_task(run_verdict_consumer(stop))
    try:
        yield
    finally:
        stop.set()
        if consumer_task is not None:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
        await dispose_engine()
        await close_redis()


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def create_app() -> FastAPI:
    app = FastAPI(title="exam-service", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(examiners.router)
    app.include_router(blueprints.router)
    app.include_router(exams.router)
    app.include_router(results.router)
    app.include_router(candidate.router)
    return app


app = create_app()
