"""Clean all old data files for a fresh start."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"


def clean_all() -> None:
    """Delete wolf.db, evolution.db, data/registry/*, and runs/*."""
    targets = [
        (DATA_DIR / "wolf.db", "file"),
        (DATA_DIR / "evolution.db", "file"),
        (DATA_DIR / "registry", "dir"),
        (RUNS_DIR, "dir"),
    ]

    for path, kind in targets:
        if not path.exists():
            print(f"  SKIP  {path} (not found)")
            continue

        if kind == "dir":
            shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            print(f"  CLEAN {path}/ (contents removed)")
        else:
            try:
                path.unlink()
                print(f"  DELETE {path}")
            except PermissionError:
                if path.suffix == ".db":
                    _reset_sqlite(path)
                    print(f"  RESET  {path} (locked; dropped all tables)")
                else:
                    raise

    # Also clean WAL/SHM companions if present
    for suffix in ("-shm", "-wal"):
        for db_name in ("wolf.db", "evolution.db"):
            companion = DATA_DIR / f"{db_name}{suffix}"
            if companion.exists():
                try:
                    companion.unlink()
                    print(f"  DELETE {companion}")
                except PermissionError:
                    print(f"  SKIP  {companion} (locked)")

    print("\nDone.")


def _reset_sqlite(path: Path) -> None:
    """Drop every user table when Windows refuses to unlink a locked DB file."""
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (name,) in rows:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    clean_all()
