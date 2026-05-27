"""Tests for version battle manifest-driven loading."""
import tempfile
from pathlib import Path

from agent.evaluation.version_battle import version_spec_from_manifest, VersionSpec
from agent.versioning.manifest import (
    AgentVersionManifest,
    ModelConfig,
    PathConfig,
    RuntimeConfig,
    VersionStatus,
    save_manifest,
)


def _write_manifest(tmpdir: str, name: str = "test_v1") -> Path:
    manifest = AgentVersionManifest(
        version="1.0.0",
        display_name=name,
        status=VersionStatus.CANDIDATE,
        notes=["test version"],
        paths=PathConfig(skills="./skills"),
        model=ModelConfig(model="gpt-4o", temperature=0.3),
        runtime=RuntimeConfig(
            tot_enabled=True,
            got_enabled=False,
            got_trigger_policy="always",
            got_trigger_threshold=0.5,
        ),
    )
    manifest_path = Path(tmpdir) / "manifest.json"
    save_manifest(manifest, manifest_path)
    return manifest_path


def test_version_spec_from_manifest():
    with tempfile.TemporaryDirectory() as td:
        path = _write_manifest(td)
        spec = version_spec_from_manifest(path)
        assert spec.name == "test_v1"
        assert spec.skill_dir == Path(td) / "skills"
        assert spec.model_name == "gpt-4o"
        assert spec.temperature == 0.3
        assert spec.notes == "test version"


def test_version_spec_runtime_flags():
    with tempfile.TemporaryDirectory() as td:
        path = _write_manifest(td)
        spec = version_spec_from_manifest(path)
        assert spec.tot_enabled is True
        assert spec.got_enabled is False
        assert spec.got_trigger_policy == "always"
        assert spec.got_trigger_threshold == 0.5


def test_version_spec_to_dict_includes_flags():
    spec = VersionSpec(
        name="test",
        tot_enabled=True,
        got_enabled=False,
        got_trigger_policy="always",
        got_trigger_threshold=0.5,
    )
    d = spec.to_dict()
    assert d["tot_enabled"] is True
    assert d["got_enabled"] is False
    assert d["got_trigger_policy"] == "always"
    assert d["got_trigger_threshold"] == 0.5
