FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Pinned, hash-checked dependencies (SEC-43).
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY ui ./ui
COPY tests/fixtures/providers ./tests/fixtures/providers
RUN pip install --no-cache-dir --no-deps -e .

# Run as a non-root user (SEC-47).
RUN useradd --system --uid 10001 keepair \
    && mkdir /spool && chown keepair /spool
USER keepair

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m keepair.demo.seed && uvicorn keepair.web.main:app --host 0.0.0.0 --port 8000"]
