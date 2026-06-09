import type { ActiveGameSession, GameMode, GameStatus } from '../types/game'

interface GameSessionGame {
  game_id?: string | null
  mode?: GameMode | null
  status?: GameStatus | null
  winner?: unknown
}

interface ActiveSessionOptions {
  mode?: GameMode | ''
  sseConnected?: boolean
}

interface StoredSessionOptions {
  mode?: GameMode | ''
}

interface StoredGameSession {
  gameId: string
  mode: string
  updatedAt: number
}

interface GameSessionStorageAdapter {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

type StorageCandidate = Partial<GameSessionStorageAdapter> | null | undefined
type ReadableStorageAdapter = Partial<GameSessionStorageAdapter> & Pick<GameSessionStorageAdapter, 'getItem'>

const TERMINAL_GAME_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled'])
const ACTIVE_GAME_STORAGE_KEY = 'night-council.active-game.v1'

function isTerminalGame(game: Pick<GameSessionGame, 'winner' | 'status'> | null | undefined): boolean {
  return Boolean(game?.winner) || TERMINAL_GAME_STATUSES.has(game?.status as string)
}

function isReturnableGame(game: Pick<GameSessionGame, 'game_id' | 'winner' | 'status'> | null | undefined): boolean {
  return Boolean(game?.game_id) && !isTerminalGame(game)
}

function activeSessionFromGame(
  game: GameSessionGame | null | undefined,
  { mode = '', sseConnected = false }: ActiveSessionOptions = {}
): ActiveGameSession {
  const running = isReturnableGame(game)
  return {
    gameId: game?.game_id || null,
    mode: game?.mode || mode || '',
    running,
    sseConnected: running && Boolean(sseConnected)
  }
}

function emptyActiveSession(): ActiveGameSession {
  return { gameId: null, mode: '', running: false, sseConnected: false }
}

function normalizeStoredSession(value: unknown): StoredGameSession | null {
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

function storageApi(storage: StorageCandidate = globalThis.window?.localStorage): ReadableStorageAdapter | null {
  return storage && typeof storage.getItem === 'function' ? storage as ReadableStorageAdapter : null
}

function readStoredGameSession(storage?: StorageCandidate): StoredGameSession | null {
  const target = storageApi(storage)
  if (!target) return null
  try {
    return normalizeStoredSession(JSON.parse(target.getItem(ACTIVE_GAME_STORAGE_KEY) || 'null'))
  } catch {
    return null
  }
}

function writeStoredGameSession(
  game: GameSessionGame | null | undefined,
  { mode = '' }: StoredSessionOptions = {},
  storage?: StorageCandidate
): StoredGameSession | null {
  const target = storageApi(storage)
  if (!target) return null
  if (!isReturnableGame(game)) {
    clearStoredGameSession(target)
    return null
  }
  const session = normalizeStoredSession({
    gameId: game.game_id,
    mode: game.mode || mode || '',
    updatedAt: Date.now()
  })
  try {
    if (typeof target.setItem !== 'function') throw new TypeError('storage.setItem is not a function')
    target.setItem(ACTIVE_GAME_STORAGE_KEY, JSON.stringify(session))
  } catch {
    return null
  }
  return session
}

function clearStoredGameSession(storage?: StorageCandidate): void {
  const target = storageApi(storage)
  if (!target) return
  try {
    if (typeof target.removeItem !== 'function') throw new TypeError('storage.removeItem is not a function')
    target.removeItem(ACTIVE_GAME_STORAGE_KEY)
  } catch {}
}

export {
  ACTIVE_GAME_STORAGE_KEY,
  TERMINAL_GAME_STATUSES,
  activeSessionFromGame,
  clearStoredGameSession,
  emptyActiveSession,
  isReturnableGame,
  isTerminalGame,
  readStoredGameSession,
  writeStoredGameSession
}
