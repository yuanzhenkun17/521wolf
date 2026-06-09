import assert from 'node:assert/strict'
import test from 'node:test'
import { useEvolutionWorkbench } from '../src/composables/useEvolutionWorkbench.ts'

test('evolution versions disable rollback for baseline shadow and canary stages', async () => {
  const apiFetch = async (path) => {
    if (path === '/roles/overview') {
      return {
        roles: ['seer'],
        versions: {
          seer: [
            { version_id: 'seer-baseline', is_baseline: true, release_stage: 'baseline' },
            { version_id: 'seer-shadow', release_stage: 'SHADOW' },
            { version_id: 'seer-canary', provenance: { release_stage: 'canary' } },
            { version_id: 'seer-draft', release_stage: 'draft' }
          ]
        },
        leaderboards: { seer: { entries: [] } }
      }
    }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return { runs: [], batches: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  const byId = Object.fromEntries(workbench.selectedRoleVersions.value.map((version) => [version.version_id, version]))

  assert.equal(byId['seer-baseline'].rollbackDisabled, true)
  assert.equal(byId['seer-baseline'].rollbackLabel, '当前基线')
  assert.equal(byId['seer-baseline'].rollbackDisabledReason, '当前基线')

  assert.equal(byId['seer-shadow'].releaseStage, 'shadow')
  assert.equal(byId['seer-shadow'].rollbackDisabled, true)
  assert.equal(byId['seer-shadow'].rollbackLabel, '影子不可回滚')
  assert.equal(byId['seer-shadow'].rollbackDisabledReason, '影子不可回滚')

  assert.equal(byId['seer-canary'].releaseStage, 'canary')
  assert.equal(byId['seer-canary'].rollbackDisabled, true)
  assert.equal(byId['seer-canary'].rollbackLabel, '灰度不可回滚')
  assert.equal(byId['seer-canary'].rollbackDisabledReason, '灰度不可回滚')

  assert.equal(byId['seer-draft'].rollbackDisabled, false)
  assert.equal(byId['seer-draft'].rollbackLabel, '回滚')
  assert.equal(byId['seer-draft'].rollbackDisabledReason, '')
})
