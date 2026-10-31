"""OData and REST JSON connector against a mock HTTP service (no network)."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any

import duckdb
import httpx
import pytest
from pydantic import ValidationError

from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.odata import (
    ODataConfig,
    ODataConnector,
    flatten,
    infer_columns,
    parse_metadata,
    read_select,
)
from magbi.refresh.importer import TableSpec, import_tables

ROOT = "https://data.example.org/odata/"
METADATA = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="Shop" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <ComplexType Name="Address">
        <Property Name="City" Type="Edm.String"/>
        <Property Name="Region" Type="Edm.String"/>
      </ComplexType>
      <EntityType Name="Base">
        <Key><PropertyRef Name="ID"/></Key>
        <Property Name="ID" Type="Edm.Int32" Nullable="false"/>
      </EntityType>
      <EntityType Name="Order" BaseType="Shop.Base">
        <Property Name="Customer_Name" Type="Edm.String"/>
        <Property Name="Amount" Type="Edm.Decimal" Precision="12" Scale="2"/>
        <Property Name="Placed" Type="Edm.DateTimeOffset"/>
        <Property Name="Due" Type="Edm.Date"/>
        <Property Name="Paid" Type="Edm.Boolean"/>
        <Property Name="ShipTo" Type="Shop.Address"/>
        <Property Name="Tags" Type="Collection(Edm.String)"/>
        <NavigationProperty Name="Lines" Type="Collection(Shop.Line)"/>
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="Orders" EntityType="Shop.Order"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def order(i: int) -> dict[str, Any]:
    return {
        "@odata.etag": "W/1",
        "ID": i,
        "Customer_Name": f"Clinic {i}",
        "Amount": "10.25" if i % 2 else 7.5,
        "Placed": "2026-10-31T09:30:00+03:00",
        "Due": "2026-11-30",
        "Paid": i % 2 == 0,
        "ShipTo": {"City": "Dodoma", "Region": "Dodoma"},
        "Tags": ["a", "b"],
    }


class Service:
    """A tiny OData v4 service with 5 orders served 2 per page, plus a REST endpoint."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.next_host = "data.example.org"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if request.headers.get("Authorization") not in (
            None,
            "Bearer good-token",
        ) and not url.path.startswith("/odata/"):
            return httpx.Response(401)
        if url.path == "/odata/" or url.path == "/odata":
            return httpx.Response(
                200,
                json={
                    "@odata.context": f"{ROOT}$metadata",
                    "value": [
                        {"name": "Orders", "kind": "EntitySet", "url": "Orders"},
                        {"name": "Me", "kind": "Singleton", "url": "Me"},
                    ],
                },
                headers={"OData-Version": "4.0"},
            )
        if url.path == "/odata/$metadata":
            return httpx.Response(
                200, text=METADATA, headers={"Content-Type": "application/xml"}
            )
        if url.path == "/odata/Orders/$count":
            return httpx.Response(200, text="﻿5")
        if url.path == "/odata/Orders":
            skip = int(url.params.get("$skiptoken", "0"))
            top = url.params.get("$top")
            page = [order(i) for i in range(1, 6)][skip : skip + 2]
            body: dict[str, Any] = {"value": page}
            if skip + 2 < 5 and top is None:
                body["@odata.nextLink"] = (
                    f"https://{self.next_host}/odata/Orders?$skiptoken={skip + 2}"
                )
            return httpx.Response(200, json=body)
        if url.path == "/v2/":
            return httpx.Response(200, json={"d": {"EntitySets": ["Things"]}})
        if url.path == "/api/items":
            page = int(url.params.get("page", "1"))
            items = (
                [
                    {
                        "id": 1,
                        "name": "Gloves",
                        "price": 1.5,
                        "added": "2026-01-02",
                        "meta": {"origin": "TZ", "lot": None},
                    },
                    {
                        "id": 2,
                        "name": "Masks",
                        "price": 2,
                        "added": "2026-01-03",
                        "meta": {"origin": "KE", "lot": "L1"},
                    },
                ]
                if page == 1
                else [
                    {
                        "id": 3,
                        "name": "Syringes",
                        "price": 0.25,
                        "added": None,
                        "meta": {"origin": "TZ", "lot": "L2"},
                    }
                ]
            )
            following = "/api/items?page=2" if page == 1 else None
            return httpx.Response(
                200, json={"data": {"items": items}, "links": {"next": following}}
            )
        if url.path == "/moved":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})
        return httpx.Response(404)


def connect(service: Service, **config: Any) -> ODataConnector:
    connector = ODataConnector(transport=httpx.MockTransport(service))
    connector.connect({"url": ROOT, **config})
    return connector


def test_config_rules() -> None:
    assert ODataConfig.model_validate({"url": ROOT}).host == "data.example.org"
    for bad in (
        {"url": "ftp://x/"},
        {"url": "https://user:pw@x/"},
        {"url": ROOT, "authentication": "basic"},
        {"url": ROOT, "authentication": "bearer"},
        {"url": ROOT, "nope": 1},
    ):
        with pytest.raises(ValidationError):
            ODataConfig.model_validate(bad)


def test_metadata_flattens_complex_types_and_keeps_keys() -> None:
    columns = {c.name: c for c in parse_metadata(METADATA)["Orders"]}
    assert list(columns) == [
        "ID",
        "Customer_Name",
        "Amount",
        "Placed",
        "Due",
        "Paid",
        "ShipTo_City",
        "ShipTo_Region",
        "Tags",
    ]
    assert columns["ID"].is_primary_key and not columns["ID"].is_nullable
    assert (
        columns["Amount"].data_type,
        columns["Amount"].precision,
        columns["Amount"].scale,
    ) == ("edm.decimal", 12, 2)
    assert columns["Tags"].data_type == "collection(edm.string)"


def test_lists_entity_sets_not_singletons() -> None:
    connector = connect(Service())
    assert connector.get_server_version() == "OData 4.0 at data.example.org"
    assert connector.list_schemas() == ["odata"]
    tables = connector.list_tables("odata")
    assert [t.name for t in tables] == ["Orders"] and len(tables[0].columns) == 9
    assert connector.get_row_count("odata", "Orders") == 5


def test_reads_every_page_and_flattens() -> None:
    service = Service()
    connector = connect(service)
    table = connector.list_tables("odata")[0]
    rows = list(connector.execute_query(connector.build_select(table)))
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0][6:8] == ("Dodoma", "Dodoma") and rows[0][8] == ["a", "b"]
    assert sum(1 for r in service.requests if r.url.path == "/odata/Orders") == 3


def test_limit_uses_top_and_stops() -> None:
    service = Service()
    connector = connect(service)
    table = connector.list_tables("odata")[0]
    assert [r[0] for r in connector.preview("odata", "Orders", 1)] == [1]
    assert service.requests[-1].url.params["$top"] == "1"
    assert '"Orders" LIMIT 1' in connector.build_select(table, limit=1)


def test_a_next_link_to_another_host_is_refused() -> None:
    service = Service()
    service.next_host = "169.254.169.254"
    connector = connect(service)
    table = connector.list_tables("odata")[0]
    with pytest.raises(ConnectorError) as err:
        list(connector.execute_query(connector.build_select(table)))
    assert "another host" in err.value.message
    assert all(r.url.host == "data.example.org" for r in service.requests)


def test_redirects_are_not_followed() -> None:
    connector = ODataConnector(transport=httpx.MockTransport(Service()))
    with pytest.raises(ConnectorError) as err:
        connector.connect({"url": "https://data.example.org/moved"})
    assert "redirected" in err.value.message


def test_http_errors_map_to_codes_without_the_token() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    connector = ODataConnector(transport=httpx.MockTransport(refuse))
    result = connector.test_connection(
        {"url": ROOT, "authentication": "bearer", "password": "sekret-token"}
    )
    assert (
        not result.success
        and result.code is ErrorCode.AUTH_FAILED
        and "sekret" not in (result.error or "")
    )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    result = ODataConnector(transport=httpx.MockTransport(down)).test_connection(
        {"url": ROOT}
    )
    assert result.code is ErrorCode.UNREACHABLE


def test_bearer_token_is_sent_as_a_header() -> None:
    service = Service()
    connect(service, authentication="bearer", password="good-token")
    assert service.requests[0].headers["Authorization"] == "Bearer good-token"


def test_only_whole_table_selects_are_accepted() -> None:
    assert read_select('SELECT "a", "b" FROM "odata"."Orders" LIMIT 3') == (
        "odata",
        "Orders",
        ["a", "b"],
        3,
    )
    for sql in (
        'SELECT "a" FROM "odata"."Orders" WHERE "a" = 1',
        "SELECT 1",
        "DELETE FROM x",
        "SELECT a FROM x JOIN y ON 1=1",
    ):
        with pytest.raises(ConnectorError):
            read_select(sql)


def test_odata_v2_service_document() -> None:
    connector = ODataConnector(transport=httpx.MockTransport(Service()))
    connector.connect({"url": "https://data.example.org/v2/"})
    assert connector._entity_sets() == ["Things"]


def test_rest_json_with_records_and_next_paths() -> None:
    connector = ODataConnector(transport=httpx.MockTransport(Service()))
    connector.connect(
        {
            "url": "https://data.example.org/api/items",
            "format": "json",
            "table_name": "Items",
            "records_path": "data.items",
            "next_path": "links.next",
        }
    )
    assert connector.list_schemas() == ["json"]
    (table,) = connector.list_tables("json")
    assert [(c.name, c.data_type) for c in table.columns] == [
        ("id", "json.integer"),
        ("name", "json.string"),
        ("price", "json.number"),
        ("added", "json.date"),
        ("meta_origin", "json.string"),
        ("meta_lot", "json.string"),
    ]
    rows = list(connector.execute_query(connector.build_select(table)))
    assert [r[1] for r in rows] == ["Gloves", "Masks", "Syringes"] and rows[2][4:] == (
        "TZ",
        "L2",
    )
    assert connector.get_row_count("json", "Items") == -1


def test_rest_json_without_a_list_says_where_to_look() -> None:
    connector = ODataConnector(transport=httpx.MockTransport(Service()))
    connector.connect({"url": "https://data.example.org/api/items", "format": "json"})
    with pytest.raises(ConnectorError) as err:
        connector.list_tables("json")
    assert "records path" in err.value.message


def test_flatten_and_inference_helpers() -> None:
    assert flatten(
        {"a": {"b": {"c": 1}}, "@odata.id": "x", "n@odata.type": "y", "l": [1]}
    ) == {"a_b_c": 1, "l": [1]}
    assert [
        c.data_type
        for c in infer_columns(
            [
                {"x": 1, "y": True, "z": "2026-01-01T10:00:00Z"},
                {"x": 2.5, "y": None, "z": None},
            ]
        )
    ] == ["json.number", "json.boolean", "json.datetime"]


def test_imports_typed_values_into_duckdb() -> None:
    connector = connect(Service())
    staging = duckdb.connect()
    result = import_tables(
        connector,
        [TableSpec(schema="odata", name="Orders", target="Orders")],
        staging,
        batch_size=2,
    )
    assert result.tables[0].rows == 5 and result.total_rows == 5
    assert not [w for w in result.tables[0].warnings if "row count" in w]
    row = staging.execute(
        'SELECT "ID", "Amount", "Placed", "Due", "Paid", "ShipTo_City", "Tags" FROM "Orders" ORDER BY "ID" LIMIT 1'
    ).fetchone()
    assert row == (
        1,
        Decimal("10.25"),
        dt.datetime(2026, 10, 31, 6, 30),
        dt.date(2026, 11, 30),
        False,
        "Dodoma",
        json.dumps(["a", "b"]),
    )
    types = dict(
        staging.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'Orders'"
        ).fetchall()
    )
    assert (
        types["Amount"] == "DECIMAL(12,2)"
        and types["Placed"] == "TIMESTAMP"
        and types["Due"] == "DATE"
    )
