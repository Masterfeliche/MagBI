# Feature: MAGBI-001 - Foundation: metadata models, DuckDB store, credential encryption

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 1 (Week 1-2). FRs: FR-006, FR-090.
Deliverable: `docker compose up` -> API starts, `/health` OK, Postgres has the schema, `data/datasets/` ready.

## 1. Analysis
**Affected files**:
- `server/magbi/metadata/models.py` (new: ORM models, async engine/session)
- `server/magbi/metadata/__init__.py`, `server/magbi/metadata/db.py` (new: engine + session factory)
- `server/alembic.ini`, `server/migrations/` (new: env.py, versions/0001_initial.py)
- `server/magbi/storage/duckdb_store.py` (new: per-dataset file + version management)
- `server/magbi/storage/credentials.py` (new: AES-256-GCM encrypt/decrypt)
- `server/magbi/config.py` (add `credential_key`, validation)
- `server/magbi/main.py` (lifespan startup checks, `/health/ready`)
- `server/pyproject.toml` (add `cryptography` explicitly, pytest config, test deps)
- `server/Dockerfile` (fix install order so the package builds)
- `deploy/docker-compose.yml` (pass `MAGBI_CREDENTIAL_KEY`; worker target is Sprint 8, out of scope)
- `server/tests/test_metadata.py`, `test_storage.py`, `conftest.py` (new)
- `docs/kb/10-storage-refresh.md` (status Planned -> In Progress, note deviations)

**Current state (verified)**: only `main.py` (/health), `config.py`, `connectors/base.py` contain logic. Every other module is a docstring. No Alembic tree, no tests, no pytest config. Directory is not a git repo, so the commit-msg hook and single-sentence commit rule cannot be enforced yet.

**Design decisions**:
1. **Tables (Sprint 1 scope)**: `workspaces`, `datasets`, `reports`, `users`, `audit_log`, plus `workspace_members` (needed to make roles meaningful later). Other tables in the architecture doc (connections, dataset_versions, refreshes, rls, apps, embed_clients) are deferred to the sprints that use them, each as its own migration.
2. **Primary keys**: UUID (the KB already addresses datasets by `{dataset-uuid}`). Timestamps are timezone-aware UTC.
3. **JSON columns**: `JSON` type with Postgres `JSONB` variant. Tests run on SQLite so the metadata layer stays portable (architecture doc says SQLite in dev).
4. **Driver**: SQLAlchemy 2.0 async. Tests use `sqlite+aiosqlite`; production uses `asyncpg`. Alembic runs with the sync-compatible async pattern in `env.py`.
5. **DuckDB layout** per KB 10: `data/datasets/{uuid}/live.duckdb` + `vN.duckdb`, 5 archived versions kept (configurable).
6. **Credentials**: AES-256-GCM via `cryptography`. Key is 32 bytes, base64 in env `MAGBI_CREDENTIAL_KEY` (never in the DB, never logged). Output format: `v1:` + base64(nonce[12] || ciphertext+tag). Optional AAD (e.g. connection id) binds a secret to its row. The import-pipeline spec says `CREDENTIAL_KEY`; we use the `MAGBI_` prefix to match `Settings` and will fix the spec.

**Risks**:
- **Windows atomic swap**: `os.rename` over an open file fails on Windows (KB claims POSIX semantics). Use `os.replace` and keep `live.duckdb` closed by readers briefly, or resolve the live file through a version pointer instead of renaming. Sprint 1 ships the store API with `os.replace` and a documented Windows caveat; the swap itself is Sprint 2.3.
- **Default `jwt_secret` and missing `credential_key`** would silently run insecurely. Startup must fail fast outside dev.
- **Dockerfile**: `pip install .` runs before the source is copied, so the image build fails. Fixed here because the deliverable requires `docker compose up`.
- **Python version drift**: API spec says 3.12, code/CI say 3.11, local machine is 3.14. Keep `>=3.11`; verify DuckDB and asyncpg wheels install on 3.14 before relying on it locally.
- **Scope creep**: R5 in the SRS. Only the five core tables plus members in Sprint 1.
- **No git repo**: needs `git init` (or a remote clone) before commits can follow AGENTS.md.

**Assumptions**:
- PostgreSQL 16 from compose is the production metadata DB; SQLite is acceptable for unit tests.
- Key management beyond a single env key (rotation, KMS) is out of scope; the `v1:` prefix leaves room for it.
- `/health` stays unauthenticated; `/health/ready` checks Postgres and the data dir.
- Auth, password hashing, and user CRUD are Sprint 7; `users` here is schema only.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Metadata layer: ORM models, async session, Alembic initial migration (1.1, 1.2) |
| TASK-2 | Storage layer: DuckDB dataset store and AES-256-GCM credential vault (1.3, 1.4) |
| TASK-3 | Startup hardening: settings validation, readiness checks, Docker fix (1.5) |
| TASK-4 | Test suite and tooling for the above (1.6) |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-0.1 | Init git repo and install commit-msg hook | `git init`; hook rejects multi-sentence or >72 char messages | 0.5h | [x] |
| SUB-0.2 | Test tooling: pytest config, conftest, aiosqlite, cryptography deps | `pytest` collects and runs a smoke test; CI green | 1h | [x] |
| SUB-1.1 | Credential vault (`credentials.py`) | Round-trip OK; wrong key/AAD/tampered data raise; nonce unique per call; bad key length rejected; plaintext never in repr/log | 2h | [ ] |
| SUB-1.2 | Settings: `credential_key`, `environment`, validation | Missing/invalid key or default jwt secret fails startup when `environment != dev` | 1h | [ ] |
| SUB-1.3 | DuckDB store (`duckdb_store.py`) | Create dataset dir; open live read-only/read-write; next version path; promote staging to live; archive pruning to N; list versions; path traversal on ids rejected | 3h | [ ] |
| SUB-1.4 | Metadata ORM models + session factory | Models for workspaces, workspace_members, datasets, reports, users, audit_log; UUID PKs; FKs and unique constraints | 3h | [ ] |
| SUB-1.5 | Alembic setup + `0001_initial` migration | `alembic upgrade head` and `downgrade base` succeed on SQLite and Postgres; models match migration (autogenerate shows no diff) | 2h | [ ] |
| SUB-1.6 | Metadata CRUD tests | Create/read/update/delete each entity; cascade rules; constraint violations raise | 2h | [ ] |
| SUB-1.7 | Lifespan startup checks + `/health/ready` | Ready returns 200 only when DB reachable and data dir writable; otherwise 503 with reason | 2h | [ ] |
| SUB-1.8 | Fix server Dockerfile and compose env | `docker compose build api` succeeds; api container reaches ready against compose Postgres | 1.5h | [ ] |
| SUB-1.9 | Docs: update KB 10, fix `CREDENTIAL_KEY` naming in import spec, mark status | KB chapter reflects what was built | 1h | [ ] |
| SUB-1.10 | Finalization: ruff, mypy --strict, coverage >80% for metadata and storage | All three pass; PR description generated | 1h | [ ] |

Order: 0.1 -> 0.2 -> 1.1 -> 1.2 -> 1.3 -> 1.4 -> 1.5 -> 1.6 -> 1.7 -> 1.8 -> 1.9 -> 1.10. Each subtask is Code + Test + one single-sentence commit.

---

## 3. Execution Log
- [x] SUB-0.1: cd03665 (hook verified: rejects multi-sentence and bad format)
- [x] SUB-0.2: 357d194 (also fixed 3 baseline ruff/mypy errors that would fail CI)
- [ ] SUB-1.1: (Commit hash)
- [ ] SUB-1.2: (Commit hash)
- [ ] SUB-1.3: (Commit hash)
- [ ] SUB-1.4: (Commit hash)
- [ ] SUB-1.5: (Commit hash)
- [ ] SUB-1.6: (Commit hash)
- [ ] SUB-1.7: (Commit hash)
- [ ] SUB-1.8: (Commit hash)
- [ ] SUB-1.9: (Commit hash)
- [ ] SUB-1.10: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests/lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage > 80% for `metadata` and `storage`
- [ ] KB chapter 10 updated to match the implementation
