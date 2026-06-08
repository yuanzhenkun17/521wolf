from __future__ import annotations

from app.tools import real_llm_smoke


def test_resolve_outer_timeout_uses_explicit_argument(monkeypatch):
    monkeypatch.setenv("WEREWOLF_GAME_TIMEOUT", "3600")

    args = real_llm_smoke._parse_args(["--timeout-seconds", "120"])

    assert real_llm_smoke._resolve_outer_timeout(args) == {
        "outer_timeout_seconds": 120.0,
        "outer_timeout_source": "argument",
        "game_timeout_seconds": 3600.0,
    }


def test_resolve_outer_timeout_defaults_to_game_timeout_with_buffer(monkeypatch):
    monkeypatch.setenv("WEREWOLF_GAME_TIMEOUT", "3600")

    args = real_llm_smoke._parse_args(["--timeout-buffer-seconds", "45"])

    assert real_llm_smoke._resolve_outer_timeout(args) == {
        "outer_timeout_seconds": 3645.0,
        "outer_timeout_source": "game_timeout_env",
        "game_timeout_seconds": 3600.0,
    }


def test_resolve_outer_timeout_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("WEREWOLF_GAME_TIMEOUT", raising=False)
    monkeypatch.delenv("WEREWOLF_RUNNER_GAME_TIMEOUT", raising=False)

    args = real_llm_smoke._parse_args([])

    assert real_llm_smoke._resolve_outer_timeout(args) == {
        "outer_timeout_seconds": 900.0,
        "outer_timeout_source": "default",
        "game_timeout_seconds": None,
    }
