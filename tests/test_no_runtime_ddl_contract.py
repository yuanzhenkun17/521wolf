from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app", "storage", "ui/backend")
EXCLUDED_RELATIVE_PATHS = {
    Path("storage/postgres/connection.py"),
    Path("storage/shared/database.py"),
}
FORBIDDEN_SNIPPETS = (
    "CREATE TABLE IF NOT EXISTS",
    "CREATE INDEX IF NOT EXISTS",
    "ALTER TABLE ADD COLUMN",
    "ensure_columns(",
)


def test_business_runtime_paths_do_not_create_or_patch_schema() -> None:
    offenders: list[str] = []
    for root_name in SCAN_ROOTS:
        for path in (ROOT / root_name).rglob("*.py"):
            relative = path.relative_to(ROOT)
            if relative in EXCLUDED_RELATIVE_PATHS:
                continue
            text = path.read_text(encoding="utf-8")
            for snippet in FORBIDDEN_SNIPPETS:
                if snippet in text:
                    offenders.append(f"{relative}:{snippet}")

    assert offenders == []
