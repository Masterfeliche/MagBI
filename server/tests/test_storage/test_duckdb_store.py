from pathlib import Path

import duckdb
import pytest

from magbi.storage.duckdb_store import DuckDBStore, StoreError

DS = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(tmp_path / "datasets", archive_versions=2)


def publish(store: DuckDBStore, value: int) -> int | None:
    con = store.open_staging(DS)
    con.execute("CREATE TABLE t AS SELECT ? AS v", [value])
    con.close()
    return store.promote_staging(DS)


def read_live(store: DuckDBStore) -> int:
    con = store.open_live(DS)
    try:
        row = con.execute("SELECT v FROM t").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        con.close()


def test_missing_dataset(store: DuckDBStore) -> None:
    assert not store.exists(DS)
    assert store.list_versions(DS) == []
    assert store.list_datasets() == []
    with pytest.raises(StoreError):
        store.open_live(DS)


def test_first_promotion_has_no_archive(store: DuckDBStore) -> None:
    assert publish(store, 1) is None
    assert store.exists(DS)
    assert read_live(store) == 1
    assert store.list_versions(DS) == []
    assert not store.staging_path(DS).exists()


def test_second_promotion_archives_previous(store: DuckDBStore) -> None:
    publish(store, 1)
    assert publish(store, 2) == 1
    assert read_live(store) == 2
    assert store.list_versions(DS) == [1]
    old = duckdb.connect(str(store.version_path(DS, 1)), read_only=True)
    assert old.execute("SELECT v FROM t").fetchone() == (1,)
    old.close()


def test_archives_are_pruned_to_limit(store: DuckDBStore) -> None:
    for i in range(1, 6):
        publish(store, i)
    assert read_live(store) == 5
    assert store.list_versions(DS) == [4, 3]
    assert store.next_version(DS) == 5


def test_zero_archive_depth_keeps_none(tmp_path: Path) -> None:
    s = DuckDBStore(tmp_path, archive_versions=0)
    publish(s, 1)
    publish(s, 2)
    assert s.list_versions(DS) == []
    assert read_live(s) == 2


def test_promote_without_staging_fails(store: DuckDBStore) -> None:
    store.ensure_dataset(DS)
    with pytest.raises(StoreError):
        store.promote_staging(DS)


def test_failed_promotion_keeps_live(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    publish(store, 1)
    con = store.open_staging(DS)
    con.execute("CREATE TABLE t AS SELECT 2 AS v")
    con.close()

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src: object, dst: object) -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # staging -> live
            raise PermissionError("file in use")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr("magbi.storage.duckdb_store.os.replace", flaky)
    with pytest.raises(StoreError):
        store.promote_staging(DS)
    monkeypatch.undo()

    assert read_live(store) == 1  # old live restored
    assert store.staging_path(DS).exists()


def test_discard_staging(store: DuckDBStore) -> None:
    store.open_staging(DS).close()
    assert store.staging_path(DS).exists()
    store.discard_staging(DS)
    assert not store.staging_path(DS).exists()


def test_list_and_delete_datasets(store: DuckDBStore) -> None:
    publish(store, 1)
    store.ensure_dataset("other")
    assert store.list_datasets() == sorted([DS, "other"])
    store.delete_dataset(DS)
    assert store.list_datasets() == ["other"]


@pytest.mark.parametrize(
    "bad", ["", "..", "../x", "a/b", "a\\b", "/abs", ".hidden", "x" * 65, "a b"]
)
def test_invalid_ids_rejected(store: DuckDBStore, bad: str) -> None:
    with pytest.raises(StoreError):
        store.dataset_dir(bad)


def test_negative_archive_versions_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DuckDBStore(tmp_path, archive_versions=-1)
