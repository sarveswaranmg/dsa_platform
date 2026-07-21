FROM python:3.12-slim

# The worker orchestrates sibling runner containers via the mounted Docker
# socket (DooD), so it needs the docker CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

WORKDIR /service
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

ENV PATH="/service/.venv/bin:$PATH"

CMD ["python", "-m", "app.worker"]
