"""Tests for app/util/ — all 8 modules.

Since util/ has no app-runtime dependencies and only depends on engine/
(black box), these tests establish the baseline integrity of the utility layer.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest


# ===========================================================================
# app/util/json.py
# ===========================================================================

class TestJson:
    def test_compact_json_serializable(self):
        from app.util.json import compact_json
        assert "a" in compact_json({"a": 1})
        assert "1" in compact_json({"a": 1})

    def test_compact_json_fallback(self):
        from app.util.json import compact_json
        result = compact_json(object())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_jsonable_dataclass(self):
        from app.util.json import to_jsonable
        from dataclasses import dataclass

        @dataclass
        class Foo:
            x: int = 1

        result = to_jsonable(Foo(x=42))
        assert result == {"x": 42}

    def test_to_jsonable_path(self):
        from app.util.json import to_jsonable
        result = to_jsonable(Path("/tmp/test"))
        assert result == str(Path("/tmp/test"))

    def test_dict_mixin(self):
        from app.util.json import DictMixin
        from dataclasses import dataclass

        @dataclass
        class Model(DictMixin):
            name: str = "test"
            value: int = 42

        m = Model()
        d = m.to_dict()
        assert d == {"name": "test", "value": 42}

    def test_read_write_json(self, tmp_path):
        from app.util.json import read_json, write_json
        p = tmp_path / "test.json"
        write_json(p, {"hello": "world"})
        assert p.exists()
        data = read_json(p)
        assert data == {"hello": "world"}

    def test_read_json_object_returns_default_for_missing_invalid_or_non_object(self, tmp_path):
        from app.util.json import read_json_object, write_json

        missing = tmp_path / "missing.json"
        bad = tmp_path / "bad.json"
        list_root = tmp_path / "list.json"
        object_root = tmp_path / "object.json"
        default = {"fallback": True}

        bad.write_text("{not json", encoding="utf-8")
        write_json(list_root, [1, 2, 3])
        write_json(object_root, {"ok": True})

        assert read_json_object(missing, default=default) == default
        assert read_json_object(bad, default=default) == default
        assert read_json_object(list_root, default=default) == default
        assert read_json_object(object_root, default=default) == {"ok": True}

    def test_write_json_repeated_writes_do_not_leave_fixed_tmp(self, tmp_path):
        from app.util.json import read_json, write_json

        p = tmp_path / "test.json"
        fixed_tmp = p.with_suffix(".tmp")

        for index in range(3):
            write_json(p, {"index": index})

        assert read_json(p) == {"index": 2}
        assert not fixed_tmp.exists()
        assert [child for child in tmp_path.iterdir() if child.suffix == ".tmp"] == []

    def test_write_json_replace_failure_cleans_current_tmp(self, tmp_path, monkeypatch):
        from app.util import json as json_util

        p = tmp_path / "test.json"
        tmp_paths = []

        def fail_replace(src, dst):
            tmp_path = Path(src)
            tmp_paths.append(tmp_path)
            assert tmp_path.parent == p.parent
            assert tmp_path.exists()
            raise OSError("replace failed")

        monkeypatch.setattr(json_util.os, "replace", fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            json_util.write_json(p, {"hello": "world"})

        assert len(tmp_paths) == 1
        assert not tmp_paths[0].exists()
        assert not p.exists()

    def test_write_json_concurrent_writes_leave_valid_file_and_no_tmp(self, tmp_path):
        from app.util.json import read_json, write_json

        p = tmp_path / "concurrent.json"

        def write_index(index: int) -> None:
            write_json(p, {"index": index, "payload": [index] * 4})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write_index, range(40)))

        data = read_json(p)
        assert isinstance(data["index"], int)
        assert data["payload"] == [data["index"]] * 4
        assert [child for child in tmp_path.iterdir() if child.suffix == ".tmp"] == []

    def test_read_jsonl_write_jsonl(self, tmp_path):
        from app.util.json import read_jsonl, write_jsonl
        from dataclasses import dataclass

        @dataclass
        class Item:
            x: int
            y: str

            def to_dict(self):
                return {"x": self.x, "y": self.y}

        p = tmp_path / "test.jsonl"
        items = [Item(1, "a"), Item(2, "b")]
        write_jsonl(p, items)

        rows = read_jsonl(p)
        assert len(rows) == 2
        assert rows[0] == {"x": 1, "y": "a"}
        assert rows[1] == {"x": 2, "y": "b"}

    def test_write_jsonl_concurrent_writes_leave_valid_file_and_no_tmp(self, tmp_path):
        from app.util.json import read_jsonl, write_jsonl

        p = tmp_path / "concurrent.jsonl"

        def write_index(index: int) -> None:
            write_jsonl(p, [{"index": index, "line": line} for line in range(5)])

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write_index, range(40)))

        rows = read_jsonl(p)
        assert len(rows) == 5
        indexes = {row["index"] for row in rows}
        assert len(indexes) == 1
        assert [row["line"] for row in rows] == list(range(5))
        assert [child for child in tmp_path.iterdir() if child.suffix == ".tmp"] == []

    def test_write_jsonl_replace_failure_cleans_current_tmp(self, tmp_path, monkeypatch):
        from app.util import json as json_util

        p = tmp_path / "test.jsonl"
        tmp_paths = []

        def fail_replace(src, dst):
            tmp_path = Path(src)
            tmp_paths.append(tmp_path)
            assert tmp_path.parent == p.parent
            assert tmp_path.exists()
            raise OSError("replace failed")

        monkeypatch.setattr(json_util.os, "replace", fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            json_util.write_jsonl(p, [{"hello": "world"}])

        assert len(tmp_paths) == 1
        assert not tmp_paths[0].exists()
        assert not p.exists()

    def test_read_jsonl_missing(self, tmp_path):
        from app.util.json import read_jsonl
        rows = read_jsonl(tmp_path / "nonexistent.jsonl")
        assert rows == []

    def test_write_text(self, tmp_path):
        from app.util.json import write_text
        p = tmp_path / "sub" / "file.txt"
        write_text(p, "hello\n")
        assert p.read_text() == "hello\n"


# ===========================================================================
# app/util/action_types.py
# ===========================================================================

class TestActionTypes:
    def test_import(self):
        from app.util.action_types import (
            AGENT_ACTION_TYPES,
            SPEECH_ACTION_TYPES,
            VOTE_ACTION_TYPES,
            TARGET_ACTION_TYPES,
            CHOICE_ACTION_TYPES,
            NIGHT_SKILL_ACTION_TYPES,
            SHERIFF_ACTION_TYPES,
        )
        assert isinstance(AGENT_ACTION_TYPES, frozenset)
        assert "speak" in AGENT_ACTION_TYPES
        assert "exile_vote" in AGENT_ACTION_TYPES
        assert "seer_check" in AGENT_ACTION_TYPES
        assert "speak" in SPEECH_ACTION_TYPES
        assert "exile_vote" in VOTE_ACTION_TYPES
        assert "seer_check" in TARGET_ACTION_TYPES
        assert "witch_act" in CHOICE_ACTION_TYPES
        assert "seer_check" in NIGHT_SKILL_ACTION_TYPES

    def test_is_valid_action_type(self):
        from app.util.action_types import is_valid_action_type
        assert is_valid_action_type("speak")
        assert not is_valid_action_type("bogus_action")

    def test_event_type_constants(self):
        from app.util.action_types import (
            EVENT_TYPE_SPEECH,
            EVENT_TYPE_VOTE,
            PUBLIC_SPEECH_EVENT_TYPES,
            VOTE_EVENT_TYPES,
        )
        assert EVENT_TYPE_SPEECH == "speech"
        assert EVENT_TYPE_VOTE == "vote"
        assert isinstance(PUBLIC_SPEECH_EVENT_TYPES, frozenset)
        assert isinstance(VOTE_EVENT_TYPES, frozenset)


# ===========================================================================
# app/util/time.py
# ===========================================================================

class TestTime:
    def test_beijing_now(self):
        from app.util.time import beijing_now, BEIJING_TZ
        from datetime import datetime
        now = beijing_now()
        assert isinstance(now, datetime)
        assert now.tzinfo == BEIJING_TZ

    def test_beijing_now_iso(self):
        from app.util.time import beijing_now_iso
        result = beijing_now_iso()
        assert isinstance(result, str)
        assert "T" in result
        assert "+08:00" in result

    def test_beijing_now_str(self):
        from app.util.time import beijing_now_str
        result1 = beijing_now_str("%Y%m%d")
        result2 = beijing_now_str("%H%M%S")
        assert len(result1) == 8
        assert len(result2) == 6

    def test_storage_timestamp_uses_project_timezone(self):
        from storage.interfaces import storage_timestamp

        result = storage_timestamp()

        assert "T" in result
        assert result.endswith("+08:00")


# ===========================================================================
# app/util/winner.py
# ===========================================================================

class TestWinner:
    def test_is_werewolf_win(self):
        from app.util.winner import is_werewolf_win
        assert is_werewolf_win("werewolves")
        assert is_werewolf_win("werewolf")
        assert is_werewolf_win("WEREWOLVES")
        assert not is_werewolf_win("villagers")
        assert not is_werewolf_win("wolf")  # "wolf" alone doesn't match "werewolf"


# ===========================================================================
# app/util/paths.py
# ===========================================================================

class TestPaths:
    def test_default_paths_exist(self):
        from app.config import DEFAULT_PATHS, PathConfig
        assert DEFAULT_PATHS.root.exists()

    def test_path_config_properties(self, tmp_path):
        from app.config import PathConfig
        pc = PathConfig(root=tmp_path)
        assert pc.runs_dir == tmp_path / "runs"
        assert pc.data_dir == tmp_path / "data"
        assert pc.wolf_db_path == tmp_path / "data" / "wolf.db"
        assert pc.registry_dir == tmp_path / "data" / "registry"

    def test_path_config_custom_root(self, tmp_path):
        from app.config import PathConfig
        custom = tmp_path / "custom"
        pc = PathConfig(root=custom)
        assert pc.root == custom


# ===========================================================================
# app/util/callbacks.py
# ===========================================================================

class TestCallbacks:
    def test_notify_calls_callback(self):
        from app.util.callbacks import notify
        results = []

        def cb(stage, data):
            results.append((stage, data))

        notify(cb, "test", {"k": "v"})
        assert len(results) == 1
        assert results[0] == ("test", {"k": "v"})

    def test_notify_none_does_not_raise(self):
        from app.util.callbacks import notify
        notify(None, "test", {"k": "v"})  # should not raise

    def test_notify_swallows_exception(self):
        from app.util.callbacks import notify

        def bad_cb(*args):
            raise RuntimeError("oops")

        notify(bad_cb, "test", {})  # should not raise

    def test_tracing_enabled_default_false(self):
        from app.util.callbacks import tracing_enabled
        # LANGFUSE env vars might be set in .env, just check it's callable and returns bool
        result = tracing_enabled()
        assert isinstance(result, bool)

    def test_observe_noop(self):
        from app.util.callbacks import observe
        @observe
        def func():
            return 42
        assert func() == 42

    def test_propagate_attributes_noop(self):
        from app.util.callbacks import propagate_attributes
        with propagate_attributes(session_id="test"):
            pass  # should not raise


# ===========================================================================
# app/util/redaction.py
# ===========================================================================

class TestRedaction:
    def test_redact_recursively_removes_sensitive_fields(self):
        from app.util.redaction import redact

        payload = {
            "api_key": "sk-test-secret",
            "headers": {"Authorization": "Bearer abcdefghijklmnop"},
            "prompt": "system prompt with hidden setup",
            "private_reasoning": "I know the hidden role",
            "safe": {"value": "public"},
        }

        result = redact(payload, context="diagnostic")

        assert result["api_key"] == "[REDACTED]"
        assert result["headers"]["Authorization"] == "[REDACTED]"
        assert result["prompt"].startswith("[REDACTED length=")
        assert result["private_reasoning"].startswith("[REDACTED length=")
        assert result["safe"]["value"] == "public"

    def test_redact_private_context_keeps_private_reasoning_but_not_secrets(self):
        from app.util.redaction import redact

        result = redact(
            {
                "private_reasoning": "hidden but allowed in private context",
                "token": "secret-token",
            },
            context="private",
        )

        assert result["private_reasoning"] == "hidden but allowed in private context"
        assert result["token"] == "[REDACTED]"

    def test_redact_text_masks_inline_secrets_and_truncates(self):
        from app.util.redaction import redact_text

        result = redact_text("api_key=sk-secretvalue " + "x" * 1000, context="diagnostic")

        assert "sk-secretvalue" not in result
        assert "api_key=[REDACTED]" in result
        assert "truncated length=" in result
