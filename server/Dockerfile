FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# pyodbc needs unixODBC plus Microsoft ODBC Driver 18 for SQL Server. Installing the
# driver means accepting Microsoft's EULA (ACCEPT_EULA=Y below). The pinned bookworm
# base matches the apt repository path; curl and gnupg are removed again afterwards.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y --auto-remove curl gnupg \
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
