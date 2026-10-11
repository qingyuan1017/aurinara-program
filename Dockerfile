FROM python:3.13.5-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN groupadd --system aurinara && useradd --system --gid aurinara --create-home aurinara \
    && pip install --no-cache-dir uv==0.11.29

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts
COPY workers ./workers
COPY support ./support
COPY migrations ./migrations
COPY schemas ./schemas
COPY terminology ./terminology
COPY templates ./templates
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"
USER aurinara

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
