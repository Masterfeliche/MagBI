"""OData and REST JSON connector (httpx).

``format: "odata"`` reads an OData service (v4, and v2 JSON): its entity sets
are the tables, their properties the columns (from ``$metadata``), and pages
are followed by their next links. ``format: "json"`` reads one REST endpoint
that returns a JSON array, or an object holding one (``records_path``), with
the next page's URL at ``next_path``; its columns are read from the first page.

Nested objects are flattened into columns joined by ``_`` (``Address_City``);
lists are kept as JSON text.

Safety properties:
* Only GET requests are made, and only to the configured host: a next link to
  another host is refused, and redirects aren't followed.
* The password or token is sent only as the Authorization header and is never
  part of an error message.
* The connector speaks a small SELECT built by ``build_select`` (columns,
  table, LIMIT); anything else is refused, so no SQL reaches the service.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import quote, urljoin, urlsplit

import httpx
import sqlglot
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlglot import exp

from magbi.connectors.base import CastKind, Connector, SourceColumn, SourceTable
from magbi.connectors.errors import ConnectorError, ErrorCode

DIALECT = "odata"
_SQL = "duckdb"  # the dialect of the small SELECTs this connector builds and reads
SAMPLE_ROWS = 200
MAX_DEPTH = 3
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)


class ODataConfig(BaseModel):
    """Connection settings. ``password`` (or the bearer token) is kept separate from the stored config."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=2000)
    format: Literal["odata", "json"] = "odata"
    authentication: Literal["none", "basic", "bearer"] = "none"
    username: str | None = Field(default=None, max_length=256)
    password: SecretStr | None = None
    table_name: str = Field(default="records", min_length=1, max_length=128)
    records_path: str = Field(default="", max_length=200)
    next_path: str = Field(default="", max_length=200)
    page_size: int = Field(default=1000, ge=10, le=10000)
    timeout: int = Field(default=60, ge=1, le=600)

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        parts = urlsplit(v.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("must be an http or https URL")
        if parts.username or parts.password:
            raise ValueError(
                "put the user name and password in their own fields, not the URL"
            )
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("must not contain control characters")
        return v.strip()

    @model_validator(mode="after")
    def _credentials(self) -> ODataConfig:
        if self.authentication == "basic" and (
            not self.username or self.password is None
        ):
            raise ValueError("basic authentication requires username and password")
        if self.authentication == "bearer" and self.password is None:
            raise ValueError("bearer authentication requires the token in password")
        return self

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def root(self) -> str:
        return self.url if self.url.endswith("/") else self.url + "/"


# -- flattening -----------------------------------------------------------------


def flatten(
    record: Mapping[str, Any], prefix: str = "", depth: int = 0
) -> dict[str, Any]:
    """``{"Address": {"City": "Dodoma"}}`` -> ``{"Address_City": "Dodoma"}``; lists stay whole."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key.startswith("@") or key == "__metadata" or "@odata." in key:
            continue  # annotations, not data
        name = f"{prefix}{key}"
        if isinstance(value, dict) and depth < MAX_DEPTH and "__deferred" not in value:
            out.update(flatten(value, f"{name}_", depth + 1))
        elif isinstance(value, dict) and "__deferred" in value:
            continue  # an OData v2 link to related records
        else:
            out[name] = value
    return out


def _json_type(values: list[Any]) -> str:
    """The column type of sampled JSON values."""
    seen = {type(v) for v in values if v is not None}
    if not seen:
        return "json.string"
    if seen <= {bool}:
        return "json.boolean"
    if seen <= {int}:
        return "json.integer"
    if seen <= {int, float}:
        return "json.number"
    if seen <= {str}:
        texts = [v for v in values if v]
        if texts and all(_ISO_DATE.match(t) for t in texts):
            return "json.date"
        if texts and all(_ISO_DATETIME.match(t) for t in texts):
            return "json.datetime"
        return "json.string"
    if seen <= {list}:
        return "json.array"
    return "json.object"


def infer_columns(records: Sequence[Mapping[str, Any]]) -> list[SourceColumn]:
    rows = [flatten(r) for r in records]
    names: dict[str, None] = {}
    for row in rows:
        names.update(dict.fromkeys(row))
    return [
        SourceColumn(name=name, data_type=_json_type([row.get(name) for row in rows]))
        for name in names
    ]


# -- $metadata ----------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_metadata(xml_text: str) -> dict[str, list[SourceColumn]]:
    """Each entity set's columns, complex types flattened, from an OData ``$metadata`` document."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise ConnectorError(
            ErrorCode.QUERY_FAILED, "the service's $metadata isn't valid XML"
        ) from None
    entity_types: dict[str, ET.Element] = {}
    complex_types: dict[str, ET.Element] = {}
    sets: dict[str, str] = {}
    for schema in root.iter():
        if _local(schema.tag) != "Schema":
            continue
        namespace = schema.get("Namespace", "")
        alias = schema.get("Alias")
        for child in schema:
            kind, name = _local(child.tag), child.get("Name", "")
            for prefix in filter(None, (namespace, alias)):
                if kind == "EntityType":
                    entity_types[f"{prefix}.{name}"] = child
                elif kind == "ComplexType":
                    complex_types[f"{prefix}.{name}"] = child
            if kind == "EntityContainer":
                for entity_set in child:
                    if _local(entity_set.tag) == "EntitySet":
                        sets[entity_set.get("Name", "")] = entity_set.get(
                            "EntityType", ""
                        )

    def base_chain(
        element: ET.Element, types: dict[str, ET.Element]
    ) -> list[ET.Element]:
        chain = [element]
        while (base := chain[-1].get("BaseType")) and base in types and len(chain) < 10:
            chain.append(types[base])
        return list(reversed(chain))

    def columns_of(
        element: ET.Element, prefix: str, depth: int, keys: set[str]
    ) -> list[SourceColumn]:
        out: list[SourceColumn] = []
        for part in base_chain(
            element,
            complex_types if element in complex_types.values() else entity_types,
        ):
            for prop in part:
                if _local(prop.tag) != "Property":
                    continue
                name, type_name = prop.get("Name", ""), prop.get("Type", "Edm.String")
                if type_name in complex_types and depth < MAX_DEPTH:
                    out.extend(
                        columns_of(
                            complex_types[type_name],
                            f"{prefix}{name}_",
                            depth + 1,
                            set(),
                        )
                    )
                    continue
                precision, scale = prop.get("Precision"), prop.get("Scale")
                out.append(
                    SourceColumn(
                        name=f"{prefix}{name}",
                        data_type=type_name.lower()
                        if type_name.startswith(("Edm.", "Collection("))
                        else "json.object",
                        is_nullable=prop.get("Nullable", "true").lower() != "false",
                        is_primary_key=not prefix and name in keys,
                        precision=int(precision)
                        if precision and precision.isdigit()
                        else None,
                        scale=int(scale) if scale and scale.isdigit() else None,
                    )
                )
        return out

    result: dict[str, list[SourceColumn]] = {}
    for set_name, type_name in sets.items():
        element = entity_types.get(type_name)
        if element is None:
            continue
        keys = {
            ref.get("Name", "")
            for part in base_chain(element, entity_types)
            for key in part
            if _local(key.tag) == "Key"
            for ref in key
            if _local(ref.tag) == "PropertyRef"
        }
        result[set_name] = columns_of(element, "", 0, keys)
    return result


# -- the SELECTs this connector understands ----------------------------------------------


def build_select_sql(table: SourceTable, limit: int | None = None) -> str:
    if not table.columns:
        raise ConnectorError(
            ErrorCode.UNSUPPORTED, f"{table.qualified_name} has no columns"
        )
    query = exp.select(*(exp.column(c.name, quoted=True) for c in table.columns)).from_(
        exp.table_(table.name, db=table.schema, quoted=True)
    )
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        query = query.limit(limit)
    return query.sql(dialect=_SQL)


def read_select(sql: str) -> tuple[str, str, list[str], int | None]:
    """(schema, table, columns, limit) of a SELECT built by ``build_select_sql``."""
    try:
        parsed = sqlglot.parse_one(sql, dialect=_SQL)
    except sqlglot.errors.ParseError:
        parsed = None
    if (
        not isinstance(parsed, exp.Select)
        or parsed.args.get("where")
        or parsed.args.get("joins")
        or parsed.args.get("group")
    ):
        raise ConnectorError(
            ErrorCode.UNSUPPORTED,
            "this source takes whole tables only, not SQL queries",
        )
    source = parsed.find(exp.From)
    table = source.this if source is not None else None
    if not isinstance(table, exp.Table):
        raise ConnectorError(
            ErrorCode.UNSUPPORTED,
            "this source takes whole tables only, not SQL queries",
        )
    columns = []
    for item in parsed.expressions:
        if not isinstance(item, exp.Column):
            raise ConnectorError(
                ErrorCode.UNSUPPORTED,
                "this source takes whole tables only, not SQL queries",
            )
        columns.append(item.name)
    limit_node = parsed.args.get("limit")
    limit = int(limit_node.expression.name) if limit_node is not None else None
    return table.db, table.name, columns, limit


def _path(data: Any, path: str) -> Any:
    for part in filter(None, path.split(".")):
        data = data.get(part) if isinstance(data, dict) else None
    return data


class ODataConnector(Connector):
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client: httpx.Client | None = None
        self._cfg: ODataConfig | None = None
        self._transport = transport  # tests pass a mock transport
        self._catalog: dict[str, SourceTable] = {}
        self._version = ""

    # -- lifecycle -----------------------------------------------------------

    def connect(self, config: Mapping[str, Any]) -> None:
        try:
            cfg = ODataConfig.model_validate(dict(config))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'config'}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConnectorError(ErrorCode.INVALID_CONFIG, problems) from None
        self.close()
        headers = {
            "Accept": "application/json",
            "User-Agent": "MagBI",
            "OData-MaxVersion": "4.0",
        }
        auth: httpx.Auth | None = None
        if cfg.authentication == "basic" and cfg.username and cfg.password is not None:
            auth = httpx.BasicAuth(cfg.username, cfg.password.get_secret_value())
        elif cfg.authentication == "bearer" and cfg.password is not None:
            headers["Authorization"] = f"Bearer {cfg.password.get_secret_value()}"
        self._client = httpx.Client(
            headers=headers,
            auth=auth,
            timeout=cfg.timeout,
            follow_redirects=False,
            transport=self._transport,
        )
        self._cfg = cfg
        self._catalog = {}
        # Reach the service now, so a wrong URL or login fails here.
        response = self._get(cfg.url)
        version = response.headers.get("OData-Version") or response.headers.get("DataServiceVersion") or ""
        self._version = version.split(";", 1)[0].strip()  # v2 sends "2.0;"

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def _config(self) -> ODataConfig:
        if self._client is None or self._cfg is None:
            raise ConnectorError(ErrorCode.NOT_CONNECTED, "not connected")
        return self._cfg

    def _get(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        cfg = self._config()
        assert self._client is not None
        if urlsplit(url).hostname != cfg.host:
            raise ConnectorError(
                ErrorCode.QUERY_FAILED,
                "the service pointed to another host; MagBI only reads from the one configured",
            )
        try:
            response = self._client.get(
                url, params=params, headers={"Accept": accept} if accept else None
            )
        except httpx.TimeoutException:
            raise ConnectorError(
                ErrorCode.TIMEOUT, f"{cfg.host} didn't answer within {cfg.timeout} s"
            ) from None
        except httpx.HTTPError as exc:
            raise ConnectorError(
                ErrorCode.UNREACHABLE,
                f"couldn't reach {cfg.host} ({type(exc).__name__})",
            ) from None
        status = response.status_code
        if status in (401, 403):
            raise ConnectorError(
                ErrorCode.AUTH_FAILED, f"{cfg.host} refused the login (HTTP {status})"
            )
        if status == 404:
            raise ConnectorError(
                ErrorCode.NOT_FOUND, f"{urlsplit(url).path} wasn't found on {cfg.host}"
            )
        if 300 <= status < 400:
            raise ConnectorError(
                ErrorCode.QUERY_FAILED,
                f"{cfg.host} redirected the request (HTTP {status}); use the final URL",
            )
        if status >= 400:
            raise ConnectorError(
                ErrorCode.QUERY_FAILED, f"{cfg.host} answered HTTP {status}"
            )
        return response

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ConnectorError(
                ErrorCode.QUERY_FAILED, "the service didn't return JSON"
            ) from None

    # -- metadata ------------------------------------------------------------

    def get_server_version(self) -> str:
        cfg = self._config()
        if cfg.format == "json":
            return f"REST JSON at {cfg.host}"
        return f"OData {self._version or 'service'} at {cfg.host}"

    def list_schemas(self) -> list[str]:
        return [self._config().format]

    def _entity_sets(self) -> list[str]:
        cfg = self._config()
        body = self._json(self._get(cfg.url))
        if isinstance(body, dict) and isinstance(
            body.get("value"), list
        ):  # v4 service document
            return [
                str(item["name"])
                for item in body["value"]
                if isinstance(item, dict)
                and item.get("kind", "EntitySet") == "EntitySet"
                and item.get("name")
            ]
        sets = _path(body, "d.EntitySets")  # v2
        if isinstance(sets, list):
            return [str(name) for name in sets]
        raise ConnectorError(
            ErrorCode.QUERY_FAILED,
            "this URL isn't an OData service root; use the JSON format for a plain REST endpoint",
        )

    def list_tables(self, schema: str) -> list[SourceTable]:
        cfg = self._config()
        if schema != cfg.format:
            return []
        if cfg.format == "json":
            records, _ = self._page(cfg.url)
            table = SourceTable(
                schema=schema,
                name=cfg.table_name,
                columns=infer_columns(records[:SAMPLE_ROWS]),
            )
            self._catalog = {table.name: table}
            return [table]
        names = self._entity_sets()
        metadata = parse_metadata(
            self._get(urljoin(cfg.root, "$metadata"), accept="application/xml").text
        )
        tables = [
            SourceTable(schema=schema, name=name, columns=metadata.get(name, []))
            for name in names
        ]
        self._catalog = {t.name: t for t in tables}
        return tables

    def _table(self, schema: str, name: str) -> SourceTable:
        if name not in self._catalog:
            self.list_tables(schema)
        return (
            self.find_table(schema, name)
            if name not in self._catalog
            else self._catalog[name]
        )

    # -- data ----------------------------------------------------------------

    def get_dialect(self) -> str:
        return DIALECT

    def build_select(
        self,
        table: SourceTable,
        *,
        casts: Mapping[str, CastKind] = MappingProxyType({}),
        limit: int | None = None,
    ) -> str:
        return build_select_sql(
            table, limit
        )  # values are converted on arrival, not in a cast

    def get_row_count(self, schema: str, table: str) -> int:
        """The entity set's count, or -1 when the service can't count."""
        cfg = self._config()
        found = self._table(schema, table)
        if cfg.format == "json":
            return -1
        try:
            text = self._get(
                urljoin(cfg.root, quote(found.name) + "/$count"), accept="text/plain"
            ).text.strip()
            return int(text.lstrip("﻿"))
        except (ConnectorError, ValueError):
            return -1

    def execute_query(
        self, sql: str, *, batch_size: int = 10_000
    ) -> Iterator[tuple[Any, ...]]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        schema, name, columns, limit = read_select(sql)
        table = self._table(schema, name)
        known = {c.name for c in table.columns}
        unknown = [c for c in columns if c not in known]
        if unknown:
            raise ConnectorError(
                ErrorCode.NOT_FOUND, f"{name} has no column {unknown[0]}"
            )
        return self._rows(table, columns, limit)

    def _first_url(
        self, table: SourceTable, limit: int | None
    ) -> tuple[str, dict[str, str]]:
        # Whole entities are read: a flattened column (Address_City) can't be told
        # apart from a property with an underscore, so $select isn't used.
        cfg = self._config()
        if cfg.format == "json":
            return cfg.url, {}
        return urljoin(cfg.root, quote(table.name)), {
            "$top": str(limit)
        } if limit is not None else {}

    def _page(
        self, url: str, params: Mapping[str, str] | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        cfg = self._config()
        body = self._json(self._get(url, params=params))
        if cfg.format == "json":
            records = _path(body, cfg.records_path) if cfg.records_path else body
            if not isinstance(records, list):
                where = (
                    f"at '{cfg.records_path}'"
                    if cfg.records_path
                    else "at the top level"
                )
                raise ConnectorError(
                    ErrorCode.QUERY_FAILED,
                    f"no list of records {where} of the response; set the records path",
                )
            following = (
                _path(body, cfg.next_path)
                if cfg.next_path and isinstance(body, dict)
                else None
            )
        else:
            records = body.get("value") if isinstance(body, dict) else None
            following = body.get("@odata.nextLink") if isinstance(body, dict) else None
            if records is None:  # v2
                records = _path(body, "d.results")
                following = _path(body, "d.__next")
                if records is None and isinstance(_path(body, "d"), list):
                    records = _path(body, "d")
            if not isinstance(records, list):
                raise ConnectorError(
                    ErrorCode.QUERY_FAILED,
                    "the service's answer has no list of records",
                )
        rows = [r for r in records if isinstance(r, dict)]
        if len(rows) != len(records):
            raise ConnectorError(
                ErrorCode.QUERY_FAILED, "the records aren't JSON objects"
            )
        next_url = (
            urljoin(url, str(following))
            if isinstance(following, str) and following
            else None
        )
        return rows, next_url

    def _rows(
        self, table: SourceTable, columns: list[str], limit: int | None
    ) -> Iterator[tuple[Any, ...]]:
        url, params = self._first_url(table, limit)
        seen = 0
        next_url: str | None = url
        query: Mapping[str, str] | None = params
        visited: set[str] = set()
        while next_url:
            if next_url in visited:
                raise ConnectorError(
                    ErrorCode.QUERY_FAILED,
                    "the service's next link points back to a page already read",
                )
            visited.add(next_url)
            records, next_url = self._page(next_url, query)
            query = None  # next links carry their own query
            for record in records:
                if limit is not None and seen >= limit:
                    return
                flat = flatten(record)
                yield tuple(flat.get(c) for c in columns)
                seen += 1
