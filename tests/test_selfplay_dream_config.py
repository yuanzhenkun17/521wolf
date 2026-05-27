"""Tests for dream layering config."""
from agent.evaluation.selfplay import SelfPlayConfig


def test_enable_dream_default_false():
    c = SelfPlayConfig(games=5)
    assert c.enable_dream is False


def test_enable_batch_dream_default_false():
    c = SelfPlayConfig(games=5)
    assert c.enable_batch_dream is False


def test_enable_batch_dream_set():
    c = SelfPlayConfig(games=5, enable_batch_dream=True)
    assert c.enable_batch_dream is True
