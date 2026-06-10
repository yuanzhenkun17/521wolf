import {
  normalizeEvolutionLeaderboardResponse,
  normalizeEvolutionListResponse,
  normalizeEvolutionRoleOverview,
  normalizeEvolutionRunResponse,
  normalizeProposalReview,
  normalizeRoleKeysResponse,
  normalizeRoleVersionsResponse,
  normalizeTrustBundle
} from '../domain/evolution/normalizers'
import type {
  EvolutionActionRequest,
  EvolutionDiffResponse,
  EvolutionLeaderboardDto,
  EvolutionLeaderboardResponse,
  EvolutionListResponse,
  EvolutionRoleOverview,
  EvolutionRoleOverviewDto,
  EvolutionRolesDto,
  EvolutionRun,
  EvolutionRunResponseDto,
  EvolutionRunsDto,
  EvolutionStartRequest,
  ProposalReview,
  ProposalReviewDto,
  RoleVersion,
  RoleVersionsDto,
  TrustBundle,
  TrustBundleDto
} from '../types/evolution'
import type { QueryParams, QueryValue, ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

type EvolutionQuery = Record<string, QueryValue>

function evolutionQueryParams(query: EvolutionQuery = {}): QueryParams {
  return query
}

export function createEvolutionService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    async roles(): Promise<string[]> {
      return normalizeRoleKeysResponse(await client.fetch<EvolutionRolesDto>('/roles'))
    },
    async roleOverview(): Promise<EvolutionRoleOverview> {
      return normalizeEvolutionRoleOverview(await client.fetch<EvolutionRoleOverviewDto>('/roles/overview'))
    },
    async versions(role: string): Promise<RoleVersion[]> {
      return normalizeRoleVersionsResponse(await client.fetch<RoleVersionsDto>(`/roles/${encodeURIComponent(role)}/versions`))
    },
    async leaderboard(role: string): Promise<EvolutionLeaderboardResponse> {
      return normalizeEvolutionLeaderboardResponse(await client.fetch<EvolutionLeaderboardDto>(`/roles/${encodeURIComponent(role)}/leaderboard`), role)
    },
    async runs(query: EvolutionQuery = {}): Promise<EvolutionListResponse> {
      return normalizeEvolutionListResponse(
        await client.fetch<EvolutionRunsDto>('/evolution-runs', {
          query: evolutionQueryParams(query)
        })
      )
    },
    async start(payload: EvolutionStartRequest): Promise<EvolutionRun> {
      return normalizeEvolutionRunResponse(
        await client.fetch<EvolutionRunResponseDto>('/evolution-runs', {
          method: 'POST',
          body: payload
        })
      )
    },
    async run(id: string): Promise<EvolutionRun> {
      return normalizeEvolutionRunResponse(await client.fetch<EvolutionRunResponseDto>(`/evolution-runs/${encodeURIComponent(id)}`))
    },
    async diff(id: string): Promise<EvolutionDiffResponse> {
      return client.fetch<EvolutionDiffResponse>(`/evolution-runs/${encodeURIComponent(id)}/diff`)
    },
    async proposals(id: string, run: EvolutionRun | null = null): Promise<ProposalReview> {
      return normalizeProposalReview(await client.fetch<ProposalReviewDto>(`/evolution-runs/${encodeURIComponent(id)}/proposals`), run, { source: 'api' })
    },
    async trustBundle(id: string): Promise<TrustBundle | null> {
      return normalizeTrustBundle(await client.fetch<TrustBundleDto>(`/evolution-runs/${encodeURIComponent(id)}/trust-bundle`))
    },
    async action(id: string, payload: EvolutionActionRequest): Promise<EvolutionRun> {
      return normalizeEvolutionRunResponse(
        await client.fetch<EvolutionRunResponseDto>(`/evolution-runs/${encodeURIComponent(id)}/actions`, {
          method: 'POST',
          body: payload
        })
      )
    }
  }
}

export type EvolutionService = ReturnType<typeof createEvolutionService>
