"""Sync built-in benchmark seed sets into Langfuse datasets.

The command is dry-run by default so local development and tests do not need a
Langfuse SDK or server. Use ``--apply`` to write datasets/items through the
optional observability client.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from app.config import PathConfig
from app.lib.benchmark_spec import (
    BenchmarkSpec,
    BenchmarkSeedSet,
    benchmark_config_hash,
    benchmark_seed_set_summary,
    benchmark_spec_summary,
    list_benchmark_specs,
    materialize_benchmark_spec,
)


@dataclass(frozen=True)
class LangfuseDatasetItemPlan:
    dataset_name: str
    item_id: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    metadata: dict[str, Any]

    @property
    def item_name(self) -> str:
        return self.item_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "input": self.input,
            "expected_output": self.expected_output,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class LangfuseDatasetPlan:
    name: str
    description: str
    metadata: dict[str, Any]
    items: list[LangfuseDatasetItemPlan]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }


def build_sync_plan(paths: PathConfig | None = None) -> list[LangfuseDatasetPlan]:
    """Build the deterministic Langfuse dataset sync plan."""
    plans: list[LangfuseDatasetPlan] = []
    for spec in list_benchmark_specs(paths):
        materialized, seed_set = materialize_benchmark_spec(spec, paths=paths)
        seeds = _spec_seeds(materialized)
        dataset_name = materialized.evaluation_set_id
        summary = benchmark_spec_summary(materialized, seed_set)
        metadata = {
            "source": "521wolf.benchmark_spec",
            "benchmark_id": materialized.id,
            "benchmark_version": materialized.version,
            "evaluation_set_id": dataset_name,
            "target_type": materialized.target_type,
            "seed_set_id": materialized.seed_set_id,
            "game_count": materialized.game_count,
            "config_hash": benchmark_config_hash(materialized),
            "summary": summary,
        }
        if seed_set is not None:
            metadata["seed_set"] = benchmark_seed_set_summary(seed_set)

        items = [
            build_dataset_item_plan(
                spec=materialized,
                seed_set=seed_set,
                dataset_name=dataset_name,
                seed=seed,
                index=index,
            )
            for index, seed in enumerate(seeds)
        ]
        plans.append(
            LangfuseDatasetPlan(
                name=dataset_name,
                description=materialized.description or materialized.name or dataset_name,
                metadata=metadata,
                items=items,
            )
        )
    return plans


def build_dataset_item_plan(
    *,
    spec: BenchmarkSpec,
    seed_set: BenchmarkSeedSet | None,
    dataset_name: str,
    seed: int,
    index: int,
) -> LangfuseDatasetItemPlan:
    seed_set_id = seed_set.id if seed_set is not None else spec.seed_set_id
    item_id = f"{spec.evaluation_set_id}:{seed_set_id}:{seed}"
    return LangfuseDatasetItemPlan(
        dataset_name=dataset_name,
        item_id=item_id,
        input={
            "evaluation_set_id": spec.evaluation_set_id,
            "benchmark_id": spec.id,
            "benchmark_version": spec.version,
            "target_type": spec.target_type,
            "roles": list(spec.roles),
            "seed_set_id": seed_set_id,
            "seed": seed,
            "index": index,
            "max_days": spec.max_days,
            "paired_seed": spec.paired_seed,
        },
        expected_output={
            "metrics": spec.metrics.model_dump(mode="json"),
            "gates": spec.gates.model_dump(mode="json"),
            "judge": spec.judge.model_dump(mode="json"),
        },
        metadata={
            "source": "521wolf.benchmark_seed",
            "evaluation_set_id": spec.evaluation_set_id,
            "benchmark_id": spec.id,
            "benchmark_version": spec.version,
            "seed_set_id": seed_set_id,
            "seed": seed,
            "item_name": item_id,
            "config_hash": benchmark_config_hash(spec),
        },
    )


def sync_langfuse_datasets(
    *,
    apply: bool = False,
    paths: PathConfig | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    plan = build_sync_plan(paths)
    report: dict[str, Any] = {
        "dry_run": not apply,
        "dataset_count": len(plan),
        "item_count": sum(len(dataset.items) for dataset in plan),
        "datasets": [dataset.to_dict() for dataset in plan],
        "applied": [],
    }
    if not apply:
        return report

    resolved_client = client if client is not None else _get_langfuse_client()
    if resolved_client is None:
        report["error"] = (
            "Langfuse is not configured. Set LANGFUSE_TRACING_ENABLED=true, "
            "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL, "
            "or run with --dry-run."
        )
        return report

    for dataset in plan:
        _create_dataset(resolved_client, dataset)
        applied_items = []
        for item in dataset.items:
            _create_dataset_item(resolved_client, item)
            applied_items.append(item.item_id)
        report["applied"].append(
            {
                "name": dataset.name,
                "item_count": len(applied_items),
                "item_ids": applied_items,
            }
        )
    return report


def _get_langfuse_client() -> Any | None:
    from app.services.observability import get_langfuse_client

    return get_langfuse_client()


def _create_dataset(client: Any, dataset: LangfuseDatasetPlan) -> None:
    create_dataset = getattr(client, "create_dataset", None)
    if not callable(create_dataset):
        raise RuntimeError("Langfuse client does not expose create_dataset")
    try:
        create_dataset(
            name=dataset.name,
            description=dataset.description,
            metadata=dataset.metadata,
        )
    except Exception as exc:  # noqa: BLE001 - existing datasets are acceptable
        if not _looks_like_already_exists(exc):
            raise


def _create_dataset_item(client: Any, item: LangfuseDatasetItemPlan) -> None:
    create_item = getattr(client, "create_dataset_item", None)
    if not callable(create_item):
        raise RuntimeError("Langfuse client does not expose create_dataset_item")
    create_item(
        dataset_name=item.dataset_name,
        id=item.item_id,
        input=item.input,
        expected_output=item.expected_output,
        metadata=item.metadata,
    )


def _looks_like_already_exists(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("already exists", "conflict", "duplicate", "409"))


def _spec_seeds(spec: BenchmarkSpec) -> list[int]:
    if spec.seeds is not None:
        return list(spec.seeds[: spec.game_count])
    return [spec.seed_start + index for index in range(spec.game_count)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync benchmark specs into Langfuse datasets.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the sync plan without writing Langfuse.")
    mode.add_argument("--apply", action="store_true", help="Write datasets and dataset items to Langfuse.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = sync_langfuse_datasets(apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.apply and report.get("error"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
