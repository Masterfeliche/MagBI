from pathlib import Path

import duckdb
import pytest

from tests.test_api.conftest import ApiEnv

V1 = "/api/v1"
CSV = b"Region,Amount\nEast,10\nWest,20\n"


def _dataset(api: ApiEnv) -> tuple[str, str]:
    wid = api.workspace()
    created = api.client.post(f"{V1}/workspaces/{wid}/datasets", json={"name": "d"})
    assert created.status_code == 201, created.text
    return wid, created.json()["id"]


def test_upload_csv_writes_table_and_definition(api: ApiEnv) -> None:
    wid, did = _dataset(api)
    uploaded = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={"file": ("sales.csv", CSV, "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    tables = body["definition"]["tables"]
    assert len(tables) == 1
    assert tables[0]["name"] == "sales"
    columns = {c["name"]: c["data_type"] for c in tables[0]["columns"]}
    assert columns["Region"] == "string"
    assert columns["Amount"] in {"integer", "decimal"}
    assert body["model_version"] == 2

    queried = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/query",
        json={
            "query": {
                "select": [
                    {
                        "column": {"table": "sales", "column": "Amount"},
                        "aggregation": "sum",
                    }
                ]
            }
        },
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()["rows"] == [[30]]


def test_second_upload_keeps_the_first_table(api: ApiEnv) -> None:
    wid, did = _dataset(api)
    first = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={"file": ("sales.csv", CSV, "text/csv")},
    )
    assert first.status_code == 200, first.text
    second = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={"file": ("dept.csv", b"Name\nHR\nFinance\n", "text/csv")},
    )
    assert second.status_code == 200, second.text
    names = [t["name"] for t in second.json()["definition"]["tables"]]
    assert "sales" in names
    assert "dept" in names

    sales = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/query",
        json={
            "query": {
                "select": [
                    {
                        "column": {"table": "sales", "column": "Amount"},
                        "aggregation": "sum",
                    }
                ]
            }
        },
    )
    assert sales.status_code == 200, sales.text
    assert sales.json()["rows"] == [[30]]


def test_upload_rejects_unsupported_and_empty_files(api: ApiEnv) -> None:
    wid, did = _dataset(api)
    bad = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={"file": ("notes.txt", b"nope", "text/plain")},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "UNSUPPORTED_FILE"
    empty = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={"file": ("sales.csv", b"", "text/csv")},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_xlsx_when_excel_extension_loads(api: ApiEnv, tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    probe = duckdb.connect()
    try:
        probe.execute("INSTALL excel")
        probe.execute("LOAD excel")
    except duckdb.Error:
        pytest.skip("DuckDB excel extension is not available")
    finally:
        probe.close()

    path = tmp_path / "Ledger.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Region", "Credit"])
    sheet.append(["East", 10])
    sheet.append(["West", 20])
    book.save(path)

    wid, did = _dataset(api)
    uploaded = api.client.post(
        f"{V1}/workspaces/{wid}/datasets/{did}/upload",
        files={
            "file": (
                "Ledger.xlsx",
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"table_name": "Ledger"},
    )
    assert uploaded.status_code == 200, uploaded.text
    table = uploaded.json()["definition"]["tables"][0]
    assert table["name"] == "Ledger"
    columns = {c["name"] for c in table["columns"]}
    assert "Region" in columns
    assert "Credit" in columns
