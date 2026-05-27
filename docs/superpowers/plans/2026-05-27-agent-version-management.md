# Agent Version Management Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement Phase 0-3 (MVP) of the agent version management system: skill metadata, manifest, version battle, and promote/reject.

**Architecture:** Version state (skills, prompts, memory, model config, runtime flags) is captured in agent_versions/<name>/manifest.json. version_battle.py loads manifests into VersionSpec -> SelfPlayConfig, runs fixed-seed selfplay, aggregates leaderboard, and auto-promotes/rejects candidates.

**Tech Stack:** Python 3.12, dataclasses, pathlib, pytest

**Design Reference:** docs/agent_version_management_plan.md Sections 11-16

---

## Task 0A: memory_candidate Persistence

**Files:**
- Modify: agent/cognition/long_memory.py
- Modify: agent/evaluation/selfplay.py

- [ ] Step 1: Write failing test: after selfplay, runs/<run_id>/memory_candidate/{role}.json exists
- [ ] Step 2: Add write_memory_candidate(memory, run_dir) to long_memory.py that writes to run_dir/memory_candidate/
- [ ] Step 3: In selfplay.py, after consolidate_role_memory, also call write_memory_candidate to runs/<run_id>/memory_candidate/
- [ ] Step 4: Run tests
- [ ] Step 5: Commit

---

## Task 0B: Enhanced Review Data in summary.json

**Files:**
- Modify: agent/evaluation/selfplay.py (summary generation)

- [ ] Step 1: Write failing test: summary.json contains mistake_count, counterfactual_count, turning_point_count
- [ ] Step 2: In selfplay summary generation, extract counts from GameReviewReport and add to summary dict
- [ ] Step 3: Run tests
- [ ] Step 4: Commit

---

## Task 0C: Counterfactual Coverage Expansion

**Files:**
- Modify: agent/evaluation/review_enhanced.py (_generate_counterfactuals)

- [ ] Step 1: Write failing test: counterfactuals cover at least 5 mistake types
- [ ] Step 2: Add counterfactual generation for: wrong exile vote, seer check priority error, wolf kills teammate, guard same-person-consecutive, witch self-poison
- [ ] Step 3: Run tests
- [ ] Step 4: Commit



---

## Task 1: Skill Metadata Extension (evolvable, category)

**Files:**
- Modify: agent/skill_system/loader.py:28-39 (MarkdownSkill dataclass)
- Modify: agent/skill_system/loader.py:216-225 (_load_skill_file)
- Create: tests/test_skill_metadata.py

- [ ] Step 1: Write failing tests for new metadata fields
- [ ] Step 2: Add evolvable (bool, default False) and category (str, default strategy) to MarkdownSkill dataclass
- [ ] Step 3: Update _load_skill_file to parse evolvable and category from front-matter
- [ ] Step 4: Run tests to verify PASS
- [ ] Step 5: Commit

---

## Task 2: applicable_actions Empty = Always Inject

**Files:**
- Modify: agent/skill_system/router.py:74-78 (select_skills)

- [ ] Step 1: Write failing test: skill with empty applicable_actions should match any action
- [ ] Step 2: Fix select_skills: change condition to (not skill.applicable_actions or action_type in skill.applicable_actions)
- [ ] Step 3: Run tests
- [ ] Step 4: Commit

---

## Task 3: Per-Root Skill Cache

**Files:**
- Modify: agent/skill_system/router.py (replace module-level globals)

- [ ] Step 1: Write failing tests for cache behavior (same root returns same object, different roots return different objects)
- [ ] Step 2: Implement SkillIndex dataclass (common: list, by_role: dict) and _get_skill_index(skill_root)
- [ ] Step 3: Replace _COMMON_SKILLS, _ROLE_SKILLS globals with _SKILL_CACHE: dict[Path, SkillIndex]
- [ ] Step 4: Update select_skills() to accept skill_root param and use _get_skill_index()
- [ ] Step 5: Run tests
- [ ] Step 6: Commit

---

## Task 4: AgentRuntime Accepts skill_dir

**Files:**
- Modify: agent/runtime/agent.py:73-95 (AgentRuntime.__init__)
- Modify: agent/runtime/agent.py:109 (act -> skill_router_node call)
- Modify: agent/runtime/agent.py:147-168 (LLMPlayerAgent.__init__)
- Modify: agent/runtime/factory.py:15-33 (create_agents)
- Modify: agent/nodes/skill_router.py:11-18 (skill_router_node)

- [ ] Step 1: Add skill_dir: Path|str|None = None to AgentRuntime.__init__, store as Path
- [ ] Step 2: Pass skill_root=self.skill_dir to skill_router_node in act()
- [ ] Step 3: Update skill_router_node to accept skill_root kwarg and forward to select_skills()
- [ ] Step 4: Update LLMPlayerAgent.__init__ and create_agents() to accept and forward skill_dir
- [ ] Step 5: Commit

---

## Task 5: AgentVersionManifest Data Structure

**Files:**
- Create: agent/versioning/__init__.py (empty)
- Create: agent/versioning/manifest.py
- Create: tests/test_manifest.py

- [ ] Step 1: Write failing tests (roundtrip, resolve_manifest_path relative/absolute)
- [ ] Step 2: Implement VersionStatus enum, RuntimeConfig, ModelConfig, EvolutionConfig, PathConfig dataclasses
- [ ] Step 3: Implement AgentVersionManifest dataclass with to_dict()/from_dict()
- [ ] Step 4: Implement load_manifest(), save_manifest(), resolve_manifest_path(), current_git_commit(), validate_manifest()
- [ ] Step 5: Run tests
- [ ] Step 6: Commit

---

## Task 6: create_agent_version Function

**Files:**
- Modify: agent/versioning/manifest.py
- Modify: tests/test_manifest.py

- [ ] Step 1: Write failing test (copies skills and memory from base, sets status=candidate)
- [ ] Step 2: Implement create_agent_version(name, base, versions_root, source_skill_dir, source_memory_dir, notes)
- [ ] Step 3: Run tests
- [ ] Step 4: Commit

---

## Task 7: Leaderboard Metric Extensions

**Files:**
- Modify: agent/evaluation/leaderboard.py (LeaderboardEntry, aggregate_summaries, to_dict)
- Create: tests/test_leaderboard_ext.py

- [ ] Step 1: Write failing tests for new fields
- [ ] Step 2: Add fields to LeaderboardEntry: bad_case_count, turning_point_quality, tot_usage_rate, got_trigger_count, got_failure_count, information_score, cooperation_score, by_role
- [ ] Step 3: Update aggregate_summaries() with weighted average for new fields and by_role merging
- [ ] Step 4: Update to_dict() to include new fields
- [ ] Step 5: Run tests
- [ ] Step 6: Commit

---

## Task 8: Version Battle with Manifest-Driven Loading

**Files:**
- Modify: agent/evaluation/version_battle.py

- [ ] Step 1: Write failing test for version_spec_from_manifest()
- [ ] Step 2: Implement version_spec_from_manifest(manifest_path) -> VersionSpec
- [ ] Step 3: Update run_version_battle to accept versions: list[str] and build VersionBattleConfig from manifests
- [ ] Step 4: Run tests
- [ ] Step 5: Commit

---

## Task 9: Promote / Reject Logic

**Files:**
- Modify: agent/versioning/manifest.py
- Modify: agent/evaluation/version_battle.py

- [ ] Step 1: Write failing tests for PromotionVerdict and evaluate_promotion()
- [ ] Step 2: Implement PromotionVerdict dataclass (promoted, reasons, metrics)
- [ ] Step 3: Implement evaluate_promotion(candidate, base) with rules: score >= 5%, bad_case no increase, fallback no increase, policy_adjusted no increase, win_rate drop < 10pp
- [ ] Step 4: Add update_manifest_status(manifest_path, status, evaluation_update)
- [ ] Step 5: Run tests
- [ ] Step 6: Commit

---

## Task 10: Prompt-to-Skill Extraction

**Files:**
- Create: skills/common/system_identity.md (scope=common, category=foundation, evolvable=false)
- Create: skills/common/reasoning_contract.md (scope=common, category=foundation, evolvable=false)
- Create: skills/werewolf/persona.md through skills/white_wolf_king/persona.md (7 files, scope=role, category=foundation, evolvable=false)
- Modify: agent/prompts/base.py (build_system_prompt uses skill_context)

- [ ] Step 1: Create system_identity.md with identity constraints from build_system_prompt
- [ ] Step 2: Create reasoning_contract.md with reasoning constraints from build_system_prompt
- [ ] Step 3: Create persona.md for each of 7 roles with persona text from default_persona()
- [ ] Step 4: Update build_system_prompt to accept skill_context param and remove hardcoded Chinese text
- [ ] Step 5: Commit

---

## Task 11: apply_skill_proposals Checks evolvable

**Files:**
- Modify: agent/cognition/skill_evolution.py:153-197 (apply_skill_proposals)
- Modify: tests/test_skill_proposals.py

- [ ] Step 1: Write failing test: non-evolvable skill should not be auto-applied
- [ ] Step 2: Update apply_skill_proposals to parse evolvable from front-matter via parse_front_matter()
- [ ] Step 3: Skip proposals where target skill has evolvable=false
- [ ] Step 4: Change interface: target_skill_root (required, replaces skill_root), audit_skill_root (optional)
- [ ] Step 5: Run tests
- [ ] Step 6: Commit

---

## Task 12: Integration Test - Full Version Battle Flow

**Files:**
- Create: tests/test_agent_version_integration.py

- [ ] Step 1: Write end-to-end test: create baseline -> create candidate -> build VersionSpec -> evaluate_promotion -> update_manifest_status
- [ ] Step 2: Run test
- [ ] Step 3: Commit


---

## Task 8B: Manifest Runtime Flags to SelfPlayConfig

**Files:**
- Modify: agent/evaluation/version_battle.py (run_version_battle)

- [ ] Step 1: Write failing test: version_spec_from_manifest produces spec with tot_enabled, got_enabled, got_trigger_policy
- [ ] Step 2: Extend VersionSpec with tot_enabled, got_enabled, got_trigger_policy, got_trigger_threshold fields
- [ ] Step 3: In run_version_battle, apply manifest runtime flags to SelfPlayConfig or pass through to create_agents
- [ ] Step 4: Run tests
- [ ] Step 5: Commit

---

## Task 9B: Version Rollback

**Files:**
- Modify: agent/versioning/manifest.py

- [ ] Step 1: Write failing test: rollback_version archives current validated and restores target
- [ ] Step 2: Implement rollback_version(current_validated, target, versions_root, reason) that sets current to archived, target to validated
- [ ] Step 3: Manifest records rollback_source and rollback_reason
- [ ] Step 4: Run tests
- [ ] Step 5: Commit

---

## Task 10B: Version Freeze Enforcement

**Files:**
- Modify: agent/evaluation/selfplay.py

- [ ] Step 1: Write failing test: selfplay run rejects skill_dir change mid-run
- [ ] Step 2: In run_selfplay, assert skill_dir is set once at start and does not change across games
- [ ] Step 3: Document the freeze constraint in SelfPlayConfig docstring
- [ ] Step 4: Run tests
- [ ] Step 5: Commit

---

## Task 10C: Dream Layering Config

**Files:**
- Modify: agent/evaluation/selfplay.py (SelfPlayConfig defaults)

- [ ] Step 1: Verify SelfPlayConfig.enable_dream defaults to False (already done)
- [ ] Step 2: Add SelfPlayConfig.enable_batch_dream: bool = False for batch-level dream
- [ ] Step 3: In selfplay, skip per-game dream when enable_dream=False; batch dream runs post-selfplay when enable_batch_dream=True
- [ ] Step 4: Run tests
- [ ] Step 5: Commit
