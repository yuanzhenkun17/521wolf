// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ApiErrorPanel from '../../src/components/ApiErrorPanel.vue'

const retryLabel = '再试一次'

function mountPanel(props = {}) {
  return mount(ApiErrorPanel, {
    props: {
      error: '网络异常',
      retryLabel,
      ...props,
    },
  })
}

describe('ApiErrorPanel', () => {
  it('emits retry when the retry button is clicked', async () => {
    const wrapper = mountPanel()

    await wrapper.get('button.api-error-panel__retry').trigger('click')

    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it.each([
    { prop: 'retrying', props: { retrying: true } },
    { prop: 'retryDisabled', props: { retryDisabled: true } },
  ])('disables retry and does not emit when $prop is true', async ({ props }) => {
    const wrapper = mountPanel(props)
    const retryButton = wrapper.get('button.api-error-panel__retry')

    expect(retryButton.attributes('disabled')).toBeDefined()

    await retryButton.trigger('click')

    expect(wrapper.emitted('retry')).toBeUndefined()
  })

  it('does not emit more retries after retrying is enabled', async () => {
    const wrapper = mountPanel()
    const retryButton = wrapper.get('button.api-error-panel__retry')

    await retryButton.trigger('click')
    await wrapper.setProps({ retrying: true })
    await retryButton.trigger('click')

    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
