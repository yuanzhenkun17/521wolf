import type { Game, PendingAction, Player } from '../../types/game'

export function alivePlayers(game: Pick<Game, 'players'> | null | undefined): Player[] {
  return (game?.players || []).filter((player) => player.alive !== false)
}

export function playerById(game: Pick<Game, 'players'> | null | undefined, id: unknown): Player | null {
  const target = Number(id)
  if (!Number.isFinite(target)) return null
  return (game?.players || []).find((player) => Number(player.id) === target) || null
}

export function humanPlayer(game: Pick<Game, 'players' | 'human_player_id'> | null | undefined): Player | null {
  return playerById(game, game?.human_player_id)
}

export function currentSpeaker(game: Pick<Game, 'players' | 'current_speaker_id'> | null | undefined): Player | null {
  return playerById(game, game?.current_speaker_id)
}

export function pendingCandidatePlayers(
  game: Pick<Game, 'players'> | null | undefined,
  pending: PendingAction | null | undefined
): Player[] {
  const candidates = new Set((pending?.candidate_ids || []).map(Number))
  if (!candidates.size) return []
  return (game?.players || []).filter((player) => candidates.has(Number(player.id)))
}

export function canSubmitPendingAction(pending: PendingAction | null | undefined, target: unknown, choice: unknown, text: unknown): boolean {
  if (!pending) return false
  if (pending.target_required && !Number(target)) return false
  if ((pending.options.choices || []).length && !String(choice || '').trim()) return false
  if (pending.type === 'speech' && !String(text || '').trim()) return false
  return true
}

export function gamePhaseKey(game: Pick<Game, 'day' | 'phase'> | null | undefined): string {
  return `day-${Number(game?.day || 1)}-${game?.phase || 'setup'}`
}
