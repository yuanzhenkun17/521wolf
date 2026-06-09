"""Phase 5B Langfuse experiment verification tool.

The verifier is offline-first: by default it only inspects environment shape,
the local benchmark dataset sync plan, and optional local result payloads. Any
real Langfuse operation is opt-in and fail-open so acceptance checks do not
break local benchmark/eval workflows when Langfuse is unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.config import DEFAULT_PATHS, PathConfig
from app.tools.sync_langfuse_datasets import build_sync_plan, sync_langfuse_datasets

LANGFUSE_ENV_KEYS: tuple[str, ...] = (
    "LANGFUSE_TRACING_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_ENVIRONMENT",
    "LANGFUSE_RELEASE",
    "LANGFUSE_SAMPLE_RATE",
    "LANGFUSE_CAPTURE_INPUT_OUTPUT",
)

REQUIRED_PAYLOAD_LINK_FIELDS: tuple[str, ...] = (
    "langfuse_trace_id",
    "langfuse_trace_url",
    "langfuse_dataset_name",
    "langfuse_dataset_item_id",
    "langfuse_experiment_name",
    "langfuse_run_name",
    "langfuse_dataset_run_id",
    "langfuse_dataset_run_item_id",
    "langfuse_experiment_url",
)

PAYLOAD_URL_FIELDS: tuple[str, ...] = (
    "langfuse_trace_url",
    "langfuse_experiment_url",
)

_NESTED_LANGFUSE_FIELD_MAP: dict[str, str] = {
    "trace_id": "langfuse_trace_id",
    "trace_url": "langfuse_trace_url",
    "dataset_name": "langfuse_dataset_name",
    "dataset_item_id": "langfuse_dataset_item_id",
    "experiment_name": "langfuse_experiment_name",
    "run_name": "langfuse_run_name",
    "dataset_run_id": "langfuse_dataset_run_id",
    "dataset_run_item_id": "langfuse_dataset_run_item_id",
    "experiment_url": "langfuse_experiment_url",
    "dataset_run_url": "langfuse_experiment_url",
}

_CHECK_PASS = "pass"
_CHECK_WARNING = "warning"
_CHECK_FAIL = "fail"
_CHECK_SKIPPED = "skipped"
_CHECK_FAIL_OPEN = "fail_open"


def verify_langfuse_experiments(
    *,
    paths: PathConfig | None = None,
    env: Mapping[str, str] | None = None,
    payloads: Iterable[Any] | None = None,
    payload_files: Iterable[str | Path] | None = None,
    apply_sync: bool = False,
    verify_remote: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Build a Phase 5B Langfuse checklist/report.

    Args:
        paths: Benchmark registry roots. Defaults to the project paths.
        env: Environment snapshot to inspect. Defaults to ``os.environ`` and
            does not load ``.env``.
        payloads: In-memory benchmark/eval result payloads to inspect.
        payload_files: JSON files containing one payload or a list of payloads.
        apply_sync: If true, attempts to apply the Langfuse dataset sync plan.
        verify_remote: If true, attempts to verify datasets/items in Langfuse.
        client: Optional fake or real Langfuse client. Supplying it keeps tests
            independent from environment credentials and SDK construction.
    """
    resolved_paths = paths or DEFAULT_PATHS
    env_snapshot = dict(os.environ if env is None else env)
    report: dict[str, Any] = {
        "kind": "langfuse_experiment_verification",
        "schema_version": 1,
        "dry_run": not apply_sync and not verify_remote,
        "mode": {
            "apply_sync": bool(apply_sync),
            "verify_remote": bool(verify_remote),
        },
        "checklist": [],
        "errors": [],
    }

    config_report = inspect_langfuse_config(env_snapshot)
    report["langfuse_config"] = config_report
    _add_check(
        report,
        "langfuse.config",
        "Langfuse configuration is present without exposing keys",
        _CHECK_PASS if config_report["configured"] else _CHECK_WARNING,
        "Langfuse is configured" if config_report["configured"] else "Langfuse is not fully configured",
        {
            "enabled": config_report["enabled"],
            "configured": config_report["configured"],
            "missing": config_report["missing"],
            "base_url": config_report.get("base_url"),
        },
    )

    plan: list[Any] = []
    try:
        plan = build_sync_plan(resolved_paths)
        plan_report = verify_dataset_sync_plan(plan)
    except Exception as exc:  # noqa: BLE001 - local plan validation should report cleanly
        plan_report = {
            "status": _CHECK_FAIL,
            "dataset_count": 0,
            "item_count": 0,
            "datasets": [],
            "invalid_item_ids": [],
            "error": _safe_error(exc),
        }
    report["dataset_sync_plan"] = plan_report
    _add_check(
        report,
        "benchmark.dataset_sync_plan",
        "Benchmark Langfuse dataset sync plan exists",
        _CHECK_PASS if plan_report.get("dataset_count", 0) > 0 and not plan_report.get("error") else _CHECK_FAIL,
        (
            f"{plan_report.get('dataset_count', 0)} datasets / {plan_report.get('item_count', 0)} items"
            if not plan_report.get("error")
            else f"Dataset sync plan failed: {plan_report.get('error')}"
        ),
        {
            "dataset_count": plan_report.get("dataset_count", 0),
            "item_count": plan_report.get("item_count", 0),
        },
    )
    _add_check(
        report,
        "benchmark.dataset_item_ids",
        "Dataset item ids follow evaluation_set_id:seed_set_id:seed",
        _CHECK_PASS if not plan_report.get("invalid_item_ids") else _CHECK_FAIL,
        (
            "All dataset item ids are canonical"
            if not plan_report.get("invalid_item_ids")
            else f"{len(plan_report['invalid_item_ids'])} invalid dataset item ids"
        ),
        {"invalid_item_ids": plan_report.get("invalid_item_ids", [])[:20]},
    )

    loaded_payloads = _load_payload_inputs(payloads=payloads, payload_files=payload_files)
    payload_report = verify_result_payloads(loaded_payloads)
    report["payload_links"] = payload_report
    if payload_report["payload_count"] == 0:
        payload_status = _CHECK_SKIPPED
        payload_message = "No local result payloads were provided"
    elif payload_report["invalid_payloads"]:
        payload_status = _CHECK_FAIL
        payload_message = f"{len(payload_report['invalid_payloads'])} payloads are missing Langfuse link fields"
    else:
        payload_status = _CHECK_PASS
        payload_message = f"{payload_report['payload_count']} payloads include required Langfuse link fields"
    _add_check(
        report,
        "benchmark.result_payload_links",
        "Benchmark/eval result payloads include Langfuse trace, dataset run/item, and experiment links",
        payload_status,
        payload_message,
        {
            "payload_count": payload_report["payload_count"],
            "required_fields": list(REQUIRED_PAYLOAD_LINK_FIELDS),
            "invalid_payloads": payload_report["invalid_payloads"][:20],
        },
    )

    if apply_sync:
        apply_report = _apply_dataset_sync_fail_open(resolved_paths, client=client)
        report["sync_apply"] = apply_report
        _add_check(
            report,
            "langfuse.apply_sync",
            "Apply benchmark datasets/items to Langfuse",
            apply_report["status"],
            apply_report["message"],
            {
                "applied_dataset_count": len(apply_report.get("applied", [])),
                "error": apply_report.get("error"),
            },
        )

    if verify_remote:
        remote_report = _verify_remote_sync_plan_fail_open(plan, client=client)
        report["remote_verification"] = remote_report
        _add_check(
            report,
            "langfuse.remote_verify",
            "Verify benchmark datasets/items in Langfuse",
            remote_report["status"],
            remote_report["message"],
            {
                "checked_dataset_count": remote_report.get("checked_dataset_count", 0),
                "checked_item_count": remote_report.get("checked_item_count", 0),
                "missing_datasets": remote_report.get("missing_datasets", [])[:20],
                "missing_items": remote_report.get("missing_items", [])[:20],
                "errors": remote_report.get("errors", [])[:20],
            },
        )

    _finalize_report(report)
    return report


def inspect_langfuse_config(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return Langfuse config state without exposing keys or secrets."""
    env_snapshot = dict(os.environ if env is None else env)
    enabled = _env_bool(env_snapshot.get("LANGFUSE_TRACING_ENABLED"), default=False)
    public_key_configured = _present(env_snapshot.get("LANGFUSE_PUBLIC_KEY"))
    secret_key_configured = _present(env_snapshot.get("LANGFUSE_SECRET_KEY"))
    base_url_configured = _present(env_snapshot.get("LANGFUSE_BASE_URL"))
    missing = []
    if not enabled:
        missing.append("LANGFUSE_TRACING_ENABLED")
    if not public_key_configured:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not secret_key_configured:
        missing.append("LANGFUSE_SECRET_KEY")
    if not base_url_configured:
        missing.append("LANGFUSE_BASE_URL")

    return {
        "enabled": enabled,
        "configured": enabled and public_key_configured and secret_key_configured and base_url_configured,
        "status": "configured" if enabled and public_key_configured and secret_key_configured and base_url_configured else "incomplete",
        "public_key_configured": public_key_configured,
        "secret_key_configured": secret_key_configured,
        "base_url_configured": base_url_configured,
        "base_url": _safe_base_url(env_snapshot.get("LANGFUSE_BASE_URL")),
        "environment_configured": _present(env_snapshot.get("LANGFUSE_ENVIRONMENT")),
        "release_configured": _present(env_snapshot.get("LANGFUSE_RELEASE")),
        "sample_rate_configured": _present(env_snapshot.get("LANGFUSE_SAMPLE_RATE")),
        "capture_input_output": _env_bool(env_snapshot.get("LANGFUSE_CAPTURE_INPUT_OUTPUT"), default=False),
        "missing": missing,
    }


def verify_dataset_sync_plan(plan: Iterable[Any]) -> dict[str, Any]:
    """Validate dataset plan existence and canonical benchmark item ids."""
    dataset_reports: list[dict[str, Any]] = []
    invalid_item_ids: list[dict[str, Any]] = []
    item_count = 0

    for dataset in plan:
        dataset_dict = _dataset_to_dict(dataset)
        items = list(dataset_dict.get("items") or [])
        dataset_invalid: list[dict[str, Any]] = []
        for raw_item in items:
            item = _item_to_dict(raw_item)
            item_count += 1
            expected = _expected_dataset_item_id(item, dataset_dict)
            item_id = _string_or_none(item.get("item_id") or item.get("id") or item.get("item_name"))
            if expected is None or item_id != expected:
                issue = {
                    "dataset_name": dataset_dict.get("name"),
                    "item_id": item_id,
                    "expected_item_id": expected,
                    "input": _compact_item_identity(item),
                }
                dataset_invalid.append(issue)
                invalid_item_ids.append(issue)
                continue

            item_name = _string_or_none(item.get("item_name"))
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            metadata_name = _string_or_none(metadata.get("item_name") or metadata.get("item_id"))
            if item_name and item_name != expected:
                issue = {
                    "dataset_name": dataset_dict.get("name"),
                    "item_id": item_id,
                    "expected_item_id": expected,
                    "item_name": item_name,
                    "input": _compact_item_identity(item),
                }
                dataset_invalid.append(issue)
                invalid_item_ids.append(issue)
            elif metadata_name and metadata_name != expected:
                issue = {
                    "dataset_name": dataset_dict.get("name"),
                    "item_id": item_id,
                    "expected_item_id": expected,
                    "metadata_item_name": metadata_name,
                    "input": _compact_item_identity(item),
                }
                dataset_invalid.append(issue)
                invalid_item_ids.append(issue)

        dataset_reports.append(
            {
                "name": dataset_dict.get("name"),
                "item_count": len(items),
                "invalid_item_ids": dataset_invalid,
                "metadata": dataset_dict.get("metadata") or {},
            }
        )

    return {
        "status": _CHECK_PASS if dataset_reports and not invalid_item_ids else _CHECK_FAIL,
        "dataset_count": len(dataset_reports),
        "item_count": item_count,
        "datasets": dataset_reports,
        "invalid_item_ids": invalid_item_ids,
    }


def verify_result_payloads(payloads: Iterable[Any] | None) -> dict[str, Any]:
    """Validate local benchmark/eval result payload Langfuse linkage fields."""
    loaded = list(payloads or [])
    payload_reports = []
    invalid_payloads = []
    for index, payload in enumerate(loaded):
        payload_report = verify_result_payload(payload, source=f"payload[{index}]")
        payload_reports.append(payload_report)
        if payload_report["status"] != _CHECK_PASS:
            invalid_payloads.append(
                {
                    "source": payload_report["source"],
                    "missing_fields": payload_report["missing_fields"],
                    "invalid_urls": payload_report["invalid_urls"],
                    "invalid_item_ids": payload_report["invalid_item_ids"],
                }
            )

    return {
        "status": _CHECK_PASS if loaded and not invalid_payloads else (_CHECK_SKIPPED if not loaded else _CHECK_FAIL),
        "payload_count": len(loaded),
        "required_fields": list(REQUIRED_PAYLOAD_LINK_FIELDS),
        "payloads": payload_reports,
        "invalid_payloads": invalid_payloads,
    }


def verify_result_payload(payload: Any, *, source: str = "payload") -> dict[str, Any]:
    """Validate one benchmark/eval result payload."""
    link_records: list[dict[str, Any]] = []
    for record in _iter_dict_records(payload):
        normalized = _normalized_langfuse_fields(record)
        if any(_present(value) for value in normalized.values()):
            link_records.append({**record, "__langfuse_fields__": normalized})

    present_fields = {
        field
        for record in link_records
        for field, value in record["__langfuse_fields__"].items()
        if _present(value)
    }
    missing_fields = [field for field in REQUIRED_PAYLOAD_LINK_FIELDS if field not in present_fields]
    invalid_urls = _invalid_payload_urls(link_records)
    invalid_item_ids = _invalid_payload_item_ids(link_records)
    status = _CHECK_PASS if link_records and not missing_fields and not invalid_urls and not invalid_item_ids else _CHECK_FAIL
    return {
        "source": source,
        "status": status,
        "link_record_count": len(link_records),
        "present_fields": sorted(present_fields),
        "missing_fields": missing_fields,
        "invalid_urls": invalid_urls,
        "invalid_item_ids": invalid_item_ids,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Phase 5B Langfuse benchmark experiment integration.")
    parser.add_argument("--root", type=Path, default=None, help="Project/data root for benchmark specs.")
    parser.add_argument(
        "--payload-file",
        action="append",
        default=[],
        help="JSON benchmark/eval result payload file. Can be passed multiple times.",
    )
    parser.add_argument(
        "--apply-sync",
        action="store_true",
        help="Apply benchmark dataset sync to Langfuse. Fail-open on Langfuse errors.",
    )
    parser.add_argument(
        "--verify-remote",
        action="store_true",
        help="Verify benchmark datasets/items against Langfuse. Fail-open on Langfuse errors.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation for the report.")
    parser.add_argument("--output", type=Path, default=None, help="Write the JSON report to this file.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the verification report contains fail or fail_open checks.",
    )
    parser.add_argument(
        "--compare-report",
        type=Path,
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Offline compare two verification report JSON files and exit without running verification.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.compare_report is not None:
        old_report = json.loads(args.compare_report[0].read_text(encoding="utf-8"))
        new_report = json.loads(args.compare_report[1].read_text(encoding="utf-8"))
        comparison = compare_verification_reports(old_report, new_report)
        _emit_json_report(comparison, output=args.output, indent=args.indent)
        return 0

    paths = PathConfig(root=args.root) if args.root is not None else DEFAULT_PATHS
    report = verify_langfuse_experiments(
        paths=paths,
        payload_files=args.payload_file,
        apply_sync=bool(args.apply_sync),
        verify_remote=bool(args.verify_remote),
    )
    _emit_json_report(report, output=args.output, indent=args.indent)
    if args.strict and report.get("status") in {_CHECK_FAIL, _CHECK_FAIL_OPEN}:
        return 1
    return 0


def compare_verification_reports(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Compare checklist status changes between two verification reports."""
    old_checks = _checks_by_id(old)
    new_checks = _checks_by_id(new)
    old_ids = set(old_checks)
    new_ids = set(new_checks)

    added_checks = [
        _comparison_check_snapshot(check_id, new_checks[check_id])
        for check_id in sorted(new_ids - old_ids)
    ]
    removed_checks = [
        _comparison_check_snapshot(check_id, old_checks[check_id])
        for check_id in sorted(old_ids - new_ids)
    ]
    changed_checks = []
    for check_id in sorted(old_ids & new_ids):
        old_check = old_checks[check_id]
        new_check = new_checks[check_id]
        old_status = old_check.get("status")
        new_status = new_check.get("status")
        if old_status == new_status:
            continue
        changed_checks.append(
            {
                "id": check_id,
                "label": new_check.get("label") or old_check.get("label"),
                "old_status": old_status,
                "new_status": new_status,
                "old_message": old_check.get("message"),
                "new_message": new_check.get("message"),
            }
        )

    return {
        "kind": "langfuse_experiment_verification_comparison",
        "schema_version": 1,
        "old_status": old.get("status"),
        "new_status": new.get("status"),
        "added_checks": added_checks,
        "removed_checks": removed_checks,
        "changed_checks": changed_checks,
        "summary_delta": _summary_delta(old.get("summary"), new.get("summary")),
    }


def _load_payload_inputs(
    *,
    payloads: Iterable[Any] | None,
    payload_files: Iterable[str | Path] | None,
) -> list[Any]:
    result = list(payloads or [])
    for path in payload_files or []:
        payload_path = Path(path)
        raw = json.loads(payload_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            result.extend(raw)
        else:
            result.append(raw)
    return result


def _emit_json_report(report: Mapping[str, Any], *, output: Path | None, indent: int) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=indent, default=str)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _checks_by_id(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    checks: dict[str, Mapping[str, Any]] = {}
    for index, raw_check in enumerate(report.get("checklist", []) or []):
        if not isinstance(raw_check, Mapping):
            continue
        check_id = _string_or_none(raw_check.get("id")) or f"check[{index}]"
        checks[check_id] = raw_check
    return checks


def _comparison_check_snapshot(check_id: str, check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": check.get("label"),
        "status": check.get("status"),
        "message": check.get("message"),
    }


def _summary_delta(old_summary: Any, new_summary: Any) -> dict[str, int]:
    old_map = old_summary if isinstance(old_summary, Mapping) else {}
    new_map = new_summary if isinstance(new_summary, Mapping) else {}
    numeric_keys = {
        key
        for key, value in [*old_map.items(), *new_map.items()]
        if isinstance(value, int) and not isinstance(value, bool)
    }
    return {
        str(key): int(new_map.get(key, 0) or 0) - int(old_map.get(key, 0) or 0)
        for key in sorted(numeric_keys)
    }


def _apply_dataset_sync_fail_open(paths: PathConfig, *, client: Any | None) -> dict[str, Any]:
    try:
        sync_report = sync_langfuse_datasets(apply=True, paths=paths, client=client)
    except Exception as exc:  # noqa: BLE001 - real Langfuse writes are fail-open
        return {
            "status": _CHECK_FAIL_OPEN,
            "message": f"Langfuse dataset sync failed open: {_safe_error(exc)}",
            "error": _safe_error(exc),
            "applied": [],
        }

    if sync_report.get("error"):
        return {
            "status": _CHECK_FAIL_OPEN,
            "message": str(sync_report.get("error")),
            "error": str(sync_report.get("error")),
            "applied": sync_report.get("applied", []),
            "raw": _compact_sync_apply_report(sync_report),
        }
    return {
        "status": _CHECK_PASS,
        "message": f"Applied {len(sync_report.get('applied', []))} datasets to Langfuse",
        "applied": sync_report.get("applied", []),
        "raw": _compact_sync_apply_report(sync_report),
    }


def _verify_remote_sync_plan_fail_open(plan: Iterable[Any], *, client: Any | None) -> dict[str, Any]:
    resolved_client = client
    if resolved_client is None:
        try:
            from app.services.observability import get_langfuse_client

            resolved_client = get_langfuse_client()
        except Exception as exc:  # noqa: BLE001 - SDK construction is fail-open
            return {
                "status": _CHECK_FAIL_OPEN,
                "message": f"Langfuse client initialization failed open: {_safe_error(exc)}",
                "checked_dataset_count": 0,
                "checked_item_count": 0,
                "missing_datasets": [],
                "missing_items": [],
                "errors": [_safe_error(exc)],
            }

    if resolved_client is None:
        return {
            "status": _CHECK_FAIL_OPEN,
            "message": "Langfuse client is unavailable; remote verification skipped fail-open",
            "checked_dataset_count": 0,
            "checked_item_count": 0,
            "missing_datasets": [],
            "missing_items": [],
            "errors": [],
        }

    checked_dataset_count = 0
    checked_item_count = 0
    missing_datasets: list[str] = []
    missing_items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for dataset in plan:
        dataset_dict = _dataset_to_dict(dataset)
        dataset_name = _string_or_none(dataset_dict.get("name"))
        if not dataset_name:
            continue
        try:
            remote_dataset = _get_remote_dataset(
                resolved_client,
                dataset_name,
                item_count=len(dataset_dict.get("items") or []),
            )
            checked_dataset_count += 1
        except Exception as exc:  # noqa: BLE001 - Langfuse reads are fail-open
            errors.append({"dataset_name": dataset_name, "error": _safe_error(exc)})
            continue
        if remote_dataset is None:
            missing_datasets.append(dataset_name)
            continue
        remote_items = list(_iter_remote_dataset_items(remote_dataset))
        for raw_item in dataset_dict.get("items") or []:
            item = _item_to_dict(raw_item)
            item_id = _string_or_none(item.get("item_id") or item.get("id") or item.get("item_name"))
            if not item_id:
                continue
            checked_item_count += 1
            if not _remote_dataset_item_exists(remote_items, item_id):
                missing_items.append({"dataset_name": dataset_name, "item_id": item_id})

    if errors:
        status = _CHECK_FAIL_OPEN
        message = f"Remote verification failed open for {len(errors)} datasets"
    elif missing_datasets or missing_items:
        status = _CHECK_FAIL
        message = (
            f"Remote verification found {len(missing_datasets)} missing datasets "
            f"and {len(missing_items)} missing items"
        )
    else:
        status = _CHECK_PASS
        message = f"Remote verification checked {checked_dataset_count} datasets / {checked_item_count} items"

    return {
        "status": status,
        "message": message,
        "checked_dataset_count": checked_dataset_count,
        "checked_item_count": checked_item_count,
        "missing_datasets": missing_datasets,
        "missing_items": missing_items,
        "errors": errors,
    }


def _get_remote_dataset(client: Any, dataset_name: str, *, item_count: int) -> Any | None:
    get_dataset = getattr(client, "get_dataset", None)
    if not callable(get_dataset):
        raise RuntimeError("Langfuse client does not expose get_dataset")
    page_size = max(1, min(max(item_count, 1), 500))
    try:
        return get_dataset(dataset_name, fetch_items_page_size=page_size)
    except TypeError:
        return get_dataset(dataset_name)


def _iter_remote_dataset_items(dataset: Any) -> Iterable[Any]:
    if dataset is None:
        return []
    items = _value_attr(dataset, "items")
    if items is None:
        return []
    try:
        return list(items)
    except TypeError:
        return []


def _remote_dataset_item_exists(remote_items: Iterable[Any], item_id: str) -> bool:
    for item in remote_items:
        if _string_attr(item, "id", "item_id", "itemId", "name") == item_id:
            return True
        metadata = _value_attr(item, "metadata")
        if isinstance(metadata, dict) and _string_or_none(metadata.get("item_name") or metadata.get("item_id")) == item_id:
            return True
    return False


def _dataset_to_dict(dataset: Any) -> dict[str, Any]:
    if isinstance(dataset, dict):
        return dict(dataset)
    to_dict = getattr(dataset, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, dict):
            return value
    result: dict[str, Any] = {}
    for key in ("name", "description", "metadata", "items"):
        if hasattr(dataset, key):
            result[key] = getattr(dataset, key)
    return result


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, dict):
            return value
    result: dict[str, Any] = {}
    for key in ("dataset_name", "item_id", "item_name", "input", "expected_output", "metadata"):
        if hasattr(item, key):
            result[key] = getattr(item, key)
    return result


def _expected_dataset_item_id(item: dict[str, Any], dataset: dict[str, Any]) -> str | None:
    input_payload = item.get("input") if isinstance(item.get("input"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    evaluation_set_id = _string_or_none(
        _first_present(
            input_payload.get("evaluation_set_id"),
            metadata.get("evaluation_set_id"),
            dataset.get("name"),
        )
    )
    seed_set_id = _string_or_none(_first_present(input_payload.get("seed_set_id"), metadata.get("seed_set_id")))
    seed = _string_or_none(_first_present(input_payload.get("seed"), metadata.get("seed")))
    if not evaluation_set_id or not seed_set_id or seed is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed}"


def _compact_item_identity(item: dict[str, Any]) -> dict[str, Any]:
    input_payload = item.get("input") if isinstance(item.get("input"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "evaluation_set_id": _first_present(input_payload.get("evaluation_set_id"), metadata.get("evaluation_set_id")),
        "seed_set_id": _first_present(input_payload.get("seed_set_id"), metadata.get("seed_set_id")),
        "seed": _first_present(input_payload.get("seed"), metadata.get("seed")),
    }


def _iter_dict_records(value: Any, *, max_records: int = 2000) -> Iterable[dict[str, Any]]:
    stack: list[Any] = [value]
    yielded = 0
    while stack and yielded < max_records:
        current = stack.pop()
        if isinstance(current, dict):
            yielded += 1
            yield current
            for nested in current.values():
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _normalized_langfuse_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = {key: record.get(key) for key in REQUIRED_PAYLOAD_LINK_FIELDS if key in record}
    _merge_nested_langfuse(fields, record.get("langfuse"))
    observability = record.get("observability")
    if isinstance(observability, dict):
        _merge_nested_langfuse(fields, observability.get("langfuse"))
    return fields


def _merge_nested_langfuse(fields: dict[str, Any], nested: Any) -> None:
    if not isinstance(nested, dict):
        return
    for source_key, target_key in _NESTED_LANGFUSE_FIELD_MAP.items():
        value = nested.get(source_key)
        if _present(value) and not _present(fields.get(target_key)):
            fields[target_key] = value


def _invalid_payload_urls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalid = []
    for index, record in enumerate(records):
        fields = record["__langfuse_fields__"]
        for field in PAYLOAD_URL_FIELDS:
            value = _string_or_none(fields.get(field))
            if value and not _looks_like_url(value):
                invalid.append({"record_index": index, "field": field, "value": value})
    return invalid


def _invalid_payload_item_ids(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalid = []
    for index, record in enumerate(records):
        fields = record["__langfuse_fields__"]
        item_id = _string_or_none(fields.get("langfuse_dataset_item_id"))
        if not item_id:
            continue
        evaluation_set_id = _string_or_none(
            _first_present(record.get("evaluation_set_id"), fields.get("langfuse_dataset_name"))
        )
        seed_set_id = _string_or_none(record.get("seed_set_id"))
        seed = _string_or_none(record.get("seed"))
        if not evaluation_set_id or not seed_set_id or seed is None:
            continue
        expected = f"{evaluation_set_id}:{seed_set_id}:{seed}"
        if item_id != expected:
            invalid.append(
                {
                    "record_index": index,
                    "item_id": item_id,
                    "expected_item_id": expected,
                    "evaluation_set_id": evaluation_set_id,
                    "seed_set_id": seed_set_id,
                    "seed": seed,
                }
            )
    return invalid


def _looks_like_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _safe_base_url(value: Any) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<configured>"
    if not parsed.scheme or not parsed.netloc:
        return "<configured>"
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _safe_error(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text.replace("\n", " ")[:500]


def _compact_sync_apply_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "dry_run": report.get("dry_run"),
        "dataset_count": report.get("dataset_count"),
        "item_count": report.get("item_count"),
        "applied": report.get("applied", []),
        "error": report.get("error"),
    }


def _add_check(
    report: dict[str, Any],
    check_id: str,
    label: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    report.setdefault("checklist", []).append(
        {
            "id": check_id,
            "label": label,
            "status": status,
            "passed": status == _CHECK_PASS,
            "message": message,
            "details": details or {},
        }
    )


def _finalize_report(report: dict[str, Any]) -> None:
    counts = Counter(check.get("status") for check in report.get("checklist", []))
    failed_checks = _check_ids_with_status(report, _CHECK_FAIL)
    warning_checks = _check_ids_with_status(report, _CHECK_WARNING)
    fail_open_checks = _check_ids_with_status(report, _CHECK_FAIL_OPEN)
    if counts[_CHECK_FAIL]:
        status = _CHECK_FAIL
    elif counts[_CHECK_FAIL_OPEN]:
        status = _CHECK_FAIL_OPEN
    elif counts[_CHECK_WARNING]:
        status = _CHECK_WARNING
    else:
        status = _CHECK_PASS
    report["status"] = status
    report["summary"] = {
        "check_count": len(report.get("checklist", [])),
        "passed": counts[_CHECK_PASS],
        "warnings": counts[_CHECK_WARNING],
        "failed": counts[_CHECK_FAIL],
        "fail_open": counts[_CHECK_FAIL_OPEN],
        "skipped": counts[_CHECK_SKIPPED],
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "fail_open_checks": fail_open_checks,
    }


def _check_ids_with_status(report: Mapping[str, Any], status: str) -> list[str]:
    return [
        str(check.get("id"))
        for check in report.get("checklist", [])
        if isinstance(check, Mapping) and check.get("status") == status and check.get("id") is not None
    ]


def _env_bool(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    return text if text != "" else None


def _first_present(*values: Any) -> Any | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _value_attr(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _string_attr(value: Any, *names: str) -> str | None:
    for name in names:
        text = _string_or_none(_value_attr(value, name))
        if text:
            return text
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
