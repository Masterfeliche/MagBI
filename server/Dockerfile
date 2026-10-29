FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# unixODBC runtime is required by pyodbc. The Microsoft ODBC driver for SQL Server
# is added in Sprint 2 together with the SQL Server connector.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unixodbc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The package sources must be present before `pip install .` (hatchling builds them).
COPY pyproject.toml ./
COPY magbi/ magbi/
RUN pip install .

COPY alembic.ini ./
COPY migrations/ migrations/

RUN useradd --system --uid 10001 --home /app magbi \
    && mkdir -p /data/datasets \
    && chown -R magbi:magbi /data /app
USER magbi

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).status == 200 else 1)"

# Apply migrations, then serve. Only the api service runs migrations.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn magbi.main:app --host 0.0.0.0 --port 8000"]
