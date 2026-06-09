import { normalizeGameSnapshot } from '../domain/game/normalizers'
import type { Game, GameStartRequest, HumanActionRequest } from '../types/game'
import type { ServiceOptions } from '../types/api'
import { defaultApiClient } from './api'

export function createGameService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient

  return {
    async health() {
      return client.fetch('/health')
    },
    async start(payload: GameStartRequest = {}): Promise<Game | null> {
      return normalizeGameSnapshot(await client.fetch('/games', { method: 'POST', body: payload }))
    },
    async get(gameId: string): Promise<Game | null> {
      return normalizeGameSnapshot(await client.fetch(`/games/${encodeURIComponent(gameId)}`))
    },
    async step(gameId: string, advance = false): Promise<Game | null> {
      const query = advance ? '?advance=1' : ''
      return normalizeGameSnapshot(await client.fetch(`/games/${encodeURIComponent(gameId)}${query}`))
    },
    async stop(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/stop`, { method: 'POST' })
    },
    async pendingHumanAction(gameId: string) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/human-action`)
    },
    async submitAction(gameId: string, payload: HumanActionRequest) {
      return client.fetch(`/games/${encodeURIComponent(gameId)}/action`, { method: 'POST', body: payload })
    }
  }
}

export type GameService = ReturnType<typeof createGameService>
