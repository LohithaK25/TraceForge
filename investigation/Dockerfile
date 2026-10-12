FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

RUN groupadd --system --gid 10001 traceforge \
    && useradd --system --uid 10001 --gid traceforge --home-dir /app traceforge \
    && chown traceforge:traceforge /app
COPY pyproject.toml ./
COPY --chown=traceforge:traceforge traceforge_investigation ./traceforge_investigation
COPY --chown=traceforge:traceforge migrations ./migrations
USER traceforge
EXPOSE 8090
CMD ["uvicorn", "traceforge_investigation.main:app", "--host", "0.0.0.0", "--port", "8090"]

FROM base AS test
USER root
RUN pip install --no-cache-dir --requirement requirements-dev.txt
COPY --chown=traceforge:traceforge tests ./tests
USER traceforge
CMD ["pytest"]
