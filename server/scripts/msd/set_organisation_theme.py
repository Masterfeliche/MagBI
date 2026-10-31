"""Store MSD's organisation theme: ERP Native (Enterprise Light), light only, locked.

Run once per MagBI instance that serves MSD. Re-running updates the theme in place.

    python -m scripts.msd.set_organisation_theme [--api URL] [--token TOKEN]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.magbi_lib import Api

THEME = Path(__file__).with_name("organisation-theme.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--token", help="a platform admin's token (not needed on a dev server)")
    args = parser.parse_args()
    api = Api(args.api, args.token)
    body = json.loads(THEME.read_text(encoding="utf-8"))
    existing = next((theme for theme in api.get("/organisation/themes") if theme["name"] == body["name"]), None)
    saved = api.put(f"/organisation/themes/{existing['id']}", body) if existing else api.post("/organisation/themes", body)
    print(f"{saved['name']}: version {saved['version']}, default={saved['isDefault']}, locked={saved['locked']}")


if __name__ == "__main__":
    main()
