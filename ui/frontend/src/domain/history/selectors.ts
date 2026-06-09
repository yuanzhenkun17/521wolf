import type { Decision, GameLog } from '../../types/game'
import type { HistoryGame, HistoryPage, HistoryPhaseDetail } from '../../types/history'
import { normalizeHistoryDay, normalizeHistoryPhase, historyPageKey } from './normalizers'

export function phaseDetailKey(page: Partial<HistoryPage> | null | undefined): string {
  return String(page?.key || historyPageKey(page?.day, page?.phase))
}

export function selectedPhaseDetail(game: HistoryGame | null | undefined, page: Partial<HistoryPage> | null | undefined): HistoryPhaseDetail | null {
  const key = phaseDetailKey(page)
  return game?.__phaseDetails?.[key] || null
}

export function logsForPhase(logs: GameLog[] = [], page: Partial<HistoryPage> = {}): GameLog[] {
  const day = normalizeHistoryDay(page.day)
  const phase = normalizeHistoryPhase(page.phase)
  return logs.filter((log) => normalizeHistoryDay(log.day) === day && normalizeHistoryPhase(log.phase) === phase)
}

export function decisionsForPhase(decisions: Decision[] = [], page: Partial<HistoryPage> = {}): Decision[] {
  const day = normalizeHistoryDay(page.day)
  const phase = normalizeHistoryPhase(page.phase)
  return decisions.filter((decision) => normalizeHistoryDay(decision.day) === day && normalizeHistoryPhase(decision.phase) === phase)
}

export function historyGameDisplayId(game: Partial<HistoryGame> | null | undefined): string {
  return String(game?.game_id || game?.id || '')
}

export function historyGameEvidenceLabel(game: Partial<HistoryGame> | null | undefined): string {
  return String(game?.evidence_source?.log_source_label || game?.evidence_source?.log_source || game?.log_source_label || game?.log_source || '对局')
}
