import { describe, expect, it, vi } from 'vitest'
import { useEvolutionWorkbench } from '../../../src/composables/useEvolutionWorkbench'

function responseFor(path: string) {
  if (path === '/roles') return { roles: ['seer'] }
  if (path === '/settings/model-profiles?compact=true') return { profiles: [] }
  if (path.startsWith('/evolution-runs?')) {
    return {
      runs: [{ run_id: 'run-1', role: 'seer', status: 'interrupted', interrupted: true }],
      batches: [],
      pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
    }
  }
  if (path === '/evolution-runs/run-1') {
    return {
      run_id: 'run-1',
      role: 'seer',
      status: 'interrupted',
      interrupted: true,
      overall_progress: { percent: 57, stage: 'battling' },
      progress: { completed_games: 20, target_games: 20 }
    }
  }
  if (path === '/evolution-runs/run-1/diff') return { diffs: [] }
  if (path === '/evolution-runs/run-1/proposals') return { proposals: [] }
  if (path.includes('/evolution-runs/run-1/games')) {
    return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
  }
  if (path === '/roles/seer/versions') return { versions: [] }
  if (path === '/roles/seer/leaderboard') return { entries: [] }
  throw new Error(`Unexpected request: ${path}`)
}

describe('useEvolutionWorkbench lazy loading', () => {
  it('loads only core run data before a tab requests its artifact', async () => {
    const calls: string[] = []
    const apiFetch = vi.fn(async (path: string) => {
      calls.push(path)
      return responseFor(path)
    })
    const workbench = useEvolutionWorkbench({ apiFetch, installLifecycle: false })

    await workbench.refreshAll()

    expect(calls).toContain('/roles')
    expect(calls).toContain('/evolution-runs/run-1')
    expect(calls.some((path) => path.endsWith('/diff'))).toBe(false)
    expect(calls.some((path) => path.endsWith('/proposals'))).toBe(false)
    expect(calls.some((path) => path.includes('/games'))).toBe(false)
    expect(workbench.selectedRun.value.overallProgressPercent).toBe(57)
    expect(workbench.selectedRun.value.canResume).toBe(true)

    await workbench.ensureEvolutionTabLoaded('review')
    expect(calls.filter((path) => path.endsWith('/proposals'))).toHaveLength(1)

    await workbench.ensureEvolutionTabLoaded('samples')
    const sampleCalls = calls.filter((path) => path.includes('/games'))
    expect(sampleCalls).toHaveLength(1)
    expect(sampleCalls[0]).toContain('phase=training')

    await workbench.selectSampleGame('candidate')
    const battleCalls = calls.filter((path) => path.includes('/games'))
    expect(battleCalls).toHaveLength(2)
    expect(battleCalls[1]).toContain('phase=battle')
    expect(battleCalls[1]).toContain('side=candidate')
  })
})
