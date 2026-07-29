import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import (
    blueprints,
    difficulty,
    generation,
    health,
    internal_testcases,
    profiles,
    testcase_generation,
)
from app.core import s3
from app.core.config import get_settings, validate_production_config
from app.core.exceptions import DomainError
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.services.gen_consumer import run_gen_result_consumer
from app.services.session_evaluation_consumer import run_session_evaluation_consumer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("ai")
    validate_production_config(get_settings())
    if get_settings().env == "dev":
        s3.ensure_bucket()  # localstack/MinIO bootstrap; prod buckets exist
    stop = asyncio.Event()
    consumer_task: asyncio.Task[None] | None = None
    eval_consumer_task: asyncio.Task[None] | None = None
    if get_settings().enable_gen_result_consumer:
        consumer_task = asyncio.create_task(run_gen_result_consumer(stop))
    if get_settings().enable_session_evaluation_consumer:
        eval_consumer_task = asyncio.create_task(run_session_evaluation_consumer(stop))
    try:
        yield
    finally:
        stop.set()
        for task in (consumer_task, eval_consumer_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await dispose_engine()
        await close_redis()


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def create_app() -> FastAPI:
    app = FastAPI(title="ai-service", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.include_router(health.router)
    app.include_router(profiles.router)
    app.include_router(generation.router)
    app.include_router(testcase_generation.router)
    app.include_router(blueprints.router)
    app.include_router(difficulty.router)
    app.include_router(internal_testcases.router)
    return app


app = create_app()
