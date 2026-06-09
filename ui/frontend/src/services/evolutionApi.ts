import type { EvolutionStartRequest } from '../types/evolution'
import type { ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

export function createEvolutionService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    roles() {
      return client.fetch('/roles')
    },
    roleOverview() {
      return client.fetch('/roles/overview')
    },
    versions(role: string) {
      return client.fetch(`/roles/${encodeURIComponent(role)}/versions`)
    },
    leaderboard(role: string) {
      return client.fetch(`/roles/${encodeURIComponent(role)}/leaderboard`)
    },
    runs(query: Record<string, string | number | boolean | null | undefined> = {}) {
      return client.fetch('/evolution-runs', { query })
    },
    start(payload: EvolutionStartRequest) {
      return client.fetch('/evolution-runs', { method: 'POST', body: payload })
    },
    run(id: string) {
      return client.fetch(`/evolution-runs/${encodeURIComponent(id)}`)
    },
    diff(id: string) {
      return client.fetch(`/evolution-runs/${encodeURIComponent(id)}/diff`)
    },
    proposals(id: string) {
      return client.fetch(`/evolution-runs/${encodeURIComponent(id)}/proposals`)
    },
    trustBundle(id: string) {
      return client.fetch(`/evolution-runs/${encodeURIComponent(id)}/trust-bundle`)
    },
    action(id: string, payload: Record<string, unknown>) {
      return client.fetch(`/evolution-runs/${encodeURIComponent(id)}/actions`, { method: 'POST', body: payload })
    }
  }
}

export type EvolutionService = ReturnType<typeof createEvolutionService>
