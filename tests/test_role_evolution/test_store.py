"""Tests for VersionStore, compute_hash, and path/text normalization."""

import pytest

from agent.learning.evolution.store import (
    VersionStore,
    compute_hash,
    normalize_skill_path,
    HashCollisionError,
)


# ---------------------------------------------------------------------------
# Hash normalization
# ---------------------------------------------------------------------------


def test_hash_normalization_lf_crlf():
    """Same skill content with LF vs CRLF produces same hash."""
    skills_lf = {"skills/seer/claim.md": "line one\nline two\n"}
    skills_crlf = {"skills/seer/claim.md": "line one\r\nline two\r\n"}
    assert compute_hash(skills_lf) == compute_hash(skills_crlf)


def test_hash_normalization_strips_trailing_whitespace():
    """Trailing spaces/tabs don't affect hash."""
    skills_clean = {"skills/seer/claim.md": "line one\nline two\n"}
    skills_dirty = {"skills/seer/claim.md": "line one   \nline two\t\n"}
    assert compute_hash(skills_clean) == compute_hash(skills_dirty)


# ---------------------------------------------------------------------------
# normalize_skill_path
# ---------------------------------------------------------------------------


def test_normalize_skill_path_rejects_empty():
    """Empty path raises ValueError."""
    with pytest.raises(ValueError, match="Empty path"):
        normalize_skill_path("")


def test_normalize_skill_path_rejects_absolute():
    """Absolute path raises ValueError."""
    with pytest.raises(ValueError, match="Absolute path"):
        normalize_skill_path("/skills/seer/claim.md")


def test_normalize_skill_path_rejects_dotdot():
    """Path with '..' raises ValueError."""
    with pytest.raises(ValueError, match="traversal"):
        normalize_skill_path("skills/../seer/claim.md")


def test_normalize_skill_path_rejects_non_md():
    """Non-.md file raises ValueError."""
    with pytest.raises(ValueError, match="Only .md"):
        normalize_skill_path("skills/seer/claim.txt")


def test_normalize_skill_path_normalizes_backslash():
    """Backslash paths normalized to forward slash."""
    result = normalize_skill_path("skills\\seer\\claim.md")
    assert "\\" not in result
    assert result == "skills/seer/claim.md"


# ---------------------------------------------------------------------------
# compute_hash
# ---------------------------------------------------------------------------


def test_compute_hash_duplicate_normalized_path():
    """Two paths normalizing to same value raises ValueError."""
    skills = {
        "skills/seer/claim.md": "content",
        "skills\\seer\\claim.md": "content",
    }
    with pytest.raises(ValueError, match="Duplicate normalized path"):
        compute_hash(skills)


# ---------------------------------------------------------------------------
# VersionStore — async tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return VersionStore(tmp_path / "role_versions")


@pytest.fixture
def sample_skills():
    return {"seer/claim.md": "# Seer Claim\nAlways claim D1.\n"}


@pytest.mark.asyncio
async def test_save_version_idempotent(store, sample_skills):
    """Same hash+content returns same hash on second save."""
    h1 = await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    h2 = await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    assert h1 == h2


@pytest.mark.asyncio
async def test_save_version_collision(store):
    """Same hash different content raises HashCollisionError."""
    from agent.learning.evolution.store import _write_json
    from agent.learning.evolution.models import RoleVersion
    from datetime import datetime, timezone

    skills_a = {"seer/claim.md": "# Seer\nContent A\n"}
    h = await store.save_version("seer", skills_a, parent_hash=None, source="test")

    # Tamper: overwrite meta.json with different skills content but same hash
    tampered = RoleVersion(
        hash=h,
        role="seer",
        skills={"seer/claim.md": "# Seer\nTOTALLY DIFFERENT\n"},
        created_at=datetime.now(timezone.utc).isoformat(),
        source="tamper",
    )
    _write_json(store._meta_path("seer", h), tampered.to_dict())

    # Saving original content again should raise HashCollisionError
    # because the on-disk meta now has different normalized content
    with pytest.raises(HashCollisionError):
        await store.save_version("seer", skills_a, parent_hash=None, source="test")


@pytest.mark.asyncio
async def test_save_version_history_not_duplicated(store, sample_skills):
    """Saving same hash twice doesn't duplicate in history."""
    await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    history = store.get_history("seer")
    assert history.versions.count(history.versions[0]) == 1


@pytest.mark.asyncio
async def test_set_baseline_cas_mismatch(store, sample_skills):
    """set_baseline with wrong expected_current returns False."""
    h = await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    result = await store.set_baseline("seer", h, expected_current="wrong_hash")
    assert result is False


@pytest.mark.asyncio
async def test_set_baseline_cas_match(store, sample_skills):
    """set_baseline with correct expected_current returns True and updates."""
    h1 = await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    skills_v2 = {"seer/claim.md": "# Seer\nVersion 2\n"}
    h2 = await store.save_version("seer", skills_v2, parent_hash=h1, source="test")

    result = await store.set_baseline("seer", h2, expected_current=h1)
    assert result is True
    history = store.get_history("seer")
    assert history.baseline == h2


@pytest.mark.asyncio
async def test_rollback_only_moves_baseline(store, sample_skills):
    """Rollback moves baseline pointer, doesn't change parent_hash of any version."""
    h1 = await store.save_version("seer", sample_skills, parent_hash=None, source="test")
    skills_v2 = {"seer/claim.md": "# Seer\nVersion 2\n"}
    h2 = await store.save_version("seer", skills_v2, parent_hash=h1, source="test")

    # Advance baseline to h2
    await store.set_baseline("seer", h2, expected_current=h1)

    # Rollback to h1
    result = await store.set_baseline("seer", h1, expected_current=h2)
    assert result is True

    # Verify parent_hash of both versions unchanged
    v1 = store.load_version("seer", h1)
    v2 = store.load_version("seer", h2)
    assert v1.parent_hash is None
    assert v2.parent_hash == h1


# ---------------------------------------------------------------------------
# initialize_from_skills
# ---------------------------------------------------------------------------


def test_initialize_from_skills(tmp_path):
    """Initialize from real skills/ directory creates baseline for each role."""
    # Build a mini skills tree
    skills_root = tmp_path / "skills"
    for role, files in [
        ("seer", {"claim.md": "# Seer Claim\n"}),
        ("werewolf", {"fake_seer.md": "# Fake Seer\n"}),
    ]:
        role_dir = skills_root / role
        role_dir.mkdir(parents=True)
        for name, content in files.items():
            (role_dir / name).write_text(content, encoding="utf-8")

    store = VersionStore(tmp_path / "role_versions")
    store.initialize_from_skills(skills_root)

    roles = store.list_roles()
    assert "seer" in roles
    assert "werewolf" in roles

    for role in roles:
        history = store.get_history(role)
        assert len(history.versions) == 1
        baseline = store.load_version(role, history.baseline)
        assert baseline.source == "initialize_from_skills"
