import assert from 'node:assert/strict'
import { test } from 'vitest'
import {
  gameStartEligibleRoleVersions,
  gameStartRoleVersionState,
  latestGameStartRoleVersion,
  roleVersionReleaseStage
} from '../src/composables/gameStartRoleVersions.ts'

const baseline = {
  version_id: 'seer-baseline',
  release_stage: 'baseline',
  is_baseline: true,
  created_at: '2026-06-01T00:00:00'
}

const stableCandidate = {
  version_id: 'seer-stable-candidate',
  release_stage: 'draft',
  is_baseline: false,
  created_at: '2026-06-02T00:00:00'
}

const shadow = {
  version_id: 'seer-shadow',
  release_stage: 'shadow',
  is_baseline: false,
  created_at: '2026-06-03T00:00:00'
}

const canary = {
  version_id: 'seer-canary',
  releaseStage: 'canary',
  is_baseline: false,
  created_at: '2026-06-04T00:00:00'
}

test('game start role versions read release stage from backend and normalized shapes', () => {
  assert.equal(roleVersionReleaseStage(shadow), 'shadow')
  assert.equal(roleVersionReleaseStage(canary), 'canary')
  assert.equal(roleVersionReleaseStage({ provenance: { release_stage: 'CANARY' } }), 'canary')
})

test('game start eligible versions exclude shadow and canary releases', () => {
  assert.deepEqual(
    gameStartEligibleRoleVersions([
      baseline,
      shadow,
      canary,
      { version_id: 'seer-provenance-canary', provenance: { release_stage: 'canary' } },
      stableCandidate
    ]).map((version) => version.version_id),
    ['seer-baseline', 'seer-stable-candidate']
  )
})

test('latest game start version ignores newer shadow and canary candidates', () => {
  assert.equal(
    latestGameStartRoleVersion([baseline, stableCandidate, shadow, canary], baseline)?.version_id,
    'seer-stable-candidate'
  )
  assert.equal(
    latestGameStartRoleVersion([baseline, shadow, canary], baseline)?.version_id,
    'seer-baseline'
  )
})

test('custom game start selection cannot turn shadow or canary into role version overrides', () => {
  const state = gameStartRoleVersionState({
    versions: [baseline, stableCandidate, shadow, canary],
    selectedVersionId: 'seer-canary',
    mode: 'custom'
  })

  assert.equal(state.baseline.version_id, 'seer-baseline')
  assert.equal(state.effectiveVersion.version_id, 'seer-baseline')
  assert.equal(state.hasOverride, false)
  assert.deepEqual(
    state.choices.map((version) => version.version_id),
    ['seer-stable-candidate']
  )
})

test('latest mode sends no role override when only experimental versions are newer than baseline', () => {
  const state = gameStartRoleVersionState({
    versions: [baseline, shadow, canary],
    mode: 'latest'
  })

  assert.equal(state.effectiveVersion.version_id, 'seer-baseline')
  assert.equal(state.hasOverride, false)
})
