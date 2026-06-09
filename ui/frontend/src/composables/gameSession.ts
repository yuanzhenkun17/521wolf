// @ts-nocheck

const TERMINAL_GAME_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const ACTIVE_GAME_STORAGE_KEY = 'night-council.active-game.v1'

function isTerminalGame(game) {
  return Boolean(game?.winner) || TERMINAL_GAME_STATUSES.has(game?.status)
}

function isReturnableGame(game) {
  return Boolean(game?.game_id) && !isTerminalGame(game)
}

function activeSessionFromGame(game, { mode = '', sseConnected = false } = {}) {
  const running = isReturnableGame(game)
  return {
    gameId: game?.game_id || null,
    mode: game?.mode || mode || '',
    running,
    sseConnected: running && Boolean(sseConnected)
  }
}

function emptyActiveSession() {
  return { gameId: null, mode: '', running: false, sseConnected: false }
}

function normalizeStoredSession(value) {
  if (!value || typeof value !== 'object') return null
  const gameId = value.gameId || value.game_id
  if (!gameId) return null
  return {
    gameId: String(gameId),
    mode: value.mode ? String(value.mode) : '',
    updatedAt: Number(value.updatedAt) || Date.now()
  }
}

function storageApi(storage = globalThis.window?.localStorage) {
  return storage && typeof storage.getItem === 'function' ? storage : null
}

function readStoredGameSession(storage) {
  const target = storageApi(storage)
  if (!target) return null
  try {
    return normalizeStoredSession(JSON.parse(target.getItem(ACTIVE_GAME_STORAGE_KEY) || 'null'))
  } catch {
    return null
  }
}

function writeStoredGameSession(game, { mode = '' } = {}, storage) {
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
    target.setItem(ACTIVE_GAME_STORAGE_KEY, JSON.stringify(session))
  } catch {
    return null
  }
  return session
}

function clearStoredGameSession(storage) {
  const target = storageApi(storage)
  if (!target) return
  try {
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
