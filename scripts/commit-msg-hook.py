#!/usr/bin/env python3
"""Git commit-msg hook — enforces single-sentence conventional commits.

Install: copy to .git/hooks/commit-msg (no extension) and chmod +x.
"""
import re
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        msg = f.readline().strip()

    if not msg:
        sys.exit(0)

    if len(msg) > 72:
        print("Error: Commit message exceeds 72 chars")
        sys.exit(1)

    pattern = (
        r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
        r"(\(.+\))?: [a-z].+"
    )
    if not re.match(pattern, msg):
        print(
            "Error: Must follow conventional commits "
            "(e.g., 'feat(scope): description')"
        )
        sys.exit(1)

    description = re.sub(r"^[^:]+: ", "", msg)
    if re.search(r"[.;:]", description):
        print(
            "Error: Commit description must be a single sentence (no ., ;, :)"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
