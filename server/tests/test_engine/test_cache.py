import duckdb

from magbi.connectors.types import DataType
from magbi.engine.cache import MemoryQueryCache, RedisQueryCache, cache_key, run_cached
from magbi.engine.semantic import parse_query
from tests.test_model.test_schema import col, definition, table


class _BrokenCache:
    def get(self, key: str) -> dict[str, object] | None:
        raise RuntimeError("redis down")

    def set(self, key: str, value: dict[str, object], ttl: int = 300) -> None:
        raise RuntimeError("redis down")


def test_a_repeat_hits_and_a_new_version_misses() -> None:
    model = definition(table("Sales", col("Amount", DataType.INTEGER)))
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER)')
    con.execute('INSERT INTO "Sales" VALUES (4), (6)')
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Amount"}, "aggregation": "sum"}
            ]
        }
    )
    cache = MemoryQueryCache()
    first = run_cached(model, query, con, cache=cache, dataset_id="ds", version=1)

    class _Counting:
        def __init__(self) -> None:
            self.n = 0

        def execute(self, sql: str) -> object:
            self.n += 1
            return con.execute(sql)

    wrapped = _Counting()
    second = run_cached(model, query, wrapped, cache=cache, dataset_id="ds", version=1)
    assert wrapped.n == 0
    assert second == first
    missed = run_cached(model, query, wrapped, cache=cache, dataset_id="ds", version=2)
    assert wrapped.n == 1
    assert missed["rows"] == [[10]]
    assert cache_key("ds", 1, query) != cache_key("ds", 2, query)


def test_a_broken_cache_still_returns_the_query() -> None:
    model = definition(table("Sales", col("Amount", DataType.INTEGER)))
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Amount" INTEGER)')
    con.execute('INSERT INTO "Sales" VALUES (3)')
    query = parse_query(
        {
            "select": [
                {"column": {"table": "Sales", "column": "Amount"}, "aggregation": "sum"}
            ]
        }
    )
    result = run_cached(
        model, query, con, cache=_BrokenCache(), dataset_id="ds", version=1
    )
    assert result["rows"] == [[3]]


def test_redis_round_trip_uses_the_client() -> None:
    class _Client:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def get(self, key: str) -> str | None:
            return self.store.get(key)

        def set(self, key: str, value: str, ex: int) -> None:
            self.store[key] = value

    cache = RedisQueryCache(_Client())
    cache.set("k", {"rows": []})
    assert cache.get("k") == {"rows": []}
    assert cache.get("missing") is None
