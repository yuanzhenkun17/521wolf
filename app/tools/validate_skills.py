"""Validate Markdown skill manifests.

Usage:
    uv run python -m app.tools.validate_skills <skill_dir>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.lib.version import validate_skill_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate skill markdown manifests.")
    parser.add_argument("skill_dir", help="Directory containing .md skill files")
    parser.add_argument("--role", help="Require every skill to declare this role")
    args = parser.parse_args(argv)

    issues = validate_skill_dir(Path(args.skill_dir), expected_role=args.role)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
