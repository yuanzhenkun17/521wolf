const ACTIVE_GAME_STORAGE_KEY = 'night-council.active-game.v1'

export interface StoredGameSession {
  gameId: string
  mode: string
  updatedAt: number
}

function storageApi(storage: Storage | null | undefined = globalThis.window?.localStorage): Storage | null {
  return storage && typeof storage.getItem === 'function' ? storage : null
}

export function normalizeStoredSession(value: unknown): StoredGameSession | null {
  if (!value || typeof value !== 'object') return null
  const source = value as Record<string, unknown>
  const gameId = source.gameId || source.game_id
  if (!gameId) return null
  return {
    gameId: String(gameId),
    mode: source.mode ? String(source.mode) : '',
    updatedAt: Number(source.updatedAt) || Date.now()
  }
}

export function readStoredGameSession(storage?: Storage | null): StoredGameSession | null {
  const target = storageApi(storage)
  if (!target) return null
  try {
    return normalizeStoredSession(JSON.parse(target.getItem(ACTIVE_GAME_STORAGE_KEY) || 'null'))
  } catch {
    return null
  }
}

export function writeStoredGameSession(session: StoredGameSession | null, storage?: Storage | null): StoredGameSession | null {
  const target = storageApi(storage)
  if (!target || !session?.gameId) return null
  const normalized = normalizeStoredSession(session)
  if (!normalized) return null
  try {
    target.setItem(ACTIVE_GAME_STORAGE_KEY, JSON.stringify(normalized))
  } catch {
    return null
  }
  return normalized
}

export function clearStoredGameSession(storage?: Storage | null): void {
  const target = storageApi(storage)
  if (!target) return
  try {
    target.removeItem(ACTIVE_GAME_STORAGE_KEY)
  } catch {}
}
