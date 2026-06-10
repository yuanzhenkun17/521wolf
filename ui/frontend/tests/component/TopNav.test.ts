// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { describe, expect, it } from 'vitest'

import TopNav from '../../src/components/TopNav.vue'
import { useGameStore, useSessionStore } from '../../src/stores'
import type { Game } from '../../src/types/game'

const EmptyRoute = defineComponent({ template: '<div />' })

async function createTestRouter(path: string): Promise<Router> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'lobby', component: EmptyRoute },
      { path: '/match', name: 'match', component: EmptyRoute },
      { path: '/logs', name: 'logs', component: EmptyRoute },
      { path: '/benchmark', name: 'benchmark', component: EmptyRoute },
      { path: '/evolution', name: 'evolution', component: EmptyRoute },
      { path: '/missing', name: 'missing', component: EmptyRoute },
    ],
  })
  await router.push(path)
  await router.isReady()
  return router
}

function gameFixture(id: string, overrides: Partial<Game> = {}): Game {
  return {
    game_id: id,
    mode: 'watch',
    status: 'running',
    phase: 'night',
    player_count: 2,
    players: [],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    ...overrides,
  }
}

async function mountTopNav(path: string, props = {}, setupStores: () => void = () => {}) {
  const router = await createTestRouter(path)
  const pinia = createPinia()
  setActivePinia(pinia)
  setupStores()
  return mount(TopNav, {
    props: {
      variant: 'lobby',
      activeView: 'lobby',
      activeSession: {},
      ...props,
    },
    global: {
      plugins: [pinia, router],
    },
  })
}

function navButton(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll('button.nav-button').find((item) => item.text().includes(label))
  if (!button) throw new Error(`missing nav button: ${label}`)
  return button
}

describe('TopNav router active state', () => {
  it('uses the current router route before the legacy activeView prop', async () => {
    const wrapper = await mountTopNav('/benchmark', { activeView: 'logs' })
    const benchmarkButton = navButton(wrapper, '评测')
    const logsButton = navButton(wrapper, '日志')

    expect(benchmarkButton.classes()).toContain('active')
    expect(benchmarkButton.attributes('aria-current')).toBe('page')
    expect(benchmarkButton.attributes('aria-label')).toContain('当前页面')
    expect(logsButton.classes()).not.toContain('active')
  })

  it('falls back to activeView while unknown routes are still in transition', async () => {
    const wrapper = await mountTopNav('/missing', { activeView: 'evolution' })
    const evolutionButton = navButton(wrapper, '自进化')

    expect(evolutionButton.classes()).toContain('active')
    expect(evolutionButton.attributes('aria-current')).toBe('page')
  })

  it('uses legacy route hashes before the store while hash routing is still supported', async () => {
    const wrapper = await mountTopNav('/', { activeView: 'lobby' }, () => {
      useSessionStore().setView('logs')
    })
    const lobbyButton = navButton(wrapper, '大厅')

    expect(lobbyButton.classes()).toContain('active')
    expect(lobbyButton.attributes('aria-current')).toBe('page')
  })

  it('keeps legacy hash routes as router-owned active navigation', async () => {
    const wrapper = await mountTopNav('/#logs?game_id=game-7', { activeView: 'lobby' }, () => {
      useSessionStore().setView('benchmark')
    })
    const logsButton = navButton(wrapper, '日志')
    const benchmarkButton = navButton(wrapper, '评测')

    expect(logsButton.classes()).toContain('active')
    expect(logsButton.attributes('aria-current')).toBe('page')
    expect(benchmarkButton.classes()).not.toContain('active')
  })

  it('prefers concrete router paths over compatibility hashes', async () => {
    const wrapper = await mountTopNav('/benchmark#logs?game_id=game-7', { activeView: 'logs' })
    const benchmarkButton = navButton(wrapper, '评测')
    const logsButton = navButton(wrapper, '日志')

    expect(benchmarkButton.classes()).toContain('active')
    expect(benchmarkButton.attributes('aria-current')).toBe('page')
    expect(logsButton.classes()).not.toContain('active')
  })

  it('uses Pinia game state for the match exit control before App props are removed', async () => {
    const wrapper = await mountTopNav('/match', { variant: 'match' }, () => {
      useSessionStore().setActiveSession({
        gameId: 'game-store',
        mode: 'watch',
        running: true,
        sseConnected: true,
      })
      useGameStore().setGame(gameFixture('game-store'))
    })

    expect(wrapper.find('button.topbar-exit-game').exists()).toBe(true)
    expect(wrapper.find('.active-session-pill').exists()).toBe(false)
  })

  it('keeps legacy navigation events while route ownership is migrating', async () => {
    const wrapper = await mountTopNav('/benchmark')

    await navButton(wrapper, '评测').trigger('click')

    expect(wrapper.emitted('open-benchmark')).toHaveLength(1)
  })
})
