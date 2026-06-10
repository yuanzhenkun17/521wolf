import { normalizeBenchmarkDiagnosticsResponse, normalizeBenchmarkLeaderboardResponse, normalizeBenchmarkRequest, normalizeBenchmarkRunResponse, normalizeBenchmarkRunsResponse, normalizeBenchmarkSeedRegistry, normalizeBenchmarkSnapshotsResponse, normalizeBenchmarkSuiteList } from '../domain/benchmark/normalizers'
import type { BenchmarkDiagnosticsDto, BenchmarkDiagnosticsResponse, BenchmarkLeaderboardDto, BenchmarkLeaderboardRow, BenchmarkListResponse, BenchmarkRequest, BenchmarkRun, BenchmarkRunResponseDto, BenchmarkRunsDto, BenchmarkSeedRegistryDto, BenchmarkSeedRegistryResponse, BenchmarkSnapshot, BenchmarkSnapshotsDto, BenchmarkSuite, BenchmarkSuiteListDto, BenchmarkTargetType } from '../types/benchmark'
import type { QueryParams, QueryValue, ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

type BenchmarkQuery = Record<string, QueryValue>

function benchmarkQueryParams(query: BenchmarkQuery = {}): QueryParams {
  return query
}

function benchmarkScopeFromQuery(query: BenchmarkQuery = {}): BenchmarkTargetType {
  return query.scope === 'model' || query.target_type === 'model' ? 'model' : 'role_version'
}

export function createBenchmarkService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    async suites(): Promise<BenchmarkSuite[]> {
      return normalizeBenchmarkSuiteList(await client.fetch<BenchmarkSuiteListDto>('/benchmarks'))
    },
    async seedSets(): Promise<BenchmarkSeedRegistryResponse> {
      return normalizeBenchmarkSeedRegistry(await client.fetch<BenchmarkSeedRegistryDto>('/benchmark/seed-sets'))
    },
    async leaderboard(query: BenchmarkQuery = {}): Promise<BenchmarkLeaderboardRow[]> {
      return normalizeBenchmarkLeaderboardResponse(
        await client.fetch<BenchmarkLeaderboardDto>('/leaderboards', {
          query: benchmarkQueryParams(query)
        }),
        benchmarkScopeFromQuery(query)
      )
    },
    async runs(query: BenchmarkQuery = {}): Promise<BenchmarkListResponse<BenchmarkRun>> {
      return normalizeBenchmarkRunsResponse(
        await client.fetch<BenchmarkRunsDto>('/evolution-runs', {
          query: benchmarkQueryParams({ ...query, source: 'benchmark' })
        })
      )
    },
    async launch(payload: BenchmarkRequest): Promise<BenchmarkRun> {
      return normalizeBenchmarkRunResponse(
        await client.fetch<BenchmarkRunResponseDto>('/benchmark', {
          method: 'POST',
          body: normalizeBenchmarkRequest(payload)
        })
      )
    },
    async run(id: string): Promise<BenchmarkRun> {
      return normalizeBenchmarkRunResponse(await client.fetch<BenchmarkRunResponseDto>(`/benchmark/batch/${encodeURIComponent(id)}`))
    },
    async diagnostics(id: string, query: BenchmarkQuery = {}): Promise<BenchmarkDiagnosticsResponse> {
      return normalizeBenchmarkDiagnosticsResponse(await client.fetch<BenchmarkDiagnosticsDto>(`/benchmark/batch/${encodeURIComponent(id)}/diagnostics`, { query: benchmarkQueryParams(query) }))
    },
    async report(id: string): Promise<unknown> {
      return client.fetch<unknown>(`/benchmark/batch/${encodeURIComponent(id)}/report`)
    },
    async snapshots(query: BenchmarkQuery = {}): Promise<BenchmarkSnapshot[]> {
      return normalizeBenchmarkSnapshotsResponse(
        await client.fetch<BenchmarkSnapshotsDto>('/benchmark/snapshots', {
          query: benchmarkQueryParams(query)
        }),
        benchmarkScopeFromQuery(query)
      )
    }
  }
}

export type BenchmarkService = ReturnType<typeof createBenchmarkService>
