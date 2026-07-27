FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

# tesseract-ocr + poppler-utils back the pytesseract/pdf2image OCR fallback
# path (services/ai/app/pdf/extract.py) — only needed at runtime, not for
# make lint/make test, which mock that path.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY migrate.sh ./
RUN chmod +x migrate.sh

ENV PATH="/service/.venv/bin:$PATH"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
