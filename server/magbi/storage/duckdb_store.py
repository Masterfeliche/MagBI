"""DuckDB dataset store — one directory per dataset, one file per version.

Layout (see docs/kb/10-storage-refresh.md)::

    {root}/{dataset_id}/live.duckdb      current version, read by the query engine
    {root}/{dataset_id}/v{N}.duckdb      archived versions, newest N kept
    {root}/{dataset_id}/staging.duckdb   being written by the refresh worker

Promotion archives ``live`` as ``v{max+1}`` and renames ``staging`` to ``live``.
On Windows a file that a reader still holds open cannot be renamed; promotion
then fails with ``StoreError`` and leaves the live file untouched.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import duckdb

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^v(\d+)\.duckdb$")

LIVE = "live.duckdb"
STAGING = "staging.duckdb"


class StoreError(Exception):
    """Raised for invalid ids, missing files, or failed promotions."""


class DuckDBStore:
    def __init__(self, root: Path, archive_versions: int = 5) -> None:
        if archive_versions < 0:
            raise ValueError("archive_versions must be >= 0")
        self.root = Path(root)
        self.archive_versions = archive_versions

    # -- paths ---------------------------------------------------------------

    def dataset_dir(self, dataset_id: str) -> Path:
        if not _ID_RE.match(dataset_id):
            raise StoreError(f"invalid dataset id: {dataset_id!r}")
        return self.root / dataset_id

    def live_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / LIVE

    def staging_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / STAGING

    def version_path(self, dataset_id: str, version: int) -> Path:
        return self.dataset_dir(dataset_id) / f"v{version}.duckdb"

    # -- lifecycle -----------------------------------------------------------

    def ensure_dataset(self, dataset_id: str) -> Path:
        path = self.dataset_dir(dataset_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, dataset_id: str) -> bool:
        return self.live_path(dataset_id).is_file()

    def list_datasets(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and _ID_RE.match(p.name)
        )

    def delete_dataset(self, dataset_id: str) -> None:
        shutil.rmtree(self.dataset_dir(dataset_id), ignore_errors=True)

    # -- versions ------------------------------------------------------------

    def list_versions(self, dataset_id: str) -> list[int]:
        """Archived version numbers, newest first."""
        directory = self.dataset_dir(dataset_id)
        if not directory.is_dir():
            return []
        found = []
        for p in directory.iterdir():
            m = _VERSION_RE.match(p.name)
            if m:
                found.append(int(m.group(1)))
        return sorted(found, reverse=True)

    def next_version(self, dataset_id: str) -> int:
        versions = self.list_versions(dataset_id)
        return (versions[0] + 1) if versions else 1

    # -- connections ---------------------------------------------------------

    def open_live(self, dataset_id: str) -> duckdb.DuckDBPyConnection:
        """Open the live file read-only for querying."""
        path = self.live_path(dataset_id)
        if not path.is_file():
            raise StoreError(f"dataset {dataset_id} has no live data")
        return _retry_shared(lambda: duckdb.connect(str(path), read_only=True))

    def open_staging(self, dataset_id: str) -> duckdb.DuckDBPyConnection:
        """Open (creating if needed) the staging file for writing."""
        self.ensure_dataset(dataset_id)
        path = str(self.staging_path(dataset_id))
        return _retry_shared(lambda: duckdb.connect(path))

    def discard_staging(self, dataset_id: str) -> None:
        for suffix in ("", ".wal"):
            Path(str(self.staging_path(dataset_id)) + suffix).unlink(missing_ok=True)

    # -- promotion -----------------------------------------------------------

    def promote_staging(self, dataset_id: str) -> int | None:
        """Make staging the live file. Returns the archive version given to the
        previous live file, or ``None`` if there was none."""
        staging = self.staging_path(dataset_id)
        live = self.live_path(dataset_id)
        if not staging.is_file():
            raise StoreError(f"dataset {dataset_id} has no staging data")

        archived: int | None = None
        archive_path: Path | None = None
        try:
            if live.is_file():
                archived = self.next_version(dataset_id)
                archive_path = self.version_path(dataset_id, archived)
                _retry_shared(lambda: os.replace(live, archive_path))
            _retry_shared(lambda: os.replace(staging, live))
        except OSError as exc:
            if archive_path is not None and not live.exists():
                os.replace(archive_path, live)  # restore previous live file
            raise StoreError(
                f"could not promote staging for {dataset_id}: {exc}"
            ) from exc

        self._prune(dataset_id)
        return archived

    def _prune(self, dataset_id: str) -> None:
        for version in self.list_versions(dataset_id)[self.archive_versions :]:
            self.version_path(dataset_id, version).unlink(missing_ok=True)


T = TypeVar("T")
_SHARING = ("being used by another process", "sharing violation", "access is denied")


def _retry_shared(action: Callable[[], T], attempts: int = 20, pause: float = 0.15) -> T:
    """Retry a file open or rename that Windows briefly refuses.

    A freshly written file can be held for a moment by another process (an
    antivirus scan, the search indexer). Anything else fails at once.
    """
    for attempt in range(attempts):
        try:
            return action()
        except (OSError, duckdb.IOException) as exc:
            if attempt == attempts - 1 or not any(text in str(exc).lower() for text in _SHARING):
                raise
            time.sleep(pause)
    raise AssertionError("unreachable")
