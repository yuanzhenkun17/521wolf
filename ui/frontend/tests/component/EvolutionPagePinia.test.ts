// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import EvolutionPage from '../../src/pages/EvolutionPage.vue'
import { useEvolutionStore } from '../../src/stores/evolution'
import type { EvolutionRun } from '../../src/types/evolution'

const mockWorkbench = vi.hoisted(() => ({
  loading: { value: false },
  error: { value: '' },
  notice: { value: { type: '', message: '' } },
  roles: { value: ['werewolf'] },
  roleRows: { value: [{ key: 'werewolf', label: '狼人' }] },
  versionsByRole: { value: {} },
  runs: { value: [] as EvolutionRun[] },
  runRows: { value: [] as EvolutionRun[] },
  selectedRole: { value: 'werewolf' },
  selectedRunId: { value: 'run-1' },
  selectedRun: { value: null as EvolutionRun | null },
  selectedRunSummary: { value: { id: 'run-1', statusLabel: '运行中' } },
  selectedProposalReview: { value: { source: 'api' } },
  selectedGames: { value: { training: [{ id: 'sample-1' }] } },
  selectedCanPromote: { value: true },
  selectedPromoteDisabledReason: { value: '' },
  selectedCanReject: { value: true },
  selectedRejectDisabledReason: { value: '' },
  selectedCanTerminate: { value: true },
  selectedTerminateDisabledReason: { value: '' },
  selectedRollbackDisabledReason: { value: '不可回滚' },
  evolutionDeepLinkTarget: { value: null as { panel?: string } | null },
  refreshAll: vi.fn(),
  selectRole: vi.fn(),
  selectRun: vi.fn(),
  consumeEvolutionDeepLink: vi.fn(),
  applyEvolutionDeepLink: vi.fn()
}))

vi.mock('../../src/composables/useEvolutionWorkbench.ts', () => ({
  useEvolutionWorkbench: () => mockWorkbench
}))

vi.mock('../../src/components/lab/LabWorkbenchShell.vue', () => ({
  default: {
    name: 'LabWorkbenchShell',
    props: ['activeTab'],
    emits: ['update:activeTab'],
    template: '<section data-test="lab-shell"><slot /></section>'
  }
}))

vi.mock('../../src/components/evolution/EvolutionWorkbenchShell.vue', () => ({
  default: {
    name: 'EvolutionWorkbenchShell',
    props: [
      'activeTab',
      'title',
      'tabs',
      'roles',
      'runRows',
      'selectedRole',
      'selectedRun',
      'selectedRunSummary',
      'selectedProposalReview',
      'selectedGames',
      'selectedCanPromote',
      'selectedPromoteDisabledReason',
      'selectedCanReject',
      'selectedRejectDisabledReason',
      'selectedCanTerminate',
      'selectedTerminateDisabledReason',
      'selectedRollbackDisabledReason',
      'error',
      'notice'
    ],
    emits: ['refresh', 'select-role', 'update:activeTab'],
    template: `
      <section
        data-test="evo-shell"
        :data-selected-role="selectedRole"
        :data-run-id="selectedRun?.id || ''"
        :data-role-count="String(roles.length)"
        :data-run-count="String(runRows.length)"
        :data-can-promote="String(selectedCanPromote)"
        :data-can-reject="String(selectedCanReject)"
        :data-can-terminate="String(selectedCanTerminate)"
        :data-error="error"
        :data-notice="notice?.message || ''"
      >
        <button data-test="select-role" type="button" @click="$emit('select-role', 'seer')" />
        <button data-test="refresh" type="button" @click="$emit('refresh')" />
        <slot />
      </section>
    `
  }
}))

vi.mock('../../src/components/evolution/EvolutionConsolePanel.vue', () => ({
  default: {
    name: 'EvolutionConsolePanel',
    props: [
      'selectedIsBatch',
      'selectedCanReview',
      'selectedCanPromote',
      'selectedPromoteDisabledReason',
      'selectedCanTerminate'
    ],
    template: `
      <section
        data-test="evo-console"
        :data-selected-is-batch="String(selectedIsBatch)"
        :data-can-review="String(selectedCanReview)"
        :data-can-promote="String(selectedCanPromote)"
        :data-can-terminate="String(selectedCanTerminate)"
      />
    `
  }
}))

vi.mock('../../src/components/evolution/EvolutionEventsPanel.vue', () => ({
  default: {
    name: 'EvolutionEventsPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

vi.mock('../../src/components/evolution/EvolutionLeaderboardPanel.vue', () => ({
  default: {
    name: 'EvolutionLeaderboardPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

vi.mock('../../src/components/evolution/EvolutionProposalReviewPanel.vue', () => ({
  default: {
    name: 'EvolutionProposalReviewPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

vi.mock('../../src/components/evolution/EvolutionRunsPanel.vue', () => ({
  default: {
    name: 'EvolutionRunsPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

vi.mock('../../src/components/evolution/EvolutionSamplesPanel.vue', () => ({
  default: {
    name: 'EvolutionSamplesPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

vi.mock('../../src/components/evolution/EvolutionVersionsPanel.vue', () => ({
  default: {
    name: 'EvolutionVersionsPanel',
    template: '<section data-test="evo-panel-stub" />'
  }
}))

function evolutionRunFixture(id: string, overrides: Partial<EvolutionRun> = {}): EvolutionRun {
  return {
    id,
    run_id: id,
    entityType: 'run',
    isBatch: false,
    childRuns: [],
    childRunCount: 0,
    role: 'werewolf',
    roles: ['werewolf'],
    displayRole: '狼人',
    status: 'running',
    currentStage: 'training',
    recommendation: 'pending',
    recommendationLabel: '等待',
    progressPercent: 0,
    progressLabel: '0%',
    overallProgressPercent: 0,
    stageProgressPercent: 0,
    trainingProgressPercent: 0,
    battleProgressPercent: 0,
    trainingGameRequested: 0,
    trainingGameCompleted: 0,
    battleGameRequested: 0,
    battleGameCompleted: 0,
    proposalCount: 0,
    diffCount: 0,
    diagnosticCount: 0,
    warningCount: 0,
    errorCount: 0,
    isReviewing: false,
    isTerminal: false,
    isActive: true,
    ...overrides
  }
}

function resetMockWorkbench() {
  const run = evolutionRunFixture('run-1', { progressLabel: 'store run' })

  mockWorkbench.loading.value = false
  mockWorkbench.error.value = ''
  mockWorkbench.notice.value = { type: '', message: '' }
  mockWorkbench.roles.value = ['werewolf']
  mockWorkbench.roleRows.value = [{ key: 'werewolf', label: '狼人' }]
  mockWorkbench.versionsByRole.value = {}
  mockWorkbench.runs.value = [run]
  mockWorkbench.runRows.value = [run]
  mockWorkbench.selectedRole.value = 'werewolf'
  mockWorkbench.selectedRunId.value = 'run-1'
  mockWorkbench.selectedRun.value = run
  mockWorkbench.selectedRunSummary.value = { id: 'run-1', statusLabel: '运行中' }
  mockWorkbench.selectedProposalReview.value = { source: 'api' }
  mockWorkbench.selectedGames.value = { training: [{ id: 'sample-1' }] }
  mockWorkbench.selectedCanPromote.value = true
  mockWorkbench.selectedPromoteDisabledReason.value = ''
  mockWorkbench.selectedCanReject.value = true
  mockWorkbench.selectedRejectDisabledReason.value = ''
  mockWorkbench.selectedCanTerminate.value = true
  mockWorkbench.selectedTerminateDisabledReason.value = ''
  mockWorkbench.selectedRollbackDisabledReason.value = '不可回滚'
  mockWorkbench.evolutionDeepLinkTarget.value = null
  mockWorkbench.refreshAll.mockReset()
  mockWorkbench.selectRole.mockReset()
  mockWorkbench.selectRun.mockReset()
  mockWorkbench.consumeEvolutionDeepLink.mockReset()
  mockWorkbench.applyEvolutionDeepLink.mockReset()
}

const EmptyRoute = defineComponent({ template: '<div />' })

async function createTestRouter(path: string): Promise<Router> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/evolution', name: 'evolution', component: EmptyRoute }]
  })
  await router.push(path)
  await router.isReady()
  return router
}

async function mountEvolutionPage() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = await createTestRouter('/evolution')

  const wrapper = mount(EvolutionPage, {
    global: {
      plugins: [pinia, router]
    }
  })
  await flushPromises()

  return { wrapper, store: useEvolutionStore() }
}

describe('EvolutionPage Pinia handoff', () => {
  beforeEach(() => {
    resetMockWorkbench()
  })

  it('hydrates shell props from the evolution store and forwards shell actions', async () => {
    const { wrapper, store } = await mountEvolutionPage()
    const shell = wrapper.find('[data-test="evo-shell"]')
    const consolePanel = wrapper.find('[data-test="evo-console"]')

    expect(store.selectedRole).toBe('werewolf')
    expect(store.selectedRun?.id).toBe('run-1')
    expect(shell.attributes('data-selected-role')).toBe('werewolf')
    expect(shell.attributes('data-run-id')).toBe('run-1')
    expect(shell.attributes('data-role-count')).toBe('1')
    expect(shell.attributes('data-run-count')).toBe('1')
    expect(shell.attributes('data-can-promote')).toBe('true')
    expect(consolePanel.attributes('data-can-review')).toBe('true')
    expect(consolePanel.attributes('data-selected-is-batch')).toBe('false')
    expect(mockWorkbench.refreshAll).toHaveBeenCalledTimes(1)

    await wrapper.find('[data-test="select-role"]').trigger('click')

    expect(store.selectedRole).toBe('seer')
    expect(mockWorkbench.selectRole).toHaveBeenCalledWith('seer')

    await wrapper.find('[data-test="refresh"]').trigger('click')

    expect(mockWorkbench.refreshAll).toHaveBeenCalledTimes(2)
  })
})
