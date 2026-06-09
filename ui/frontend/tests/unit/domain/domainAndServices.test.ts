import { describe, expect, it } from 'vitest'
import {
  arrayOrEmpty,
  booleanValue,
  buildQuery,
  firstNumber,
  firstString,
  integerValue,
  isRecord,
  mergeByStableId,
  normalizePagination,
  nullableNumber,
  numberValue,
  objectOrEmpty,
  positiveInteger,
  shortId,
  stringValue,
  uniqueStrings
} from '../../../src/domain/common'
import {
  canonicalActionType,
  canonicalChoice,
  normalizeGameSnapshot,
  normalizePendingHumanAction,
  targetRequiredForAction
} from '../../../src/domain/game/normalizers'
import { canSubmitPendingAction, currentSpeaker, pendingCandidatePlayers } from '../../../src/domain/game/selectors'
import { historyPageKey, normalizeHistoryPageSummary, parseHistoryPageKey } from '../../../src/domain/history/normalizers'
import { historyGameEvidenceLabel, logsForPhase } from '../../../src/domain/history/selectors'
import { normalizeRun, normalizeVersion } from '../../../src/domain/evolution/normalizers'
import { activeEvolutionRuns, rollbackEligibleVersions } from '../../../src/domain/evolution/selectors'
import { ApiError, normalizeApiError } from '../../../src/services/api'

describe('domain common helpers', () => {
  it('coerces primitive values with explicit fallbacks', () => {
    const record = { id: 'wolf' }

    expect(isRecord(record)).toBe(true)
    expect(isRecord([])).toBe(false)
    expect(isRecord(null)).toBe(false)
    expect(objectOrEmpty(record)).toBe(record)
    expect(objectOrEmpty('bad')).toEqual({})
    expect(arrayOrEmpty([1, 2])).toEqual([1, 2])
    expect(arrayOrEmpty('bad')).toEqual([])

    expect(stringValue('  alpha  ', 'fallback')).toBe('alpha')
    expect(stringValue('   ', 'fallback')).toBe('fallback')
    expect(numberValue('4.5')).toBe(4.5)
    expect(numberValue('bad', 7)).toBe(7)
    expect(integerValue('4.9')).toBe(4)
    expect(positiveInteger(0, 9)).toBe(9)
    expect(nullableNumber('')).toBeNull()
    expect(nullableNumber('3')).toBe(3)
    expect(booleanValue('YES')).toBe(true)
    expect(booleanValue('off', true)).toBe(false)
    expect(booleanValue('unknown', true)).toBe(true)

    expect(firstString(null, '  ', 'alpha')).toBe('alpha')
    expect(firstNumber('', 'bad', '2.25')).toBe(2.25)
    expect(uniqueStrings([' a ', ['a', 'b', '', null], 'b', 'c'])).toEqual(['a', 'b', 'c'])
    expect(shortId('abcdef', 3)).toBe('abc')
  })

  it('builds queries, clamps pagination, and merges stable ids', () => {
    expect(
      buildQuery({
        q: 'wolf pack',
        page: 0,
        active: false,
        empty: '',
        missing: null,
        tag: ['a', '', 'b']
      })
    ).toBe('?q=wolf+pack&page=0&active=false&tag=a&tag=b')

    expect(
      normalizePagination(
        { total: '-5', offset: '-4', limit: 'bad', returned: '-2', has_more: 'yes' },
        [1, 2, 3],
        { total: 10, offset: 8, limit: 5 }
      )
    ).toEqual({
      total: 0,
      offset: 0,
      limit: 3,
      returned: 0,
      has_more: true
    })

    const existing: Array<{ id?: string; fallback_id?: string; value: number }> = [
      { id: 'a', value: 1 },
      { id: '', fallback_id: 'legacy', value: 2 },
      { value: 3 }
    ]
    const incoming: Array<{ id?: string; fallback_id?: string; value: number }> = [
      { id: 'a', value: 99 },
      { fallback_id: 'legacy', value: 100 },
      { id: 'b', value: 4 },
      { id: '', value: 5 }
    ]

    expect(mergeByStableId(existing, incoming, ['id', 'fallback_id'])).toEqual([
      existing[0],
      existing[1],
      existing[2],
      incoming[2],
      incoming[3]
    ])
  })
})

describe('game domain normalizers and selectors', () => {
  it('normalizes pending action aliases and submission boundaries', () => {
    const normalized = normalizePendingHumanAction({
      action_type: 'white_wolf_burst',
      player_id: '3',
      candidates: [{ seat: '2' }, { player_id: 4 }, 'bad', 0],
      metadata: { allow_no_target: false }
    })

    expect(canonicalActionType('white_wolf_explosion')).toBe('white_wolf_explode')
    expect(canonicalActionType('vote')).toBe('exile_vote')
    expect(canonicalChoice('witch_act', 'antidote')).toBe('save')
    expect(canonicalChoice('white_wolf_burst', 'burst')).toBe('explode')
    expect(canonicalChoice('vote', '')).toBeNull()
    expect(targetRequiredForAction('exile_vote')).toBe(false)
    expect(targetRequiredForAction('guard_protect')).toBe(true)

    expect(normalized.waiting_for).toBe('action')
    expect(normalized.pending_human_action?.action_type).toBe('white_wolf_explode')
    expect(normalized.pending_human_action?.candidate_ids).toEqual([2, 4])
    expect(normalized.pending_action?.target_required).toBe(true)
    expect(normalized.pending_action?.allow_no_target).toBe(false)

    expect(canSubmitPendingAction(normalized.pending_action, null, 'explode', '')).toBe(false)
    expect(canSubmitPendingAction(normalized.pending_action, 2, '', '')).toBe(false)
    expect(canSubmitPendingAction(normalized.pending_action, 2, 'explode', '')).toBe(true)
  })

  it('keeps speech pending actions out of target submission flow', () => {
    const game = normalizeGameSnapshot(
      {
        game_id: 'game-1',
        phase: 'day_speech',
        human_player_id: 1,
        players: [
          { id: 1, seat: 1, name: 'P1', alive: true },
          { id: 2, seat: 2, name: 'P2', alive: true },
          { id: 3, seat: 3, name: 'P3', alive: false }
        ],
        pending_human_action: {
          action_type: 'sheriff_speech',
          player_id: 2,
          candidate_ids: [1, 2, 3]
        }
      },
      { mode: 'play' }
    )

    expect(game?.phase).toBe('speech')
    expect(game?.waiting_for).toBe('speech')
    expect(game?.pending_action).toBeNull()
    expect(game?.current_speaker_id).toBe(2)
    expect(currentSpeaker(game)?.id).toBe(2)
    expect(pendingCandidatePlayers(game, game?.pending_action)).toEqual([])
  })
})

describe('history and evolution boundaries', () => {
  it('normalizes history page keys, phase aliases, and evidence labels', () => {
    expect(historyPageKey(0, 'finished')).toBe('day-1-ended')
    expect(parseHistoryPageKey('day-03-sheriff_election')).toEqual({ day: 3, phase: 'sheriff' })
    expect(parseHistoryPageKey('bad-key')).toBeNull()
    expect(
      normalizeHistoryPageSummary({ phase_key: 'day-0-finished', logs_count: 'bad', decisions_count: '4' }, 7)
    ).toMatchObject({
      key: 'day-0-finished',
      day: 1,
      phase: 'ended',
      log_count: 0,
      decision_count: 4,
      index: 7
    })

    const speechLog = { day: 2, phase: 'day_speech', sequence: 1, type: 'speak', speaker: 'P1', visibility: 'public', message: 'claim' }
    const nightLog = { day: 2, phase: 'night', sequence: 2, type: 'night', speaker: 'Judge', visibility: 'public', message: 'night' }
    expect(logsForPhase([speechLog, nightLog], { day: 2, phase: 'speech' })).toEqual([speechLog])
    expect(historyGameEvidenceLabel({ evidence_source: { log_source: 'benchmark' } })).toBe('benchmark')
    expect(historyGameEvidenceLabel({ log_source_label: 'archive' })).toBe('archive')
    expect(historyGameEvidenceLabel(null)).toBe('对局')
  })

  it('clamps evolution progress and excludes rollback-blocked versions', () => {
    const active = normalizeRun({
      run_id: 'run-1',
      roles: ['seer', ''],
      status: 'running',
      overall_progress: { percent: 140 },
      training_total: 4,
      training_completed: 5,
      battle_total: 6,
      battle_completed: 3,
      proposals: [{ id: 'p1' }]
    })
    const done = normalizeRun({ run_id: 'run-2', status: 'completed' })

    expect(active.displayRole).toBe('seer')
    expect(active.progressPercent).toBe(100)
    expect(active.trainingProgressPercent).toBe(100)
    expect(active.battleProgressPercent).toBe(50)
    expect(active.proposalCount).toBe(1)
    expect(active.isActive).toBe(true)
    expect(done.isTerminal).toBe(true)
    expect(activeEvolutionRuns([active, done])).toEqual([active])

    const baseline = normalizeVersion({ version_id: 'baseline-version', is_baseline: true })
    const shadow = normalizeVersion({ target_version_id: 'shadow-version', provenance: { release_stage: 'SHADOW' } })
    const stable = normalizeVersion({ version_id: 'stable-version', release_stage: 'stable' })

    expect(baseline.rollbackDisabled).toBe(true)
    expect(shadow.rollbackDisabled).toBe(true)
    expect(stable.rollbackDisabled).toBe(false)
    expect(rollbackEligibleVersions([baseline, shadow, stable])).toEqual([stable])
  })
})

describe('service error conversion', () => {
  it('normalizes API error payloads into ApiError instances', () => {
    const response = new Response('ignored', {
      status: 422,
      headers: { 'x-request-id': 'header-request' }
    })
    const error = normalizeApiError({
      response,
      payload: {
        error: {
          code: 'invalid_action',
          message: 'Invalid action',
          diagnostics: [{ level: 'error', message: 'target missing' }],
          request_id: 'payload-request'
        },
        detail: [{ msg: 'fallback detail' }]
      },
      text: '{"detail":[{"msg":"fallback detail"}]}'
    })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(422)
    expect(error.code).toBe('invalid_action')
    expect(error.message).toBe('Invalid action')
    expect(error.requestId).toBe('payload-request')
    expect(error.diagnostics).toEqual([{ level: 'error', message: 'target missing' }])
    expect(error.body).toBe('{"detail":[{"msg":"fallback detail"}]}')
  })
})
