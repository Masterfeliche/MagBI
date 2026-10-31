"""Give reports their phone layouts from a JSON file, through the API.

    python -m scripts.apply_phone_layouts --login <login.json> [--layouts <file>] [--write]

Without ``--write`` it only reports what it would do. With it, each report's
published definition gets ``pages[].phone`` and nothing else changes. A report
with an unpublished draft keeps it: the draft is saved again with the same phone
layout. When the account can't read a draft (a viewer), nothing is written.

The default file holds the auto-arranged layouts of the 3 Warehouse dashboards
(MAGBI-019 phase 8). They are not applied until the owner approves.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from scripts.qa_gate import _call, sign_in

DEFAULT = Path(__file__).with_name("warehouse_phone_layouts.json")


def with_phone(definition: dict[str, Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    """The definition with each page's phone layout from ``pages`` (matched by page name)."""
    out = copy.deepcopy(definition)
    by_name = {page["name"]: page["phone"] for page in pages}
    for page in out.get("pages", []):
        if page.get("name") in by_name:
            page["phone"] = by_name[page["name"]]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--login", type=Path, required=True, help="JSON file with an editor's email and password")
    parser.add_argument("--layouts", type=Path, default=DEFAULT)
    parser.add_argument("--write", action="store_true", help="save the layouts; without it nothing changes")
    args = parser.parse_args()
    sign_in(args.api, args.login)
    plan = json.loads(args.layouts.read_text(encoding="utf-8"))
    wid = plan["workspace"]
    for rid, item in plan["reports"].items():
        url = f"{args.api}/workspaces/{wid}/reports/{rid}"
        status, report, _secs = _call("GET", url)
        if status != 200:
            raise SystemExit(f"{item['name']}: read failed ({status})")
        draft = report.get("draft")
        if report.get("has_draft") and draft is None:
            raise SystemExit(f"{report['name']}: has a draft this account can't read; publishing would lose it")
        print(f"{report['name']}: {'writing' if args.write else 'would write'} {len(item['pages'])} page(s)"
              f"{' and re-save its draft' if draft is not None else ''}")
        if not args.write:
            continue
        status, body, _secs = _call("PUT", url, {"definition": with_phone(report["definition"], item["pages"])})
        if status != 200:
            raise SystemExit(f"{report['name']}: publish refused ({status}): {body}")
        if draft is not None:
            status, body, _secs = _call("PUT", url, {"draft": with_phone(draft, item["pages"])})
            if status != 200:
                raise SystemExit(f"{report['name']}: draft not saved again ({status}): {body}")


if __name__ == "__main__":
    main()
