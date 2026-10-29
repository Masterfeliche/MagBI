# 11 — Deployment & Operations

> **Status: Planned**

---

## What It Does

The deployment layer packages MagBI into containers, wires them together, and
provides the tooling to run, monitor, and maintain the system in production.
A single `docker compose up` starts the entire stack locally. In production,
the same containers run behind a load balancer with monitoring and alerting.

### The five services

```
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌───────┐
│  web    │   │   api   │   │ worker  │   │ postgres │   │ redis │
│ (nginx) │──▶│(FastAPI) │──▶│(Celery) │   │(metadata)│   │(cache)│
│  :3000  │   │  :8000  │   │         │   │  :5432   │   │ :6379 │
└─────────┘   └────┬────┘   └────┬────┘   └──────────┘   └───────┘
                   │              │
                   └──────┬───────┘
                          │
                    ┌─────┴─────┐
                    │  DuckDB   │
                    │  (files)  │
                    └───────────┘
```

| Service | Image | Purpose |
|---------|-------|---------|
| **web** | nginx:alpine | Serves the React frontend; reverse-proxies `/api` to the FastAPI server |
| **api** | Custom Python | FastAPI application — REST API, query engine, WebSocket |
| **worker** | Same Python image | Celery worker — runs background refresh jobs |
| **postgres** | postgres:16-alpine | Metadata store — workspaces, datasets, reports, users |
| **redis** | redis:7-alpine | Query cache, Celery message broker, WebSocket pub/sub |

---

## Why This Approach

### Why Docker Compose for MVP

| Approach | Pros | Cons |
|----------|------|------|
| **Bare metal** | Maximum performance, no container overhead | Manual dependency management, no reproducibility, works-on-my-machine problems |
| **Docker Compose** | **Chosen.** Single-command deployment, reproducible environments, isolates services, easy local development | Not designed for multi-host production (no built-in service discovery, health-based routing, rolling deploys) |
| **Kubernetes** | Auto-scaling, rolling deploys, self-healing, service mesh | Massive operational complexity for a small team. Overkill until you have >5 replicas and a dedicated platform team |
| **Serverless** | Zero ops, pay-per-request | DuckDB files need persistent disk (no ephemeral functions). Long-running refresh jobs don't fit the serverless model |

Docker Compose is the right choice for the first 6-12 months:
- **Local development:** `docker compose up` starts everything, hot reload works
  for both server and web
- **Single-server production:** The same compose file runs on a VM, with volume
  mounts for persistence
- **Transition to Kubernetes:** Each service's Dockerfile works unchanged in a
  K8s pod. The compose file is a stepping stone, not a dead end.

### Why nginx as the frontend server

The React app builds to static HTML/JS/CSS files. These could be served by:
1. **FastAPI's static file handler** — works, but FastAPI is a Python async
   server optimised for API requests, not static file serving. Every static
   file request occupies an async slot.
2. **A CDN (CloudFront, Cloudflare)** — ideal for production, but requires
   additional infrastructure configuration.
3. **nginx** — purpose-built for serving static files. Handles thousands of
   concurrent connections with minimal memory. Also reverse-proxies API
   requests to FastAPI, providing a single entry point.

nginx gives us:
- Static file serving with gzip compression and caching headers
- Reverse proxy to the API (the browser talks to one origin, avoiding CORS)
- TLS termination in production
- Rate limiting and connection limiting as a defense layer

---

## How It Works

### Docker Compose Configuration

The `deploy/docker-compose.yml` defines all five services:

**API service:**
```yaml
api:
  build: ../server
  ports: ["8000:8000"]
  environment:
    MAGBI_DATABASE_URL: postgresql+asyncpg://magbi:magbi@postgres:5432/magbi
    MAGBI_REDIS_URL: redis://redis:6379/0
    MAGBI_DUCKDB_DATA_DIR: /data/datasets
  volumes:
    - duckdb-data:/data/datasets
  depends_on: [postgres, redis]
```

**Key details:**
- The API and worker share the same Python image but different commands
- DuckDB data is on a named volume (`duckdb-data`) shared between api and worker
- Environment variables configure everything — no config files to mount
- `depends_on` ensures Postgres and Redis start before the API

### Environment Variables

All configuration is via environment variables, following the
[12-Factor App](https://12factor.net/config) methodology:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAGBI_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `MAGBI_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `MAGBI_DUCKDB_DATA_DIR` | `data/datasets` | Where DuckDB files are stored |
| `MAGBI_JWT_SECRET` | `change-me-in-production` | Secret for signing JWTs |
| `MAGBI_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `MAGBI_ACCESS_TOKEN_TTL_MINUTES` | `60` | User token lifetime |
| `MAGBI_EMBED_TOKEN_TTL_MINUTES` | `15` | Embed token lifetime |
| `MAGBI_MAX_QUERY_TIMEOUT_SECONDS` | `30` | Maximum query execution time |
| `MAGBI_MAX_CONCURRENT_REFRESHES` | `10` | Platform-wide refresh limit |

**Why environment variables over config files?** Environment variables are
the standard in containerised deployments. Docker Compose, Kubernetes, and
every CI/CD system can inject them. Config files require volume mounts and
are harder to manage per-environment.

### Health Checks

Each service exposes a health check endpoint:

**API:** `GET /health` returns `{"status": "ok", "version": "0.1.0"}`

The health check verifies:
1. The FastAPI process is running and accepting requests
2. PostgreSQL is reachable (a lightweight query: `SELECT 1`)
3. Redis is reachable (`PING`)
4. The DuckDB data directory exists and is writable

In Docker Compose, health checks are configured with:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 5s
  retries: 3
```

In Kubernetes, these become liveness and readiness probes.

### Development Workflow

**Local development with hot reload:**

```bash
# Terminal 1: Start infrastructure
docker compose up postgres redis

# Terminal 2: Start API with hot reload
cd server
uvicorn magbi.main:app --reload --port 8000

# Terminal 3: Start frontend with hot reload
cd web
npm run dev   # Vite dev server on port 3000, proxies /api to :8000
```

**Why not run everything in Docker for development?** Hot reload inside Docker
containers is slow on macOS and Windows because filesystem events must cross
the VM boundary. Running the API and web servers natively gives sub-second
reload. Infrastructure services (Postgres, Redis) run in Docker because they
have no code to reload.

---

## Production Scaling

### Scaling the API

The API server is stateless (JWT auth, no sessions). To handle more requests:

```
                    ┌─────────┐
                    │  nginx  │ (or cloud load balancer)
                    └────┬────┘
                  ┌──────┼──────┐
                  ▼      ▼      ▼
              ┌──────┐┌──────┐┌──────┐
              │ api-1││ api-2││ api-3│
              └──────┘└──────┘└──────┘
```

Each API instance connects to the same PostgreSQL, Redis, and DuckDB volume.
No sticky sessions needed — any instance can serve any request.

**Bottleneck:** DuckDB files are on a shared volume. At very high concurrency,
filesystem I/O becomes the bottleneck. Mitigations:
- SSD storage for the DuckDB volume
- Query result caching in Redis reduces DuckDB reads
- For extreme scale: replicate DuckDB files to each API server's local disk

### Scaling the worker

Multiple Celery workers process refresh jobs in parallel:

```
              ┌───────────┐
              │   Redis   │ (message broker)
              └─────┬─────┘
              ┌─────┼─────┐
              ▼     ▼     ▼
          ┌──────┐┌──────┐┌──────┐
          │wkr-1 ││wkr-2 ││wkr-3 │
          └──────┘└──────┘└──────┘
```

The concurrency limits (1/dataset, 3/workspace, 10/platform) are enforced by
distributed locks in Redis. Adding more workers increases throughput up to the
platform limit.

### Scaling PostgreSQL

PostgreSQL handles metadata — workspace definitions, report JSONs, user
accounts. This is a low-volume workload. Scaling options:

1. **Read replicas** — for read-heavy loads, add replicas. The API reads from
   replicas and writes to the primary.
2. **Connection pooling** — PgBouncer reduces connection overhead.
3. **Vertical scaling** — give Postgres more RAM. For metadata workloads,
   even a small instance is usually sufficient.

### Scaling Redis

Redis handles caching, Celery messaging, and WebSocket pub/sub. Scaling options:

1. **Redis Sentinel** — automatic failover if the primary goes down
2. **Redis Cluster** — shards data across multiple nodes for capacity
3. **Separate instances** — one for cache, one for Celery, one for pub/sub.
   Different workloads benefit from different configurations.

---

## CI/CD Pipeline

### GitHub Actions

The `.github/workflows/ci.yml` pipeline runs on every push and pull request:

```
Job: server
  1. Checkout code
  2. Setup Python 3.11
  3. Install dependencies: pip install -e ".[dev]"
  4. Lint: ruff check magbi/
  5. Type check: mypy magbi/
  6. Test: pytest

Job: web
  1. Checkout code
  2. Setup Node 20
  3. Install dependencies: npm install
  4. Lint: eslint .
  5. Build: tsc -b && vite build
```

**Why two separate jobs?** Server and web are independent — a Python change
does not affect the frontend and vice versa. Running them in parallel cuts CI
time in half.

**Future additions:**
- Integration tests with a real PostgreSQL and Redis (Docker services in CI)
- End-to-end tests with Playwright (browser automation)
- Docker image build and push to a registry
- Automated deployment to staging on merge to main

---

## Monitoring

### Prometheus Metrics

The API server exposes metrics at `/metrics` (Prometheus exposition format):

| Metric | Type | What it measures |
|--------|------|-----------------|
| `magbi_http_requests_total` | Counter | Total requests by method, path, status |
| `magbi_http_request_duration_seconds` | Histogram | Request latency distribution |
| `magbi_query_duration_seconds` | Histogram | Query engine execution time |
| `magbi_query_cache_hits_total` | Counter | Cache hits vs. misses |
| `magbi_active_connections` | Gauge | Current WebSocket connections |
| `magbi_refresh_duration_seconds` | Histogram | Data refresh time per dataset |
| `magbi_duckdb_file_size_bytes` | Gauge | Size of each live DuckDB file |

### Key dashboards (Grafana)

1. **API Health** — request rate, error rate, latency percentiles (p50, p95, p99)
2. **Query Performance** — query duration distribution, cache hit rate, slow queries
3. **Refresh Pipeline** — refresh duration, success/failure rate, queue depth
4. **Resources** — CPU, memory, disk I/O per service

### Structured Logging

All services log in JSON format for easy parsing:

```json
{
  "timestamp": "2026-10-29T10:30:00Z",
  "level": "info",
  "service": "api",
  "event": "query_executed",
  "dataset_id": "ds-abc-123",
  "duration_ms": 145,
  "cached": false,
  "row_count": 2500
}
```

**Why JSON logging?** Log aggregation tools (ELK, Loki, CloudWatch) can parse
JSON fields and build dashboards. Plain text logs require regex parsing, which
is fragile and slow.

---

## Backup Strategy

| What | How | Frequency |
|------|-----|-----------|
| **PostgreSQL** | `pg_dump` to a compressed file | Daily, retained for 30 days |
| **DuckDB files** | File copy (rsync, S3 sync) | After each refresh |
| **Redis** | RDB snapshot or AOF persistence | Hourly (but Redis is a cache — loss is recoverable) |
| **Report definitions** | Stored in PostgreSQL, backed up with it | With PostgreSQL |

**Recovery time objective (RTO):** < 1 hour. Restore PostgreSQL from dump,
copy DuckDB files back, restart services.

**Recovery point objective (RPO):** < 1 day for metadata, < 1 refresh cycle
for data.

---

## Security Hardening

### For production deployments:

1. **TLS everywhere** — nginx terminates TLS. Internal service communication
   uses TLS if services are on different hosts.
2. **Non-root containers** — all containers run as a non-root user.
3. **Secrets management** — JWT secret and database passwords come from
   environment variables, injected by Docker secrets or a vault (HashiCorp
   Vault, AWS Secrets Manager).
4. **Network isolation** — PostgreSQL and Redis are not exposed to the public
   network. Only nginx is exposed.
5. **Read-only filesystems** — containers mount their filesystems as read-only
   except for specific writable paths (DuckDB data, temp files).
6. **Rate limiting** — nginx rate-limits requests before they reach FastAPI.
7. **CORS** — configured to allow only known origins.
8. **SQL injection prevention** — all queries use parameterised statements via
   sqlglot. No string concatenation of user input into SQL.

---

## Strengths

- **Single-command deployment** — `docker compose up` starts everything
- **Same containers dev and prod** — no "works in Docker but not on the server"
- **Stateless API** — horizontal scaling requires no shared state
- **Standard tooling** — Docker, nginx, Prometheus, GitHub Actions are
  well-understood by most teams
- **Progressive scaling** — start with one server, scale to many without
  architecture changes

## Weaknesses & Risks

- **Not Kubernetes-ready out of the box** — Docker Compose does not handle
  auto-scaling, rolling deploys, or self-healing. Moving to Kubernetes requires
  writing manifests (Helm charts or Kustomize overlays).
- **Shared DuckDB volume** — in a multi-server deployment, all API instances
  must access the same volume. This limits deployment to a single availability
  zone unless DuckDB files are replicated.
- **No blue-green deployment** — Docker Compose does not support running two
  versions simultaneously. Upgrades require brief downtime or a manual
  blue-green setup with an external load balancer.
- **Monitoring is BYO** — Prometheus, Grafana, and alerting must be set up
  separately. There is no built-in monitoring dashboard.

---

## For Agents

1. Deployment configuration lives in `deploy/`.
2. CI configuration lives in `.github/workflows/`.
3. Never hardcode secrets in Dockerfiles or compose files. Use environment
   variables.
4. When adding a new service dependency (e.g., a new database), add it to
   `docker-compose.yml` and document the environment variables.
5. Test Docker builds in CI — a Dockerfile that fails to build is a broken
   deployment.
6. When adding new Prometheus metrics, add them to the metrics table in this
   chapter.
7. Every new API endpoint should be covered by the CI test suite.

---

## Further Reading

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [The Twelve-Factor App](https://12factor.net/)
- [nginx Reverse Proxy Guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Container Security (Liz Rice)](https://www.oreilly.com/library/view/container-security/9781492056690/)
