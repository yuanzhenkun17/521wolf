// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import LobbyPage from '../../src/pages/LobbyPage.vue'
import { useGameStore, useSessionStore } from '../../src/stores'

function mountLobbyPage(props = {}, setupStores: () => void = () => {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setupStores()

  return mount(LobbyPage, {
    props,
    global: {
      plugins: [pinia]
    }
  })
}

function modeButton(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll('button.mode-card').find((item) => item.text().includes(label))
  if (!button) throw new Error(`missing lobby mode button: ${label}`)
  return button
}

describe('LobbyPage Pinia state handoff', () => {
  it('uses Pinia backend and loading state when App runtime props are absent', async () => {
    let sessionStore!: ReturnType<typeof useSessionStore>
    let gameStore!: ReturnType<typeof useGameStore>
    const apiFetch = vi.fn().mockResolvedValue({
      roles: [],
      versions: {},
      leaderboards: {}
    })

    const wrapper = mountLobbyPage({ apiFetch }, () => {
      sessionStore = useSessionStore()
      gameStore = useGameStore()
      sessionStore.setBackendMode('offline')
      gameStore.setLoading(true)
    })

    await flushPromises()

    expect(apiFetch).not.toHaveBeenCalled()
    expect(modeButton(wrapper, '观战模式').attributes('disabled')).toBeDefined()
    expect(modeButton(wrapper, '观战模式').text()).toContain('后端未连接')

    gameStore.setLoading(false)
    sessionStore.setBackendMode('api')
    await nextTick()
    await flushPromises()

    expect(apiFetch).toHaveBeenCalledWith('/roles/overview')
    expect(modeButton(wrapper, '观战模式').attributes('disabled')).toBeUndefined()
    expect(modeButton(wrapper, '观战模式').text()).toContain('观看智能体对局')
  })

  it('keeps explicit legacy lobby props ahead of store state during migration', async () => {
    const wrapper = mountLobbyPage({ backendMode: 'mock', loading: false }, () => {
      useSessionStore().setBackendMode('offline')
      useGameStore().setLoading(true)
    })

    await flushPromises()

    const watchButton = modeButton(wrapper, '观战模式')
    expect(watchButton.attributes('disabled')).toBeUndefined()
    expect(watchButton.text()).toContain('观看智能体对局')
  })

  it('blocks starting from a selected model profile when preflight fails', async () => {
    const apiFetch = vi.fn(async (path: string) => {
      if (path === '/roles/overview') return { roles: [], versions: {}, leaderboards: {} }
      if (path === '/settings/model-profiles') {
        return {
          profiles: [{
            profile_id: 'profile-game-main',
            name: '主游戏模型',
            model: 'qwen-max',
            enabled: true,
            has_api_key: true,
            default_scopes: { game_decision: true },
            last_test_status: 'ok'
          }]
        }
      }
      if (path.startsWith('/health/preflight?scope=game_start')) {
        return {
          ready: false,
          status: 'error',
          gate: {
            ready: false,
            status: 'error',
            blockers: ['llm_connectivity'],
            warnings: [],
            actions: ['打开设置页，测试模型连接。']
          },
          checks: { llm_connectivity: { status: 'error' } }
        }
      }
      throw new Error(`unexpected ${path}`)
    })

    const wrapper = mountLobbyPage({ apiFetch, runtimeHealth: { gates: {} } }, () => {
      useSessionStore().setBackendMode('api')
      useGameStore().setLoading(false)
    })

    await flushPromises()

    const watchButton = modeButton(wrapper, '观战模式')
    expect(watchButton.attributes('disabled')).toBeDefined()
    await watchButton.trigger('click')
    expect(wrapper.emitted('start-mode')).toBeUndefined()
  })
})
