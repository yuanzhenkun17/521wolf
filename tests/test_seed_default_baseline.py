from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


seed_tool = pytest.importorskip("app.tools.seed_default_baseline")

from app.lib import version as version_mod  # noqa: E402
from engine import Role  # noqa: E402


DEFAULT_BASELINE_ROLES = tuple(
    getattr(
        seed_tool,
        "DEFAULT_BASELINE_ROLES",
        getattr(seed_tool, "DEFAULT_ROLE_ORDER", tuple(role.value for role in Role)),
    )
)


class FakeRegistry:
    def __init__(self, baselines: dict[str, str | None] | None = None) -> None:
        self.baselines = dict(baselines or {})
        self.publish_calls: list[dict[str, Any]] = []
        self.set_baseline_calls: list[dict[str, Any]] = []
        self.get_baseline_calls: list[str] = []
        self.read_skill_contents_calls: list[dict[str, str]] = []
        self.closed = False

    def get_baseline(self, role: str) -> str | None:
        self.get_baseline_calls.append(role)
        return self.baselines.get(role)

    def publish_skills(
        self,
        role: str,
        skill_contents: dict[str, str],
        *,
        parent_id: str | None = None,
        source: str = "manual",
        run_id: str | None = None,
        proposal_ids: list[str] | None = None,
        version_id: str | None = None,
        set_as_baseline: bool = False,
        expected_current: str | None = None,
    ) -> str:
        published = version_id or f"{role}_seeded"
        self.publish_calls.append(
            {
                "role": role,
                "skill_contents": dict(skill_contents),
                "parent_id": parent_id,
                "source": source,
                "run_id": run_id,
                "proposal_ids": list(proposal_ids or []),
                "version_id": version_id,
                "set_as_baseline": set_as_baseline,
                "expected_current": expected_current,
                "published": published,
            }
        )
        if set_as_baseline:
            self.baselines[role] = published
        return published

    def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        self.set_baseline_calls.append(
            {
                "role": role,
                "version_id": version_id,
                "expected_current": expected_current,
            }
        )
        if self.baselines.get(role) != expected_current:
            return False
        self.baselines[role] = version_id
        return True

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        self.read_skill_contents_calls.append({"role": role, "version_id": version_id})
        return {
            "main.md": _skill_markdown(role).replace(
                f"Baseline guidance for {role}.",
                f"Existing registry guidance for {role}.",
            )
        }

    def close(self) -> None:
        self.closed = True


def _patch_registry(monkeypatch: pytest.MonkeyPatch, registry: FakeRegistry) -> None:
    def factory(*args: Any, **kwargs: Any) -> FakeRegistry:
        return registry

    monkeypatch.setattr(version_mod, "version_registry_from_env", factory)
    monkeypatch.setattr(seed_tool, "version_registry_from_env", factory, raising=False)


def _run_main(argv: list[str]) -> int:
    try:
        result = seed_tool.main(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    return int(result or 0)


def _seed_args(root: Path, *extra: str) -> list[str]:
    return ["--skill-root", str(root), *extra]


def _write_default_baseline_tree(root: Path, *, roles: tuple[str, ...] = DEFAULT_BASELINE_ROLES) -> Path:
    for role in roles:
        _write_role_skill(root, role)
    return root


def _write_role_skill(root: Path, role: str) -> Path:
    role_dir = root / role
    role_dir.mkdir(parents=True, exist_ok=True)
    path = role_dir / "main.md"
    path.write_text(_skill_markdown(role), encoding="utf-8")
    return path


def _skill_markdown(role: str) -> str:
    return (
        "---\n"
        f"name: default_{role}_baseline\n"
        f"role: {role}\n"
        "status: active\n"
        "applicable_actions:\n"
        "  - speak\n"
        "evolution:\n"
        "  enabled: true\n"
        "  allowed_actions:\n"
        "    - append_rule\n"
        "---\n"
        f"Baseline guidance for {role}.\n"
    )


def _combined_output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_dry_run_validates_role_dirs_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_dir = _write_default_baseline_tree(tmp_path / "default_baseline")
    registry = FakeRegistry()
    _patch_registry(monkeypatch, registry)

    code = _run_main(_seed_args(baseline_dir, "--dry-run"))

    assert code == 0
    assert registry.publish_calls == []
    assert registry.set_baseline_calls == []


@pytest.mark.parametrize("case", ["missing_dir", "empty_dir"])
def test_invalid_role_directory_returns_nonzero_and_names_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    missing_role = DEFAULT_BASELINE_ROLES[0]
    roles = tuple(role for role in DEFAULT_BASELINE_ROLES if role != missing_role)
    baseline_dir = _write_default_baseline_tree(tmp_path / "default_baseline", roles=roles)
    if case == "empty_dir":
        empty_dir = baseline_dir / missing_role
        empty_dir.mkdir(parents=True)

    registry = FakeRegistry()
    _patch_registry(monkeypatch, registry)

    code = _run_main(_seed_args(baseline_dir, "--dry-run"))

    assert code != 0
    assert missing_role in _combined_output(capsys)
    assert registry.publish_calls == []
    assert registry.set_baseline_calls == []


def test_seed_publishes_each_role_as_baseline_with_current_baseline_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_dir = _write_default_baseline_tree(tmp_path / "default_baseline")
    registry = FakeRegistry({role: None for role in DEFAULT_BASELINE_ROLES})
    _patch_registry(monkeypatch, registry)

    code = _run_main(_seed_args(baseline_dir))

    assert code == 0
    assert registry.set_baseline_calls == []
    assert [call["role"] for call in registry.publish_calls] == list(DEFAULT_BASELINE_ROLES)
    for call in registry.publish_calls:
        role = call["role"]
        assert call["set_as_baseline"] is True
        assert call["expected_current"] is None
        assert call["skill_contents"]
        assert all(f"role: {role}" in content for content in call["skill_contents"].values())


def test_existing_baseline_without_force_refuses_to_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_dir = _write_default_baseline_tree(tmp_path / "default_baseline")
    existing_role = DEFAULT_BASELINE_ROLES[0]
    registry = FakeRegistry({existing_role: f"current_{existing_role}"})
    _patch_registry(monkeypatch, registry)

    code = _run_main(_seed_args(baseline_dir))

    assert code != 0
    assert existing_role in _combined_output(capsys)
    assert registry.publish_calls == []
    assert registry.set_baseline_calls == []


def test_force_seed_uses_expected_current_for_existing_baselines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_dir = _write_default_baseline_tree(tmp_path / "default_baseline")
    baselines = {role: f"current_{role}" for role in DEFAULT_BASELINE_ROLES}
    registry = FakeRegistry(baselines)
    _patch_registry(monkeypatch, registry)

    code = _run_main(_seed_args(baseline_dir, "--force"))

    assert code == 0
    assert [call["role"] for call in registry.publish_calls] == list(DEFAULT_BASELINE_ROLES)
    assert {
        call["role"]: call["expected_current"]
        for call in registry.publish_calls
    } == baselines
    assert all(call["set_as_baseline"] is True for call in registry.publish_calls)
    assert registry.set_baseline_calls == []
