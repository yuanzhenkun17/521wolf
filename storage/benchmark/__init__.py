"""Benchmark persistence repositories."""

from __future__ import annotations

from storage.benchmark.saved_view_repo import BenchmarkSavedViewRepository
from storage.benchmark.snapshot_repo import BenchmarkSnapshotRepository

__all__ = [
    "BenchmarkSavedViewRepository",
    "BenchmarkSnapshotRepository",
]
