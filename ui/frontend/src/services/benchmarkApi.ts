import type { BenchmarkRequest } from '../types/benchmark'
import type { QueryParams, ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

type BenchmarkQuery = Record<string, string | number | boolean | null | undefined>

function benchmarkQueryParams(query: BenchmarkQuery = {}): QueryParams {
  return query
}

export function createBenchmarkService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    suites() {
      return client.fetch('/benchmarks')
    },
    seedSets() {
      return client.fetch('/benchmark/seed-sets')
    },
    leaderboard(query: BenchmarkQuery = {}) {
      return client.fetch('/leaderboards', { query: benchmarkQueryParams(query) })
    },
    runs(query: BenchmarkQuery = {}) {
      return client.fetch('/evolution-runs', { query: benchmarkQueryParams({ ...query, source: 'benchmark' }) })
    },
    launch(payload: BenchmarkRequest) {
      return client.fetch('/benchmark', { method: 'POST', body: payload })
    },
    run(id: string) {
      return client.fetch(`/benchmark/batch/${encodeURIComponent(id)}`)
    },
    diagnostics(id: string, query: BenchmarkQuery = {}) {
      return client.fetch(`/benchmark/batch/${encodeURIComponent(id)}/diagnostics`, { query: benchmarkQueryParams(query) })
    },
    report(id: string) {
      return client.fetch(`/benchmark/batch/${encodeURIComponent(id)}/report`)
    },
    snapshots(query: BenchmarkQuery = {}) {
      return client.fetch('/benchmark/snapshots', { query: benchmarkQueryParams(query) })
    }
  }
}

export type BenchmarkService = ReturnType<typeof createBenchmarkService>
