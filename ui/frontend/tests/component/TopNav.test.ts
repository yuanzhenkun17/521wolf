// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { describe, expect, it } from 'vitest'

import TopNav from '../../src/components/TopNav.vue'

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

async function mountTopNav(path: string, props = {}) {
  const router = await createTestRouter(path)
  return mount(TopNav, {
    props: {
      variant: 'lobby',
      activeView: 'lobby',
      activeSession: {},
      ...props,
    },
    global: {
      plugins: [router],
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

  it('keeps legacy navigation events while route ownership is migrating', async () => {
    const wrapper = await mountTopNav('/benchmark')

    await navButton(wrapper, '评测').trigger('click')

    expect(wrapper.emitted('open-benchmark')).toHaveLength(1)
  })
})
