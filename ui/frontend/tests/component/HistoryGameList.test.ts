// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import HistoryGameList from '../../src/components/HistoryGameList.vue'
import { useHistoryStore } from '../../src/stores'
import type { HistoryGame } from '../../src/types/history'

function gameFixture(gameId: string, overrides: Partial<HistoryGame> = {}): HistoryGame {
  return {
    game_id: gameId,
    mode: 'watch',
    status: 'finished',
    phase: 'day',
    player_count: 0,
    players: [],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    event_count: 0,
    decision_count: 0,
    phases: [],
    history_pages: [],
    started_at: '2026-06-10T08:00:00.000Z',
    ...overrides,
  } as HistoryGame
}

function mountHistoryGameList(props = {}, setupStore: (store: ReturnType<typeof useHistoryStore>) => void = () => {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useHistoryStore()
  setupStore(store)

  const wrapper = mount(HistoryGameList, {
    props,
    global: {
      plugins: [pinia],
    },
  })

  return { wrapper, store }
}

function sourceTab(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll('.history-source-tabs button').find((item) => item.text().includes(label))
  if (!button) throw new Error(`missing source tab: ${label}`)
  return button
}

describe('HistoryGameList Pinia fallback', () => {
  it('renders games, selected state, and loading guard from the history store when props are absent', async () => {
    const { wrapper } = mountHistoryGameList(
      {},
      (store) => {
        store.setGames([
          gameFixture('store-game-a', { mode: 'watch' }),
          gameFixture('store-game-b', { mode: 'play' }),
        ])
        store.selectedHistoryGameId = 'store-game-b'
        store.loading = true
        store.loadingMore = true
        store.sourceFilter = 'benchmark'
        store.pagination = { total: 3, limit: 1, offset: 1, returned: 1 }
        store.counts = { all: 3, normal: 1, benchmark: 2, evolution: 0 }
        store.notice = { type: 'warning', message: 'store notice' }
      }
    )

    const items = wrapper.findAll('.history-game-item')
    expect(items).toHaveLength(2)
    expect(items[1].classes()).toContain('active')
    expect(sourceTab(wrapper, '批量评测').classes()).toContain('active')
    expect(wrapper.find('.history-notice').text()).toContain('store notice')
    expect(wrapper.find('.history-pagination').exists()).toBe(false)
    expect(wrapper.find('.history-page-meta').exists()).toBe(false)
    expect(wrapper.find('.empty-log').exists()).toBe(false)
    expect(wrapper.findAll('button.history-page-step')).toHaveLength(0)

    await sourceTab(wrapper, '批量评测').trigger('click')

    expect(wrapper.emitted('change-source')).toBeUndefined()
  })

  it('prefers explicitly passed props over history store state', async () => {
    const { wrapper } = mountHistoryGameList(
      {
        games: [
          gameFixture('prop-game-a', {
            log_source: 'benchmark',
            log_source_label: '评测来源',
          }),
        ],
        selectedGameId: 'prop-game-a',
        loading: false,
        sourceFilter: 'all',
        pagination: { total: 1, limit: 1, offset: 0, returned: 1 },
        notice: { type: 'success', message: 'prop notice' },
      },
      (store) => {
        store.setGames([
          gameFixture('store-game-a'),
          gameFixture('store-game-b'),
        ])
        store.selectedHistoryGameId = 'store-game-b'
        store.loading = true
        store.sourceFilter = 'benchmark'
        store.pagination = { total: 9, limit: 3, offset: 3, returned: 3 }
        store.notice = { type: 'warning', message: 'store notice' }
      }
    )

    const items = wrapper.findAll('.history-game-item')
    expect(items).toHaveLength(1)
    expect(items[0].classes()).toContain('active')
    expect(items[0].text()).toContain('评测来源')
    expect(sourceTab(wrapper, '全部').classes()).toContain('active')
    expect(wrapper.find('.history-notice').text()).toContain('prop notice')
    expect(wrapper.find('.history-pagination').exists()).toBe(false)
    expect(wrapper.find('.history-page-meta').exists()).toBe(false)

    await sourceTab(wrapper, '批量评测').trigger('click')

    expect(wrapper.emitted('change-source')).toEqual([['benchmark']])
  })
})
