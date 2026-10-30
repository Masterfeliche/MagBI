"""Drive the MagBI API end to end: connect to SQL Server, import tables, report.

Standard library only. Typical use against the compose stack (see
docs/guides/sql-server-import.md)::

    python scripts/e2e_import.py --host mssql-test --database magbi_test \\
        --username sa --password-env MSSQL_PASSWORD --trust-server-certificate \\
        --table sales."Order Lines"=order_lines --table dbo.all_types

``--host`` is resolved by the API server, not by this script (inside compose use the
service name). The password is read from an environment variable so it does not
land in shell history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


def call(base: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def must(status: int, body: Any, expected: int, what: str) -> Any:
    if status != expected:
        print(f"FAILED {what}: HTTP {status}\n{json.dumps(body, indent=2)}", file=sys.stderr)
        raise SystemExit(1)
    return body


def parse_table(value: str) -> dict[str, str]:
    source, _, target = value.partition("=")
    schema, _, name = source.partition(".")
    name = name.strip('"')
    if not schema or not name:
        raise argparse.ArgumentTypeError("use SCHEMA.TABLE or SCHEMA.TABLE=target")
    return {"schema": schema, "name": name, "target": target or name}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int)
    p.add_argument("--database", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password-env", default="MSSQL_PASSWORD", help="env var holding the password")
    p.add_argument("--trust-server-certificate", action="store_true")
    p.add_argument("--table", action="append", required=True, type=parse_table)
    p.add_argument("--workspace", default="e2e")
    p.add_argument("--timeout", type=int, default=600, help="seconds to wait for the refresh")
    a = p.parse_args()

    password = os.environ.get(a.password_env)
    if not password:
        raise SystemExit(f"set the {a.password_env} environment variable")
    api = a.api.rstrip("/") + "/api/v1"
    run_id = uuid.uuid4().hex[:6]

    status, body = call(api, "POST", "/workspaces", {"name": f"{a.workspace}-{run_id}"})
    wid = must(status, body, 201, "create workspace")["id"]

    config: dict[str, Any] = {
        "host": a.host,
        "database": a.database,
        "authentication": "sql",
        "username": a.username,
        "password": password,
        "trust_server_certificate": a.trust_server_certificate,
    }
    if a.port:
        config["port"] = a.port

    status, body = call(api, "POST", f"/workspaces/{wid}/connections/test", {"kind": "sqlserver", "config": config})
    result = must(status, body, 200, "test connection")
    if not result["success"]:
        raise SystemExit(f"connection test failed: {result['code']}: {result['error']}")
    print(f"connected: {result['server_version']} ({result['latency_ms']} ms), schemas={result['schemas']}")

    status, body = call(api, "POST", f"/workspaces/{wid}/connections", {"name": "source", "kind": "sqlserver", "config": config})
    cid = must(status, body, 201, "save connection")["id"]
    print(f"saved connection {cid} (password shown as {body['config'].get('password')!r})")

    spec = {"connection_id": cid, "tables": a.table}
    status, body = call(api, "POST", f"/workspaces/{wid}/datasets", {"name": f"import-{run_id}", "import_spec": spec})
    did = must(status, body, 201, "create dataset")["id"]
    print(f"dataset {did}")

    status, body = call(api, "POST", f"/workspaces/{wid}/datasets/{did}/refresh")
    jid = must(status, body, 202, "start refresh")["refresh_id"]
    started = time.monotonic()
    while True:
        status, job = call(api, "GET", f"/workspaces/{wid}/datasets/{did}/refresh/{jid}")
        must(status, job, 200, "poll refresh")
        if job["status"] in ("succeeded", "failed"):
            break
        if time.monotonic() - started > a.timeout:
            raise SystemExit(f"timed out waiting for refresh {jid} (status {job['status']})")
        time.sleep(1)

    if job["status"] == "failed":
        raise SystemExit(f"refresh FAILED: {job['error']}")
    res = job["result"]
    print(f"refresh succeeded: version {job['version']}, {res['total_rows']} rows in {res['seconds']}s")
    for t in res["tables"]:
        print(f"  {t['schema']}.{t['name']} -> {t['target']}: {t['rows']} rows")
    for w in res["warnings"]:
        print(f"  warning: {w}")
    print(f"DATASET_ID={did}")


if __name__ == "__main__":
    main()
