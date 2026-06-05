#!/usr/bin/env python3
"""Bootstrap the version registry with empty baselines for all roles.

This is the canonical bootstrap path for initializing the registry.
It creates explicit empty baselines for every role in the game engine,
so that the evolution pipeline has a starting point.

Usage (from project root):
    uv run python scripts/bootstrap_registry.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.common.paths import DEFAULT as DEFAULT_PATHS  # noqa: E402
from agent.learning.evolution.registry import VersionRegistry  # noqa: E402


async def async_main() -> None:
    registry = VersionRegistry(DEFAULT_PATHS.registry_dir)
    print("Bootstrapping registry with empty baselines for all roles ...\n")
    await registry.ensure_default_baselines()

    print("=" * 60)
    print("Registry baselines after bootstrap:")
    print("=" * 60)
    for role in sorted(registry.list_roles()):
        baseline = registry.get_baseline(role)
        versions = [v.version_id for v in registry.list_versions(role)]
        print(f"  {role:20s}  baseline={baseline}  versions={versions}")
    print("\nDone.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
