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
})
