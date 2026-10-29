# Feature: MAGBI-008 - Scheduled refresh

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 8 (Week 11-12). FR: FR-080, FR-083, FR-086.
Deliverable: a dataset cron schedule queues a refresh, the existing runner swaps the new DuckDB file in, and the previous file keeps serving until that swap.

## 1. Analysis
**Current state (verified)**: A manual refresh already queues one `dataset_refreshes` row, imports into `staging.duckdb`, and swaps it to `live.duckdb`. `queue_refresh` refuses a second queued or running refresh for the same dataset, and the partial unique index enforces that. `run_refresh` is a coroutine started by a FastAPI background task. The module comment says a Celery task will wrap it in this sprint. `celery` is a dependency and is not imported. `datasets.schedule_cron` exists and is unused. There is no route to set it. History is `GET /workspaces/{wid}/datasets/{did}/refresh/history` and returns status, timestamps, result, and error. `max_concurrent_refreshes` is 10 in settings. Nothing counts refreshes per workspace. `server/magbi/refresh/calculated.py` is a stub. Calculated columns are stored and shape-checked, and they are not written into DuckDB. Transform recipes are not applied during import.

**Affected files**:
- `server/magbi/refresh/orchestrator.py`, `calculated.py`, a new `schedule.py` and `worker.py`
- `server/magbi/api/refresh.py`, `server/magbi/api/schemas.py`
- `server/magbi/config.py`
- `server/tests/test_refresh/`
- `docs/kb/10-storage-refresh.md` (status note)

**Design decisions**:
1. **The runner stays `run_refresh`.** Celery calls that coroutine. The API keeps using a background task when no worker is running, so tests and a single process still refresh. `worker.py` exposes a Celery task with the same arguments. Tests call the coroutine and the schedule function directly. They do not need a broker.
2. **A schedule is a five-field cron expression on the dataset.** `PUT /workspaces/{wid}/datasets/{did}/schedule` sets it. `DELETE` clears it. An expression croniter cannot parse is 422 `BAD_SCHEDULE`. The stored column remains `schedule_cron`.
3. **The due scan queues, it does not import.** `enqueue_due(now)` loads datasets with a cron, and for each one whose previous fire is at or before `now` and whose latest successful finish is before that fire, it calls `queue_refresh(..., trigger="schedule")`. A dataset that already has an active refresh is skipped. The scan is idempotent for the same minute.
4. **Limits are checked before insert.** One active refresh per dataset stays a 409. A workspace with 3 queued or running refreshes, or a platform with `max_concurrent_refreshes` (default 10), returns 429 `REFRESH_LIMIT` and inserts nothing. The counts include every dataset, manual and scheduled.
5. **Calculated columns are written on the staging file before the swap.** Each expression must be a scalar the Sprint 4 binder already accepts. An aggregation is still an error. `RELATED` is not compiled. Columns are applied in dependency order. A failure fails the refresh, discards staging, and leaves `live.duckdb` in place.
6. **History gains `duration_seconds`.** It is `finished_at - started_at` when both exist, otherwise null. The existing history route stays. A second `/refreshes` path is not added.
7. **Transform recipes are still not applied on refresh.** Sprint 6 preview is separate. This sprint does not fold steps into the import.

**Risks**:
- **A schedule scan that also runs the import will lock tests to a broker.** Mitigation: the scan only inserts queued rows. A test then runs one `run_refresh` and asserts the swap.
- **A calculated column that names a missing source column fails the whole refresh.** Mitigation: the error names the column, and the test shows the previous live rows are unchanged.
- **Cron "every 30 minutes" fired twice in the same window.** Mitigation: the last success time is compared with the cron's previous fire, so one success covers that fire.

**Assumptions**:
- Incremental refresh stays stubbed.
- DirectQuery datasets are not scheduled. A schedule on a dataset with no import definition still fails at run time the way a manual refresh does.
- The in-process background task remains the execution path for the API. Operators can point Celery at `worker.py` without a second implementation.
- Display of the schedule in the UI waits for the designer.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Cron schedule and the due scan |
| TASK-2 | Concurrency limits and calculated columns |
| TASK-3 | Celery wrapper, docs, and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Schedule API | A five-field cron is stored and returned; a bad expression is 422; delete clears it | 3h | [x] |
| SUB-1.2 | Due scan | A dataset due at `now` is queued with trigger `schedule`; one already queued is skipped; a second scan in the same fire does not queue again after success | 4h | [x] |
| SUB-2.1 | Concurrency limits | A second refresh for one dataset stays 409; the fourth in a workspace and the one past the platform cap are 429 and do not insert a row | 3h | [ ] |
| SUB-2.2 | Calculated columns | A scalar calculated column is present in `live.duckdb` after a successful refresh; a bad expression fails the refresh and leaves the previous live file unchanged | 4h | [ ] |
| SUB-3.1 | Celery task and duration | A Celery task calls `run_refresh`; history includes `duration_seconds` | 2h | [ ] |
| SUB-3.2 | Docs | KB 10 says schedules queue the existing runner, calculated columns are scalar only, and recipes are not applied | 1.5h | [ ] |
| SUB-3.3 | Finalization | ruff, mypy strict, coverage over 80% for the schedule, limit, and calculated-column code; full regression; PR description | 1.5h | [ ] |

Order: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.3. Each subtask is code, tests, and one single-sentence commit. About 19 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. A five-field cron is stored on the dataset and returned. A bad expression is 422. Delete clears it.
- [x] SUB-1.2: see git log. A due dataset is queued with trigger schedule. An active refresh is skipped. A success in the same fire is not queued again.
- [ ] SUB-2.1: (Commit hash)
- [ ] SUB-2.2: (Commit hash)
- [ ] SUB-3.1: (Commit hash)
- [ ] SUB-3.2: (Commit hash)
- [ ] SUB-3.3: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage over 80% for the schedule, limit, and calculated-column code
- [ ] A due schedule queues a refresh and a failed refresh leaves the old data in place
- [ ] A calculated column is readable in `live.duckdb` after a successful refresh
- [ ] KB 10 updated to match the implementation
