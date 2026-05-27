"""Tests for memory_candidate persistence."""
import json
import tempfile
from pathlib import Path

from agent.cognition.long_memory import RoleLongTermMemory, write_memory_candidate


def test_write_memory_candidate():
    memory = RoleLongTermMemory(
        role="werewolf",
        generated_at="2026-01-01T00:00:00Z",
        source_card_count=5,
        win_rate=0.6,
        avg_score=7.0,
    )
    with tempfile.TemporaryDirectory() as td:
        path = write_memory_candidate(memory, output_dir=td)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["role"] == "werewolf"
        assert data["win_rate"] == 0.6
