// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import LogsPage from '../../src/pages/LogsPage.vue'
import { useHistoryStore } from '../../src/stores'
import type { HistoryGame } from '../../src/types/history'

vi.mock('../../src/components/HistoryGameList.vue', () => ({
  default: {
    name: 'HistoryGameList',
    template: '<aside class="history-game-list-stub" />',
  },
}))

vi.mock('../../src/components/ApiErrorPanel.vue', () => ({
  default: {
    name: 'ApiErrorPanel',
    template: '<section class="api-error-panel-stub" />',
  },
}))

vi.mock('../../src/components/PhaseTabs.vue', () => ({
  default: {
    name: 'PhaseTabs',
    props: ['pages', 'selectedPageKey'],
    template: '<nav class="phase-tabs-stub" :data-page-count="String(pages.length)" :data-selected="selectedPageKey" />',
  },
}))

vi.mock('../../src/components/SeatLedger.vue', () => ({
  default: {
    name: 'SeatLedger',
    props: ['players', 'aliveMap', 'selectedPage'],
    template: '<section class="seat-ledger-stub" :data-player-count="String(players.length)" :data-alive-count="String(Object.keys(aliveMap || {}).length)" :data-page-key="selectedPage?.key || \'\'" />',
  },
}))

vi.mock('../../src/components/MultiAssess.vue', () => ({
  default: {
    name: 'MultiAssess',
    props: ['scores'],
    template: '<section class="multi-assess-stub" :data-score-count="String(scores.length)" />',
  },
}))

vi.mock('../../src/components/NightSection.vue', () => ({
  default: { name: 'NightSection', template: '<section class="night-section-stub" />' },
}))
vi.mock('../../src/components/SpeechSection.vue', () => ({
  default: { name: 'SpeechSection', template: '<section class="speech-section-stub" />' },
}))
vi.mock('../../src/components/VoteSection.vue', () => ({
  default: { name: 'VoteSection', template: '<section class="vote-section-stub" />' },
}))
vi.mock('../../src/components/history/EvidenceContextBar.vue', () => ({
  default: { name: 'EvidenceContextBar', template: '<section class="evidence-context-stub" />' },
}))

function gameFixture(gameId: string, overrides: Partial<HistoryGame> = {}): HistoryGame {
  return {
    game_id: gameId,
    mode: 'watch',
    status: 'finished',
    phase: 'night',
    player_count: 2,
    players: [
      { id: 1, seat: 1, name: 'Player 1', role_hint: '平民', alive: true, is_human: false, is_sheriff: false },
      { id: 2, seat: 2, name: 'Player 2', role_hint: '狼人', alive: true, is_human: false, is_sheriff: false },
    ],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    event_count: 0,
    decision_count: 0,
    phases: [],
    history_pages: [],
    ...overrides,
  } as HistoryGame
}

function mountLogsPage(props = {}, setupStore: (store: ReturnType<typeof useHistoryStore>) => void = () => {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useHistoryStore()
  setupStore(store)

  const wrapper = mount(LogsPage, {
    props,
    global: {
      plugins: [pinia],
      stubs: {
        ReviewReportPanel: {
          name: 'ReviewReportPanel',
          props: ['report'],
          template: '<section class="review-report-stub" :data-report-id="report?.report_id || \'\'" />',
        },
        GameArchivePanel: {
          name: 'GameArchivePanel',
          props: ['archive'],
          template: '<section class="game-archive-stub" :data-archive-id="archive?.archive_id || \'\'" />',
        },
      },
    },
  })

  return { wrapper, store }
}

describe('LogsPage Pinia fallback', () => {
  it('keeps empty store-owned detail state ahead of stale runtime props', async () => {
    const selectedGame = gameFixture('store-history')
    const { wrapper } = mountLogsPage(
      {
        historyLogs: [{ message: 'stale runtime log' }],
        pageNightActions: [{ action: 'stale_night_action' }],
        playerAssessmentScores: [{ player: { id: 1 }, score: 99 }],
        activeAssessScores: [{ player: { id: 1 }, score: 99 }],
        playerAliveAtPage: { 1: true, 2: false },
        reviewByGameId: { 'store-history': { report_id: 'stale-review' } },
        archiveByGameId: { 'store-history': { archive_id: 'stale-archive' } },
        reviewLoading: true,
        archiveLoading: true,
      },
      (store) => {
        store.hydrateFromRuntime({
          gameHistory: [selectedGame],
          selectedHistoryGameId: 'store-history',
          selectedHistoryGame: selectedGame,
          historyWorkspaceTab: 'phase',
          historyPages: [{ key: 'day-1-night', day: 1, phase: 'night' }],
          selectedHistoryPageKey: 'day-1-night',
          selectedHistoryPage: { key: 'day-1-night', day: 1, phase: 'night' },
          historyLogs: [],
          pageNightActions: [],
          playerAssessmentScores: [],
          activeAssessScores: [],
          playerAliveAtPage: {},
          reviewByGameId: {},
          archiveByGameId: {},
          reviewLoading: false,
          archiveLoading: false,
        })
      }
    )

    expect(wrapper.text()).not.toContain('stale runtime log')
    expect(wrapper.find('.multi-assess-stub').exists()).toBe(false)
    expect(wrapper.find('.seat-ledger-stub').attributes('data-alive-count')).toBe('0')

    await wrapper.findAll('.detail-workspace-tabs button').find((button) => button.text().includes('复盘报告'))?.trigger('click')
    expect(wrapper.find('.review-report-stub').attributes('data-report-id')).toBe('')
    expect(wrapper.text()).not.toContain('读取中')

    await wrapper.findAll('.detail-workspace-tabs button').find((button) => button.text().includes('对局档案'))?.trigger('click')
    expect(wrapper.find('.game-archive-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('读取对局档案')
  })

  it('uses bound history store actions before stale action props', async () => {
    const selectedGame = gameFixture('store-history')
    const propLoadReview = vi.fn()
    const storeLoadReview = vi.fn()
    const { wrapper } = mountLogsPage(
      {
        loadReview: propLoadReview,
      },
      (store) => {
        store.hydrateFromRuntime({
          gameHistory: [selectedGame],
          selectedHistoryGameId: 'store-history',
          selectedHistoryGame: selectedGame,
          historyWorkspaceTab: 'phase',
          historyPages: [{ key: 'day-1-night', day: 1, phase: 'night' }],
          selectedHistoryPageKey: 'day-1-night',
          selectedHistoryPage: { key: 'day-1-night', day: 1, phase: 'night' },
        })
        store.bindRuntimeActions({ loadReview: storeLoadReview })
      }
    )

    const reviewButton = wrapper.findAll('.detail-workspace-tabs button').find((button) => button.text().includes('复盘报告'))
    if (!reviewButton) throw new Error('missing review tab')
    await reviewButton.trigger('click')

    expect(storeLoadReview).toHaveBeenCalledWith('store-history')
    expect(propLoadReview).not.toHaveBeenCalled()
  })
})
