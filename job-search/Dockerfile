FROM python:3.13-slim@sha256:48d884813cf44e927cf64c5529dd630dd3b18338c6dc727991eef9b71e934a20

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client passwd && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10001 app && \
    useradd -u 10001 -g 10001 -m -d /home/app -s /bin/sh app

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    CREWAI_DISABLE_TELEMETRY=true \
    CREWAI_TRACING_ENABLED=false \
    ANONYMIZED_TELEMETRY=False \
    HOME=/home/app

USER 10001:10001

ENTRYPOINT ["python", "-m", "job_search.server"]