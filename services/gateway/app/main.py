import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.auth import AuthFailed, authorise
from app.config import get_settings
from app.deps import get_forwarder, get_rate_limiter, shutdown
from app.logging import RequestIdMiddleware, configure_logging, current_request_id
from app.proxy import Forwarder
from app.rate_limit import RateLimiter
from app.routing import Policy, match_route

logger = logging.getLogger("gateway.access")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().service_name)
    yield
    await shutdown()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="gateway", lifespan=lifespan)

    # Outermost middleware binds the request id before anything else logs.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
    )
    async def gateway(
        full_path: str,
        request: Request,
        forwarder: Annotated[Forwarder, Depends(get_forwarder)],
        rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> Response:
        path = "/" + full_path
        route = match_route(path)

        # Allow-list: unmatched paths and /internal are refused at the edge.
        if route is None or route.policy is Policy.BLOCKED or route.upstream is None:
            logger.info("blocked %s %s", request.method, path)
            return Response(status_code=404)

        try:
            identity = authorise(
                route.policy,
                request.headers.get("authorization"),
                _client_ip(request),
            )
        except AuthFailed as exc:
            logger.info("auth rejected %s %s: %s", request.method, path, exc.detail)
            return Response(
                content=f'{{"detail":"{exc.detail}"}}',
                status_code=401,
                media_type="application/json",
            )

        limit = settings.rate_limit_auth if route.strict_rate_limit else settings.rate_limit_default
        retry_after = await rate_limiter.check(identity, limit)
        if retry_after is not None:
            logger.info("rate limited %s (%s)", identity, path)
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        body = await request.body()
        headers = dict(request.headers)
        request_id = current_request_id()
        if request_id:
            headers["x-request-id"] = request_id  # propagate to the upstream

        upstream_response = await forwarder.forward(
            upstream=route.upstream,
            method=request.method,
            path=path,
            query=request.url.query,
            headers=headers,
            body=body,
        )
        logger.info(
            "proxied %s %s -> %s %d",
            request.method,
            path,
            route.upstream,
            upstream_response.status_code,
        )
        passthrough = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "content-encoding"}
        }
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=passthrough,
        )

    return app


app = create_app()
