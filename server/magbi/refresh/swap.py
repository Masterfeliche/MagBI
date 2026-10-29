"""Atomic swap of the staging DuckDB file into place.

``DuckDBStore.promote_staging`` renames files and restores the previous live file
if anything goes wrong. This module adds what a refresh needs around it:

* retries with backoff, because on Windows a reader that still holds the live
  file open makes the rename fail until it lets go;
* staging cleanup on final failure, so a failed refresh leaves nothing behind;
* the ``datasets.current_version`` update, only after the swap succeeded.

On any failure the previous live file keeps serving unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from magbi.metadata.models import Dataset
from magbi.storage.duckdb_store import DuckDBStore, StoreError

log = logging.getLogger("magbi.refresh")

DEFAULT_ATTEMPTS = 6
DEFAULT_BASE_DELAY = 0.25
MAX_DELAY = 5.0


class SwapError(Exception):
    """The new data could not be put in place; the old data is still live."""


def swap_with_retry(
    store: DuckDBStore,
    dataset_id: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> int | None:
    """Promote staging to live. Returns the archive number of the previous live file."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if not store.staging_path(dataset_id).is_file():
        raise SwapError(f"dataset {dataset_id} has no staging data to promote")

    last: StoreError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return store.promote_staging(dataset_id)
        except StoreError as exc:
            last = exc
            if attempt < attempts:
                delay = min(base_delay * 2 ** (attempt - 1), MAX_DELAY)
                log.warning(
                    "swap for %s failed (attempt %d/%d), retrying in %.2fs",
                    dataset_id,
                    attempt,
                    attempts,
                    delay,
                )
                sleep(delay)

    try:
        store.discard_staging(dataset_id)
    except OSError:
        log.warning("could not remove staging file for %s", dataset_id)
    raise SwapError(
        f"could not swap new data into place after {attempts} attempts; "
        "the previous version is still live (is a query holding the file open?)"
    ) from last


async def publish_version(
    session: AsyncSession,
    store: DuckDBStore,
    dataset_id: uuid.UUID,
    version: int,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> None:
    """Swap files, then record ``version`` as the dataset's current version."""
    await asyncio.to_thread(
        swap_with_retry,
        store,
        str(dataset_id),
        attempts=attempts,
        base_delay=base_delay,
    )
    await session.execute(
        update(Dataset).where(Dataset.id == dataset_id).values(current_version=version)
    )
    await session.commit()
