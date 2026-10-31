"""Store frame colours as theme token names in a workspace's saved reports.

Frames saved before theming hold literal colours ("#F8FAFC"), which a theme
change cannot restyle. This swaps every colour that equals a surface token for
the token's name ("frame") and records the theme id. Under the same theme the
report looks exactly the same. Dry run unless ``--apply``.

    python -m scripts.theme_tokens --workspace <id> [--report <id> ...] [--apply]
"""

from __future__ import annotations

import argparse
import copy

from magbi.themes import DEFAULT_THEME, load_theme, tokenise_definition
from scripts.magbi_lib import Api


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--report", action="append", help="only these report ids (default: every report)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    api = Api(args.api)
    for item in api.get(f"/workspaces/{args.workspace}/reports"):
        if args.report and item["id"] not in args.report:
            continue
        report = api.get(f"/workspaces/{args.workspace}/reports/{item['id']}")
        definition = copy.deepcopy(report["definition"])
        theme = load_theme(definition.get("theme", {}).get("id", DEFAULT_THEME))
        changed = tokenise_definition(definition, theme)
        print(f"{report['name']}: {changed} change(s)")
        if changed and args.apply:
            api.put(
                f"/workspaces/{args.workspace}/reports/{item['id']}",
                {"definition": definition, "is_published": report["is_published"]},
            )


if __name__ == "__main__":
    main()
