"""Build a local manifest of Langfuse and UI deep links from JSON payloads.

The builder is intentionally offline-only. It inspects benchmark/eval/review/
verification/annotation queue JSON payloads already on disk and never imports
Langfuse clients or storage adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from app.util.redaction import redact


SCHEMA_VERSION = "langfuse_link_manifest_v1"
DEFAULT_UI_BASE_URL = "/"

SENSITIVE_KEY_PARTS = (
    "private_reasoning",
    "hidden_reasoning",
    "chain_of_thought",
    "scratchpad",
    "prompt",
    "raw_messages",
    "messages",
    "raw_output",
    "completion",
)

IDENTITY_KEYS = (
    "game_id",
    "history_game_id",
    "batch_id",
    "result_batch_id",
    "seed",
    "source_run_id",
    "run_id",
    "report_id",
    "benchmark_id",
    "benchmark_version",
    "evaluation_set_id",
    "seed_set_id",
    "target_type",
    "target_role",
    "target_version_id",
    "model_id",
    "model_config_hash",
)

METADATA_KEYS = (
    "annotation_scope",
    "priority_score",
    "reason_codes",
    "status",
    "winner",
    "rankable",
    "rankable_reason",
    "source_run_id",
    "run_id",
    "report_id",
    "benchmark_id",
    "benchmark_version",
    "evaluation_set_id",
    "seed_set_id",
    "target_type",
    "target_role",
    "target_version_id",
    "model_id",
    "model_config_hash",
    "langfuse_dataset_name",
    "langfuse_dataset_item_id",
    "langfuse_experiment_name",
    "langfuse_run_name",
    "langfuse_dataset_run_id",
    "langfuse_dataset_run_item_id",
)

LANGFUSE_METADATA_KEYS = (
    "dataset_name",
    "dataset_item_id",
    "experiment_name",
    "run_name",
    "dataset_run_id",
    "dataset_run_item_id",
)

TRACE_ID_ALIASES = (
    "langfuse_trace_id",
    "trace_id",
    "langfuse.trace_id",
    "metadata.langfuse_trace_id",
    "metadata.trace_id",
    "metadata.langfuse.trace_id",
)
TRACE_URL_ALIASES = (
    "langfuse_trace_url",
    "trace_url",
    "langfuse.trace_url",
    "metadata.langfuse_trace_url",
    "metadata.trace_url",
    "metadata.langfuse.trace_url",
)
EXPERIMENT_URL_ALIASES = (
    "langfuse_experiment_url",
    "experiment_url",
    "dataset_run_url",
    "langfuse.experiment_url",
    "langfuse.dataset_run_url",
    "metadata.langfuse_experiment_url",
    "metadata.experiment_url",
    "metadata.dataset_run_url",
    "metadata.langfuse.experiment_url",
    "metadata.langfuse.dataset_run_url",
)
LOCAL_URL_ALIASES = (
    "local_url",
    "ui_deep_link",
    "metadata.local_url",
    "metadata.ui_deep_link",
)


def build_link_manifest(payloads: Iterable[Any] | Any, ui_base_url: str = DEFAULT_UI_BASE_URL) -> dict[str, Any]:
    """Extract Langfuse and local UI links into a deterministic manifest."""

    records: dict[str, dict[str, Any]] = {}
    for payload_index, payload in enumerate(_coerce_payloads(payloads)):
        root_context = _context_from_data(_as_mapping(payload), {}, child_key=None)
        for item in _extract_items(
            payload,
            context=root_context,
            ui_base_url=ui_base_url,
            path=f"payload[{payload_index}]",
        ):
            key = _dedupe_key(item)
            if key in records:
                _merge_item(records[key], item)
            else:
                records[key] = item

    items = list(records.values())
    items.sort(key=_sort_key)
    for item in items:
        item["id"] = _stable_item_id(item)

    missing_links = [_missing_entry(item) for item in items if _missing_reasons(item)]
    return {
        "schema_version": SCHEMA_VERSION,
        "item_count": len(items),
        "items": items,
        "missing_links": missing_links,
    }


def load_json(path: str | Path) -> Any:
    """Load one UTF-8 JSON payload from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline Langfuse/local link manifest.")
    parser.add_argument("inputs", nargs="+", help="Input benchmark/eval/review/verification JSON payload(s).")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write manifest JSON to this file.")
    parser.add_argument("--ui-base-url", default=DEFAULT_UI_BASE_URL, help="Base URL for generated local UI links.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation for emitted manifest.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payloads = [load_json(path) for path in args.inputs]
    manifest = build_link_manifest(payloads, ui_base_url=args.ui_base_url)
    output = json.dumps(manifest, ensure_ascii=False, indent=args.indent, sort_keys=True, default=str)
    if args.output is None:
        print(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0


def _extract_items(value: Any, *, context: dict[str, Any], ui_base_url: str, path: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for index, child in enumerate(value):
            items.extend(
                _extract_items(
                    child,
                    context=context,
                    ui_base_url=ui_base_url,
                    path=f"{path}[{index}]",
                )
            )
        return items

    data = _as_mapping(value)
    if not data:
        return []

    current_context = _context_from_data(data, context, child_key=None)
    item = _item_from_data(data, context=current_context, ui_base_url=ui_base_url, path=path)
    items = [item] if item is not None else []

    for raw_key, child in data.items():
        key = str(raw_key)
        if _is_sensitive_key(key) or key in {"metadata"}:
            continue
        if not isinstance(child, (Mapping, list)):
            continue
        child_context = _context_from_data(data, current_context, child_key=key)
        items.extend(
            _extract_items(
                child,
                context=child_context,
                ui_base_url=ui_base_url,
                path=f"{path}.{key}",
            )
        )
    return items


def _item_from_data(
    data: dict[str, Any],
    *,
    context: dict[str, Any],
    ui_base_url: str,
    path: str,
) -> dict[str, Any] | None:
    identity = _identity_from_data(data, context)
    trace_id = _first_text(*(_value_at(data, alias) for alias in TRACE_ID_ALIASES))
    trace_url = _first_text(*(_value_at(data, alias) for alias in TRACE_URL_ALIASES))
    experiment_url = _first_text(*(_value_at(data, alias) for alias in EXPERIMENT_URL_ALIASES))
    explicit_local_url = _first_text(*(_value_at(data, alias) for alias in LOCAL_URL_ALIASES))
    generated_local_url = _generated_local_url(identity, ui_base_url=ui_base_url)
    local_url = _first_text(explicit_local_url, generated_local_url)

    has_explicit_link = any((trace_id, trace_url, experiment_url, explicit_local_url))
    if not has_explicit_link and not _looks_like_linkable_leaf(data):
        return None

    source_type = _infer_source_type(data, context)
    item = {
        "id": "",
        "source_type": source_type,
        "game_id": _first_text(identity.get("game_id")),
        "batch_id": _first_text(identity.get("batch_id")),
        "result_batch_id": _first_text(identity.get("result_batch_id")),
        "seed": identity.get("seed"),
        "trace_id": trace_id,
        "trace_url": trace_url,
        "experiment_url": experiment_url,
        "local_url": local_url,
        "ui_deep_link": local_url,
        "metadata": _metadata_for_record(data, context=context, path=path, source_type=source_type),
    }
    return item


def _context_from_data(data: dict[str, Any], parent: Mapping[str, Any], *, child_key: str | None) -> dict[str, Any]:
    context = dict(parent)
    metadata = _as_mapping(data.get("metadata"))

    if child_key == "results" and data.get("batch_id") not in (None, ""):
        context["batch_id"] = data["batch_id"]
    if child_key in {"games", "problem_games", "affected_games"}:
        result_batch_id = _first_present(data.get("result_batch_id"), data.get("batch_id"), context.get("result_batch_id"))
        if result_batch_id not in (None, ""):
            context["result_batch_id"] = result_batch_id

    for key in IDENTITY_KEYS:
        value = _first_present(data.get(key), metadata.get(key))
        if value not in (None, ""):
            normalized_key = "game_id" if key == "history_game_id" else key
            context[normalized_key] = value

    benchmark = _as_mapping(data.get("benchmark"))
    benchmark_fields = {
        "benchmark_id": "id",
        "benchmark_version": "version",
        "evaluation_set_id": "evaluation_set_id",
        "seed_set_id": "seed_set_id",
        "target_type": "target_type",
    }
    for context_key, benchmark_key in benchmark_fields.items():
        if context.get(context_key) in (None, "") and benchmark.get(benchmark_key) not in (None, ""):
            context[context_key] = benchmark[benchmark_key]

    config = _as_mapping(data.get("config") or data.get("batch_config"))
    for key in IDENTITY_KEYS:
        if context.get(key) in (None, "") and config.get(key) not in (None, ""):
            context[key] = config[key]

    if parent.get("batch_id") and data.get("batch_id") and _looks_like_result_container(data):
        context["batch_id"] = parent["batch_id"]
        context["result_batch_id"] = _first_present(data.get("result_batch_id"), data.get("batch_id"))

    source_type = _infer_source_type(data, context)
    if source_type:
        context["source_type"] = source_type
    if data.get("kind") not in (None, ""):
        context["kind"] = data["kind"]
    if data.get("schema_version") not in (None, ""):
        context["schema_version"] = data["schema_version"]
    return {key: value for key, value in context.items() if value not in (None, "")}


def _identity_from_data(data: dict[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _as_mapping(data.get("metadata"))
    identity = dict(context)
    for key in ("game_id", "history_game_id", "batch_id", "result_batch_id", "seed", "run_id", "source_run_id"):
        value = _first_present(data.get(key), metadata.get(key), context.get("game_id" if key == "history_game_id" else key))
        if value not in (None, ""):
            identity["game_id" if key == "history_game_id" else key] = value
    return identity


def _metadata_for_record(
    data: dict[str, Any],
    *,
    context: Mapping[str, Any],
    path: str,
    source_type: str,
) -> dict[str, Any]:
    metadata_source = _as_mapping(data.get("metadata"))
    metadata: dict[str, Any] = {
        "source_type": source_type,
        "source_path": path,
    }
    if data.get("id") not in (None, ""):
        metadata["source_id"] = data["id"]
    if data.get("kind") not in (None, ""):
        metadata["source_kind"] = data["kind"]
    if data.get("schema_version") not in (None, ""):
        metadata["source_schema_version"] = data["schema_version"]

    for key in METADATA_KEYS:
        value = _first_present(data.get(key), metadata_source.get(key), context.get(key))
        if value not in (None, ""):
            metadata[key] = value

    langfuse = _as_mapping(data.get("langfuse"))
    metadata_langfuse = _as_mapping(metadata_source.get("langfuse"))
    for key in LANGFUSE_METADATA_KEYS:
        output_key = f"langfuse_{key}"
        value = _first_present(data.get(output_key), metadata_source.get(output_key), langfuse.get(key), metadata_langfuse.get(key))
        if value not in (None, ""):
            metadata[output_key] = value

    return _sanitize(metadata)


def _generated_local_url(identity: Mapping[str, Any], *, ui_base_url: str) -> str | None:
    base = _normalized_base_url(ui_base_url)
    game_id = _first_text(identity.get("game_id"))
    batch_id = _first_text(identity.get("batch_id"))
    result_batch_id = _first_text(identity.get("result_batch_id"))
    run_id = _first_text(identity.get("run_id"), identity.get("source_run_id"))

    if game_id and (batch_id or result_batch_id):
        resolved_batch_id = batch_id or result_batch_id
        path = f"/benchmark/batch/{quote(str(resolved_batch_id), safe='')}/games"
        return f"{base}{path}?{urlencode({'game_id': str(game_id)})}"
    if batch_id:
        return f"{base}/benchmark/batch/{quote(str(batch_id), safe='')}"
    if result_batch_id:
        return f"{base}/benchmark/batch/{quote(str(result_batch_id), safe='')}"
    if run_id:
        return f"{base}/evolution-runs/{quote(str(run_id), safe='')}"
    return None


def _normalized_base_url(ui_base_url: str) -> str:
    base = (ui_base_url or DEFAULT_UI_BASE_URL).rstrip("/")
    return "" if base == "" else base


def _dedupe_key(item: Mapping[str, Any]) -> str:
    game_id = item.get("game_id")
    if game_id not in (None, ""):
        material = [
            "game",
            item.get("source_type"),
            item.get("batch_id"),
            item.get("result_batch_id"),
            game_id,
            item.get("seed"),
            item.get("trace_id"),
            item.get("trace_url"),
            item.get("experiment_url"),
            item.get("local_url"),
        ]
        return _fingerprint(material)
    if item.get("trace_id") not in (None, ""):
        return f"trace:{item['trace_id']}"
    if item.get("trace_url") not in (None, ""):
        return f"trace_url:{item['trace_url']}"
    if item.get("experiment_url") not in (None, ""):
        return _fingerprint(["experiment", item.get("source_type"), item.get("batch_id"), item.get("result_batch_id"), item["experiment_url"]])
    if item.get("local_url") not in (None, ""):
        return f"local:{item['local_url']}"
    return _fingerprint([item.get("source_type"), item.get("batch_id"), item.get("result_batch_id"), item.get("seed")])


def _stable_item_id(item: Mapping[str, Any]) -> str:
    material = {
        "source_type": item.get("source_type"),
        "game_id": item.get("game_id"),
        "batch_id": item.get("batch_id"),
        "result_batch_id": item.get("result_batch_id"),
        "seed": item.get("seed"),
        "trace_id": item.get("trace_id"),
        "trace_url": item.get("trace_url"),
        "experiment_url": item.get("experiment_url"),
        "local_url": item.get("local_url"),
    }
    return f"link:{_fingerprint(material)[:16]}"


def _merge_item(existing: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        if key == "metadata":
            for metadata_key, metadata_value in _as_mapping(value).items():
                existing["metadata"].setdefault(metadata_key, metadata_value)
            continue
        if existing.get(key) in (None, "") and value not in (None, ""):
            existing[key] = value


def _missing_entry(item: Mapping[str, Any]) -> dict[str, Any]:
    reasons = _missing_reasons(item)
    missing_fields: list[str] = []
    if "missing_trace_url_for_trace_id" in reasons:
        missing_fields.append("trace_url")
    if "missing_langfuse_url" in reasons:
        missing_fields.append("langfuse_url")
    if "missing_local_url" in reasons:
        missing_fields.append("local_url")
    if "missing_all_urls" in reasons:
        missing_fields.append("url")
    return {
        "id": item.get("id"),
        "source_type": item.get("source_type"),
        "game_id": item.get("game_id"),
        "batch_id": item.get("batch_id"),
        "result_batch_id": item.get("result_batch_id"),
        "seed": item.get("seed"),
        "trace_id": item.get("trace_id"),
        "missing": missing_fields,
        "reason": ";".join(reasons),
        "reasons": reasons,
    }


def _missing_reasons(item: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    trace_url = _first_text(item.get("trace_url"))
    experiment_url = _first_text(item.get("experiment_url"))
    local_url = _first_text(item.get("local_url"), item.get("ui_deep_link"))
    if item.get("trace_id") not in (None, "") and not trace_url:
        reasons.append("missing_trace_url_for_trace_id")
    if not trace_url and not experiment_url:
        reasons.append("missing_langfuse_url")
    if not local_url:
        reasons.append("missing_local_url")
    if not trace_url and not experiment_url and not local_url:
        reasons.append("missing_all_urls")
    return reasons


def _sort_key(item: Mapping[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(item.get("source_type") or ""),
        str(item.get("batch_id") or ""),
        str(item.get("result_batch_id") or ""),
        str(item.get("game_id") or ""),
        str(item.get("seed") or ""),
        str(item.get("trace_id") or ""),
        str(item.get("local_url") or ""),
    )


def _infer_source_type(data: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    metadata = _as_mapping(data.get("metadata"))
    direct = _first_text(data.get("source_type"), metadata.get("source_type"))
    if direct:
        return _normalize_source_type(direct)

    hints = (
        data.get("kind"),
        data.get("schema_version"),
        context.get("kind"),
        context.get("schema_version"),
        context.get("source_type"),
    )
    for hint in hints:
        source_type = _source_type_from_hint(hint)
        if source_type:
            return source_type

    if data.get("payload_links") is not None or data.get("checklist") is not None:
        return "verification"
    if data.get("annotation_task") is not None or data.get("priority_score") is not None:
        return "annotation_queue"
    if data.get("review") is not None or data.get("review_report") is not None:
        return "review"
    if data.get("score_summary") is not None or data.get("leaderboard_gate") is not None or data.get("games") is not None:
        return "benchmark"
    return _normalize_source_type(context.get("source_type") or "payload")


def _source_type_from_hint(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if "annotation" in text and "queue" in text:
        return "annotation_queue"
    if "verification" in text or "verify" in text:
        return "verification"
    if "benchmark" in text or text.startswith("bench"):
        return "benchmark"
    if "review" in text:
        return "review"
    if "eval" in text:
        return "eval"
    return None


def _normalize_source_type(value: Any) -> str:
    hinted = _source_type_from_hint(value)
    if hinted:
        return hinted
    text = str(value or "payload").strip().lower()
    return "_".join(part for part in text.replace("-", "_").split() if part) or "payload"


def _looks_like_result_container(data: Mapping[str, Any]) -> bool:
    return any(
        data.get(key) is not None
        for key in ("result_batch_id", "games", "score_summary", "leaderboard_gate", "config", "batch_config")
    )


def _looks_like_linkable_leaf(data: Mapping[str, Any]) -> bool:
    metadata = _as_mapping(data.get("metadata"))
    if _first_text(data.get("game_id"), data.get("history_game_id"), metadata.get("game_id")):
        return True
    if _first_text(data.get("run_id"), data.get("source_run_id"), metadata.get("run_id"), metadata.get("source_run_id")):
        return not any(isinstance(data.get(key), (Mapping, list)) for key in ("results", "games", "items"))
    return False


def _coerce_payloads(payloads: Iterable[Any] | Any) -> list[Any]:
    if payloads is None:
        return []
    if isinstance(payloads, Mapping):
        return [payloads]
    if isinstance(payloads, (str, bytes, bytearray)):
        return [payloads]
    try:
        return list(payloads)
    except TypeError:
        return [payloads]


def _value_at(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            if _is_sensitive_key(key):
                continue
            output[key] = _sanitize(raw_item)
        return redact(output, context="public")
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return redact(value, context="public")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _fingerprint(value: Any) -> str:
    material = json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
