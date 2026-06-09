import type { HistoryQuery, PhaseDetailQuery } from '../types/history'
import type { QueryParams, ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

const DEFAULT_HISTORY_PAGE_SIZE = 8
const DEFAULT_PHASE_LOG_LIMIT = 300
const DEFAULT_PHASE_DECISION_LIMIT = 200

function historyQueryParams(query: HistoryQuery = {}): QueryParams {
  const params: QueryParams = {
    limit: query.limit === undefined ? DEFAULT_HISTORY_PAGE_SIZE : query.limit,
    offset: query.offset ?? 0
  }
  if (query.source && query.source !== 'all') params.source = query.source
  if (query.status && query.status !== 'all') params.status = query.status
  return params
}

function phaseDetailQueryParams(query: PhaseDetailQuery): QueryParams {
  return {
    day: query.day,
    phase: query.phase,
    log_offset: query.log_offset ?? 0,
    log_limit: query.log_limit ?? DEFAULT_PHASE_LOG_LIMIT,
    decision_offset: query.decision_offset ?? 0,
    decision_limit: query.decision_limit ?? DEFAULT_PHASE_DECISION_LIMIT
  }
}

export function createHistoryService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    list(query: HistoryQuery = {}) {
      return client.fetch('/games', { query: historyQueryParams(query) })
    },
    shell(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}`, { query: { view: 'history-shell' } })
    },
    phaseDetail(gameId: string, query: PhaseDetailQuery) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/phase`, { query: phaseDetailQueryParams(query) })
    },
    archive(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/archive`)
    },
    review(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/review`)
    },
    flow(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/flow-data`)
    },
    delete(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}`, { method: 'DELETE' })
    }
  }
}

export type HistoryService = ReturnType<typeof createHistoryService>
