import type { BenchmarkRequest } from '../types/benchmark'
import type { ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

export function createBenchmarkService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    suites() {
      return client.fetch('/benchmarks')
    },
    seedSets() {
      return client.fetch('/benchmark-seed-sets')
    },
    leaderboard(query: Record<string, string | number | boolean | null | undefined> = {}) {
      return client.fetch('/benchmark-leaderboard', { query })
    },
    runs(query: Record<string, string | number | boolean | null | undefined> = {}) {
      return client.fetch('/benchmark-runs', { query })
    },
    launch(payload: BenchmarkRequest) {
      return client.fetch('/benchmark-runs', { method: 'POST', body: payload })
    },
    run(id: string) {
      return client.fetch(`/benchmark-runs/${encodeURIComponent(id)}`)
    },
    diagnostics(id: string, query: Record<string, string | number | boolean | null | undefined> = {}) {
      return client.fetch(`/benchmark-runs/${encodeURIComponent(id)}/diagnostics`, { query })
    },
    report(id: string) {
      return client.fetch(`/benchmark-runs/${encodeURIComponent(id)}/report`)
    },
    snapshots(query: Record<string, string | number | boolean | null | undefined> = {}) {
      return client.fetch('/benchmark-snapshots', { query })
    }
  }
}

export type BenchmarkService = ReturnType<typeof createBenchmarkService>
