import type { HistoryQuery, PhaseDetailQuery } from '../types/history'
import type { QueryParams, ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

function historyQueryParams(query: HistoryQuery): QueryParams {
  return {
    limit: query.limit,
    offset: query.offset,
    source: query.source,
    status: query.status
  }
}

function phaseDetailQueryParams(query: PhaseDetailQuery): QueryParams {
  return {
    day: query.day,
    phase: query.phase,
    log_offset: query.log_offset,
    log_limit: query.log_limit,
    decision_offset: query.decision_offset,
    decision_limit: query.decision_limit
  }
}

export function createHistoryService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    list(query: HistoryQuery = {}) {
      return client.fetch('/games/history', { query: historyQueryParams(query) })
    },
    shell(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/history-shell`)
    },
    phaseDetail(gameId: string, query: PhaseDetailQuery) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/history-phase`, { query: phaseDetailQueryParams(query) })
    },
    archive(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/archive`)
    },
    review(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/review`)
    },
    flow(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/flow`)
    },
    delete(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}`, { method: 'DELETE' })
    }
  }
}

export type HistoryService = ReturnType<typeof createHistoryService>
