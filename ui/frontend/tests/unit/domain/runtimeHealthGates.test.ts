import { describe, expect, it } from 'vitest'
import { runtimeHealthGateSummary, runtimeHealthPreflightStatusText } from '../../../src/domain/runtimeHealth/gates'

describe('runtime health gate summaries', () => {
  it('does not block launch while health is not loaded yet', () => {
    const summary = runtimeHealthGateSummary(null, 'game_start')

    expect(summary.known).toBe(false)
    expect(summary.disabled).toBe(false)
    expect(summary.reason).toBe('')
  })

  it('blocks launch when a runtime gate is explicitly not ready', () => {
    const summary = runtimeHealthGateSummary({
      gates: {
        benchmark_start: {
          ready: false,
          status: 'error',
          blockers: ['llm_connectivity'],
          actions: ['Open Settings and test the model connection.']
        }
      }
    }, 'benchmark_start')

    expect(summary.known).toBe(true)
    expect(summary.disabled).toBe(true)
    expect(summary.blockers).toEqual(['llm_connectivity'])
    expect(summary.reason).toBe('模型连接不可用')
    expect(summary.actions).toEqual(['打开设置页，测试模型连接。'])
  })

  it('surfaces degraded checks without disabling launch', () => {
    const summary = runtimeHealthGateSummary({
      gates: {
        evolution_start: {
          ready: true,
          status: 'degraded',
          blockers: [],
          warnings: ['llm_connectivity']
        }
      }
    }, 'evolution_start')

    expect(summary.disabled).toBe(false)
    expect(summary.warning).toContain('模型连接尚未探测')
  })

  it('localizes failed model preflight status with the gate blocker reason', () => {
    const message = runtimeHealthPreflightStatusText({
      ready: false,
      status: 'error',
      gate: {
        ready: false,
        status: 'error',
        blockers: ['llm_connectivity']
      }
    }, 'benchmark_start')

    expect(message).toBe('模型预检未通过：模型连接不可用')
  })
})
