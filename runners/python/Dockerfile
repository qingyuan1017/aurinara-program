FROM python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.29 \
    && groupadd --system runner \
    && useradd --system --gid runner --uid 10001 runner
WORKDIR /runner
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chmod=0555 runners/run-program.sh /runner/run-program.sh
ENV PATH="/runner/.venv/bin:$PATH"
WORKDIR /workspace
USER 10001:10001

ENTRYPOINT ["/runner/run-program.sh", "python"]
