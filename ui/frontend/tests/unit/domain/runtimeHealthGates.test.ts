import { describe, expect, it } from 'vitest'
import { runtimeHealthGateSummary } from '../../../src/domain/runtimeHealth/gates'

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
    expect(summary.reason).toBe('Open Settings and test the model connection.')
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
})
