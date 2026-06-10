import { describe, expect, expectTypeOf, it } from 'vitest'
import { arrayOrEmpty, booleanValue, buildQuery, firstNumber, firstString, integerValue, isRecord, mergeByStableId, normalizePagination, nullableNumber, numberValue, objectOrEmpty, positiveInteger, shortId, stringValue, uniqueStrings } from '../../../src/domain/common'
import { canonicalActionType, canonicalChoice, normalizeGameSnapshot, normalizePendingHumanAction, targetRequiredForAction } from '../../../src/domain/game/normalizers'
import { canSubmitPendingAction, currentSpeaker, pendingCandidatePlayers } from '../../../src/domain/game/selectors'
import { historyPageKey, normalizeHistoryPageSummary, parseHistoryPageKey } from '../../../src/domain/history/normalizers'
import { historyGameEvidenceLabel, logsForPhase } from '../../../src/domain/history/selectors'
import {
  normalizeTaskActionResponse,
  normalizeTaskArtifactsResponse,
  normalizeTaskEventsResponse,
  normalizeTaskListResponse,
  normalizeTaskResponse
} from '../../../src/domain/task/normalizers'
import {
  normalizeEvolutionListResponse,
  normalizeEvolutionRoleOverview,
  normalizeEvolutionRunResponse,
  normalizeProposalReview,
  normalizeRoleKeysResponse,
  normalizeRoleVersionsResponse,
  normalizeRun,
  normalizeTrustBundle,
  normalizeVersion
} from '../../../src/domain/evolution/normalizers'
import { activeEvolutionRuns, rollbackEligibleVersions } from '../../../src/domain/evolution/selectors'
import { ApiError, normalizeApiError, readErrorPayload } from '../../../src/services/api'
import { createBenchmarkService } from '../../../src/services/benchmarkApi'
import { createEvolutionService } from '../../../src/services/evolutionApi'
import { createHistoryService } from '../../../src/services/historyApi'
import { createTaskService } from '../../../src/services/taskApi'
import type { ApiClient, ApiRequestOptions } from '../../../src/types/api'
import type { EvolutionRun, ProposalReview } from '../../../src/types/evolution'
import type { TaskActionResponse, TaskListResponse } from '../../../src/types/task'

interface RecordedRequest {
  path: string
  options: ApiRequestOptions
}

function recordingClient(response: unknown = {}): {
  client: ApiClient
  requests: RecordedRequest[]
} {
  const requests: RecordedRequest[] = []
  const client: ApiClient = {
    apiBase: '/api',
    async fetch<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
      requests.push({ path, options })
      return response as T
    },
    async raw(): Promise<Response> {
      throw new Error('raw should not be called by service contract tests')
    }
  }
  return { client, requests }
}

function recordingSequenceClient(responses: readonly unknown[]): {
  client: ApiClient
  requests: RecordedRequest[]
} {
  const requests: RecordedRequest[] = []
  let index = 0
  const client: ApiClient = {
    apiBase: '/api',
    async fetch<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
      requests.push({ path, options })
      return (responses[index++] ?? {}) as T
    },
    async raw(): Promise<Response> {
      throw new Error('raw should not be called by service contract tests')
    }
  }
  return { client, requests }
}

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
        {
          total: '-5',
          offset: '-4',
          limit: 'bad',
          returned: '-2',
          has_more: 'yes'
        },
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

    const existing: Array<{
      id?: string
      fallback_id?: string
      value: number
    }> = [{ id: 'a', value: 1 }, { id: '', fallback_id: 'legacy', value: 2 }, { value: 3 }]
    const incoming: Array<{
      id?: string
      fallback_id?: string
      value: number
    }> = [
      { id: 'a', value: 99 },
      { fallback_id: 'legacy', value: 100 },
      { id: 'b', value: 4 },
      { id: '', value: 5 }
    ]

    expect(mergeByStableId(existing, incoming, ['id', 'fallback_id'])).toEqual([existing[0], existing[1], existing[2], incoming[2], incoming[3]])
  })

  it('keeps helper type contracts narrow for readonly inputs', () => {
    type StableRow = { id?: string; fallback_id?: string; value: number }

    const existing: readonly StableRow[] = [{ id: 'a', value: 1 }]
    const incoming: readonly StableRow[] = [{ fallback_id: 'legacy', value: 2 }]
    const pagination = normalizePagination({}, existing)
    const merged = mergeByStableId(existing, incoming, ['id', 'fallback_id'])

    expectTypeOf(pagination.limit).toEqualTypeOf<number | null>()
    expectTypeOf(merged).toEqualTypeOf<StableRow[]>()

    // @ts-expect-error Stable id fields must exist on row types without index signatures.
    mergeByStableId<StableRow>(existing, incoming, 'missing_id')
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
    expect(parseHistoryPageKey('day-03-sheriff_election')).toEqual({
      day: 3,
      phase: 'sheriff'
    })
    expect(parseHistoryPageKey('bad-key')).toBeNull()
    expect(
      normalizeHistoryPageSummary(
        {
          phase_key: 'day-0-finished',
          logs_count: 'bad',
          decisions_count: '4'
        },
        7
      )
    ).toMatchObject({
      key: 'day-0-finished',
      day: 1,
      phase: 'ended',
      log_count: 0,
      decision_count: 4,
      index: 7
    })

    const speechLog = {
      day: 2,
      phase: 'day_speech',
      sequence: 1,
      type: 'speak',
      speaker: 'P1',
      visibility: 'public',
      message: 'claim'
    }
    const nightLog = {
      day: 2,
      phase: 'night',
      sequence: 2,
      type: 'night',
      speaker: 'Judge',
      visibility: 'public',
      message: 'night'
    }
    expect(logsForPhase([speechLog, nightLog], { day: 2, phase: 'speech' })).toEqual([speechLog])
    expect(
      historyGameEvidenceLabel({
        evidence_source: { log_source: 'benchmark' }
      })
    ).toBe('benchmark')
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

    const baseline = normalizeVersion({
      version_id: 'baseline-version',
      is_baseline: true
    })
    const shadow = normalizeVersion({
      target_version_id: 'shadow-version',
      provenance: { release_stage: 'SHADOW' }
    })
    const stable = normalizeVersion({
      version_id: 'stable-version',
      release_stage: 'stable'
    })

    expect(baseline.rollbackDisabled).toBe(true)
    expect(shadow.rollbackDisabled).toBe(true)
    expect(stable.rollbackDisabled).toBe(false)
    expect(rollbackEligibleVersions([baseline, shadow, stable])).toEqual([stable])
  })

  it('normalizes evolution API wrappers, missing fields, and legacy review fields', () => {
    const list = normalizeEvolutionListResponse({
      items: [
        {
          run_id: 'run-1',
          role: 'seer',
          status: 'running',
          progress: { overall_percent: 0.5 }
        },
        {
          batch_id: 'batch-1',
          roles: ['seer', 'wolf'],
          status: 'queued',
          run_summaries: ['child-1']
        }
      ],
      pagination: { total: '2', offset: '0', limit: '20' }
    })
    const detail = normalizeEvolutionRunResponse({
      data: {
        run_id: 'run-2',
        role: 'guard',
        status: 'completed'
      }
    })
    const roles = normalizeRoleKeysResponse({
      roles: ['seer', { key: 'wolf' }, { role: 'seer' }, null]
    })
    const versions = normalizeRoleVersionsResponse({
      items: [
        {
          target_version_id: 'canary-version',
          provenance: { releaseStage: 'CANARY' }
        }
      ]
    })
    const overview = normalizeEvolutionRoleOverview({
      versions: {
        seer: [{ version_id: 'v1' }]
      },
      leaderboards: {
        seer: {
          entries: [
            {
              target_role: 'seer',
              target_version_id: 'v1',
              target_role_role_weighted_score: '0.75',
              game_count: '4'
            }
          ]
        }
      }
    })
    const review = normalizeProposalReview({
      rows: [
        {
          proposal_id: 'p1',
          claim: 'tighten vote timing',
          status: 'accepted',
          evidence_summary: { game_ids: ['g1', 'g1'] },
          risk: { tags: ['timing', 'timing'] }
        }
      ],
      paired_seed_pairs: [
        {
          battle_seed: 'seed-1',
          baseline_result: { score: '1', game_id: 'base-game' },
          candidate_result: { score: '2', game_id: 'cand-game' }
        }
      ],
      generated_proposal_ids: ['p1', 'p2'],
      accepted_proposal_ids: ['p1'],
      preflight_passed_proposal_ids: ['p1'],
      applied_proposal_ids: ['p1']
    })
    const fallbackReview = normalizeProposalReview(null, { proposal_rows: [{ id: 'fallback-p' }] }, {
      source: 'run-detail',
      error: 'proposal endpoint failed',
      unsupported: true
    })
    const trustBundle = normalizeTrustBundle({
      data: {
        trustBundleId: 'tb-1',
        trustBundle: {
          run_id: 'run-1',
          role: 'seer',
          bundle_hash: 'hash-1'
        }
      }
    })

    expect(list.runs).toHaveLength(1)
    expect(list.batches[0]).toMatchObject({
      id: 'batch-1',
      isBatch: true,
      childRunCount: 1
    })
    expect(list.pagination).toMatchObject({ total: 2, returned: 2 })
    expect(detail).toMatchObject({ id: 'run-2', displayRole: 'guard', isTerminal: true })
    expect(roles).toEqual(['seer', 'wolf'])
    expect(versions[0]).toMatchObject({
      version_id: 'canary-version',
      releaseStage: 'canary',
      rollbackDisabled: true
    })
    expect(overview.roles).toEqual(['seer'])
    expect(overview.versions.seer[0]).toMatchObject({ version_id: 'v1' })
    expect(overview.leaderboards.seer.entries[0]).toMatchObject({
      role: 'seer',
      versionId: 'v1',
      score: 0.75,
      gameCount: 4
    })
    expect(review.proposals[0]).toMatchObject({
      id: 'p1',
      title: 'tighten vote timing',
      evidenceGameIds: ['g1'],
      riskTags: ['timing']
    })
    expect(review.pairedSeeds[0]).toMatchObject({
      seed: 'seed-1',
      baselineScore: 1,
      candidateScore: 2,
      scoreDelta: 1,
      baselineGameId: 'base-game',
      candidateGameId: 'cand-game'
    })
    expect(review.summary).toMatchObject({
      total: 2,
      accepted: 1,
      rejected: 0,
      pending: 1,
      preflight: 1,
      applied: 1
    })
    expect(fallbackReview).toMatchObject({
      source: 'run-detail',
      error: 'proposal endpoint failed',
      unsupported: true
    })
    expect(fallbackReview.proposals[0]).toMatchObject({ id: 'fallback-p' })
    expect(trustBundle).toMatchObject({
      trust_bundle_id: 'tb-1',
      run_id: 'run-1',
      role: 'seer',
      bundle_hash: 'hash-1'
    })
  })
})

describe('task domain normalizers', () => {
  it('normalizes task list and detail wrappers from backend-compatible fields', () => {
    const list = normalizeTaskListResponse({
      items: [
        {
          id: 'task-1',
          kind: 'artifact.export',
          status: 'running',
          priority: '5',
          progress: { completed_games: '2', target_games: '4', stage: 'battle' },
          attempt: '1',
          max_attempts: '3',
          payload: { role: 'seer' },
          result: null,
          error: null,
          cancel_requested: 'false'
        },
        {
          task_id: 'task-2',
          status: 'succeeded',
          progress_percent: 0.25,
          result: { artifact_count: 2 },
          current_stage: 'done'
        }
      ],
      pagination: { total: '2', offset: '0', limit: '20' }
    })
    const detail = normalizeTaskResponse({
      data: {
        task_id: 'task-3',
        status: 'failed',
        progress: { percent: 140 },
        error: { message: 'boom' },
        metadata: { source: 'queue' }
      }
    })
    const legacyDetail = normalizeTaskResponse({
      task: {
        id: 'task-4',
        status: 'queued',
        progress: { overall_percent: '0.5' }
      }
    })

    expectTypeOf(list).toMatchTypeOf<TaskListResponse>()
    expect(list.tasks[0]).toMatchObject({
      id: 'task-1',
      task_id: 'task-1',
      priority: 5,
      progressPercent: 50,
      progressLabel: '2 / 4',
      stageLabel: 'battle',
      statusLabel: '运行中',
      isActive: true,
      isTerminal: false
    })
    expect(list.tasks[1]).toMatchObject({
      id: 'task-2',
      progressPercent: 25,
      progressLabel: '25%',
      stageLabel: 'done',
      isTerminal: true
    })
    expect(list.pagination).toMatchObject({ total: 2, returned: 2 })
    expect(detail).toMatchObject({
      id: 'task-3',
      progressPercent: 100,
      error: { message: 'boom' },
      metadata: { source: 'queue' },
      isTerminal: true
    })
    expect(legacyDetail).toMatchObject({
      id: 'task-4',
      progressPercent: 50,
      statusLabel: '排队中',
      isActive: true
    })
  })

  it('normalizes task artifacts, events, and action responses', () => {
    const artifacts = normalizeTaskArtifactsResponse({
      task_id: 'task-1',
      items: [
        {
          id: 'artifact-1',
          task_id: 'task-1',
          artifact_type: 'report',
          relative_path: 'reports/run.json',
          content_type: 'APPLICATION/JSON',
          size_bytes: '1536',
          sha256: 'sha256:abcdef1234567890'
        },
        {
          artifact_id: 'artifact-2',
          name: 'stdout.txt',
          size_bytes: '',
          sha256: ''
        }
      ]
    })
    const events = normalizeTaskEventsResponse({
      task_id: 'task-1',
      after_event_id: '41',
      items: [
        { event_id: 42, event_type: 'progress', payload: { percent: 50 } },
        { id: '43', type: 'artifact_created', payload: { artifact_id: 'artifact-1' } },
        { id: '44', event: 'cancel_requested', payload: { task_id: 'task-1' } }
      ]
    })
    const action = normalizeTaskActionResponse({
      task_id: 'task-1',
      action: 'cancel',
      changed: 'yes',
      task: { task_id: 'task-1', status: 'cancelled' }
    })

    expectTypeOf(action).toMatchTypeOf<TaskActionResponse>()
    expect(artifacts).toMatchObject({
      task_id: 'task-1',
      artifacts: [
        {
          id: 'artifact-1',
          artifact_id: 'artifact-1',
          name: 'reports/run.json',
          content_type: 'application/json',
          size_bytes: 1536,
          isJson: true,
          sizeLabel: '1.5 KB',
          shortSha: 'abcdef123456'
        },
        {
          id: 'artifact-2',
          name: 'stdout.txt',
          size_bytes: null,
          isJson: false,
          sizeLabel: '大小未知'
        }
      ]
    })
    expect(events).toMatchObject({
      task_id: 'task-1',
      after_event_id: 41,
      events: [
        { event_id: 42, event_type: 'progress' },
        { id: '43', type: 'artifact_created' },
        { id: '44', event_type: 'cancel_requested', type: 'cancel_requested' }
      ]
    })
    expect(action).toMatchObject({
      task_id: 'task-1',
      action: 'cancel',
      changed: true,
      task: {
        id: 'task-1',
        isTerminal: true
      }
    })
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

  it('converts primitive error JSON into a typed detail payload', async () => {
    const response = new Response('"plain failure"', {
      status: 500,
      headers: { 'x-correlation-id': 'correlation-1' }
    })
    const payload = await readErrorPayload(response)
    const error = normalizeApiError({ response, ...payload })

    expect(payload).toEqual({
      payload: { detail: 'plain failure' },
      text: '"plain failure"',
      requestId: 'correlation-1'
    })
    expect(error.code).toBe('internal_error')
    expect(error.message).toBe('plain failure')
    expect(error.requestId).toBe('correlation-1')
    expect(error.diagnostics).toEqual([])
  })
})

describe('service endpoint contracts', () => {
  it('maps task service calls to task queue backend routes and artifact URLs', async () => {
    const { client, requests } = recordingClient()
    const tasks = createTaskService({ client })

    await tasks.list({ status: ['queued', 'running'], limit: 25 })
    await tasks.get('task id/1')
    await tasks.cancel('task id/1')
    await tasks.retry('task id/1')
    await tasks.events('task id/1', 42)
    await tasks.artifacts('task id/1')
    await tasks.previewJsonArtifact('task id/1', 'artifact id/2')
    const artifactUrl = tasks.artifactUrl('task id/1', 'artifact id/2')

    expect(artifactUrl).toBe('/api/tasks/task%20id%2F1/artifacts/artifact%20id%2F2')
    expect(requests).toEqual([
      {
        path: '/tasks',
        options: {
          query: { status: ['queued', 'running'], limit: 25 }
        }
      },
      { path: '/tasks/task%20id%2F1', options: {} },
      {
        path: '/tasks/task%20id%2F1/cancel',
        options: { method: 'POST' }
      },
      {
        path: '/tasks/task%20id%2F1/retry',
        options: { method: 'POST' }
      },
      {
        path: '/tasks/task%20id%2F1/events',
        options: { query: { after_event_id: 42 } }
      },
      { path: '/tasks/task%20id%2F1/artifacts', options: {} },
      { path: '/tasks/task%20id%2F1/artifacts/artifact%20id%2F2', options: {} }
    ])
  })

  it('maps history service calls to the current game history backend routes', async () => {
    const { client, requests } = recordingClient()
    const history = createHistoryService({ client })

    await history.list({
      source: 'benchmark',
      status: 'completed',
      limit: 12,
      offset: 24
    })
    await history.list({ source: 'all', status: 'all' })
    await history.shell('game id/1')
    await history.phaseDetail('game id/1', { day: 2, phase: 'speech' })
    await history.flow('game id/1')
    await history.delete('game id/1')

    expect(requests).toEqual([
      {
        path: '/games',
        options: {
          query: {
            limit: 12,
            offset: 24,
            source: 'benchmark',
            status: 'completed'
          }
        }
      },
      {
        path: '/games',
        options: { query: { limit: 8, offset: 0 } }
      },
      {
        path: '/games/game%20id%2F1',
        options: { query: { view: 'history-shell' } }
      },
      {
        path: '/games/game%20id%2F1/phase',
        options: {
          query: {
            day: 2,
            phase: 'speech',
            log_offset: 0,
            log_limit: 300,
            decision_offset: 0,
            decision_limit: 200
          }
        }
      },
      {
        path: '/games/game%20id%2F1/flow-data',
        options: {}
      },
      {
        path: '/games/game%20id%2F1',
        options: { method: 'DELETE' }
      }
    ])
  })

  it('maps benchmark service calls to benchmark and leaderboard backend routes', async () => {
    const { client, requests } = recordingClient()
    const benchmark = createBenchmarkService({ client })
    const payload = {
      benchmark_id: 'role-baseline',
      target_type: 'role_version' as const,
      roles: ['seer'],
      battle_games: 4
    }

    await benchmark.suites()
    await benchmark.seedSets()
    await benchmark.leaderboard({
      scope: 'role_version',
      target_role: 'seer',
      limit: 50
    })
    await benchmark.runs({ status: 'running', limit: 20 })
    await benchmark.launch(payload)
    await benchmark.run('bench id/1')
    await benchmark.diagnostics('bench id/1', {
      kind: 'game_failure',
      seed: 260902
    })
    await benchmark.report('bench id/1')
    await benchmark.snapshots({
      scope: 'role_version',
      benchmark_id: 'role-baseline'
    })

    expect(requests).toEqual([
      { path: '/benchmarks', options: {} },
      { path: '/benchmark/seed-sets', options: {} },
      {
        path: '/leaderboards',
        options: {
          query: { scope: 'role_version', target_role: 'seer', limit: 50 }
        }
      },
      {
        path: '/evolution-runs',
        options: {
          query: { status: 'running', limit: 20, source: 'benchmark' }
        }
      },
      {
        path: '/benchmark',
        options: { method: 'POST', body: { ...payload, target_versions: {} } }
      },
      { path: '/benchmark/batch/bench%20id%2F1', options: {} },
      {
        path: '/benchmark/batch/bench%20id%2F1/diagnostics',
        options: { query: { kind: 'game_failure', seed: 260902 } }
      },
      { path: '/benchmark/batch/bench%20id%2F1/report', options: {} },
      {
        path: '/benchmark/snapshots',
        options: {
          query: { scope: 'role_version', benchmark_id: 'role-baseline' }
        }
      }
    ])
  })

  it('maps evolution service calls to typed API DTOs and normalized domain responses', async () => {
    const { client, requests } = recordingSequenceClient([
      { roles: ['seer', { key: 'wolf' }, ''] },
      {
        versions: { seer: [{ version_id: 'v1' }] },
        leaderboards: {
          seer: {
            entries: [{ target_role: 'seer', target_version_id: 'v1', score: '0.6' }]
          }
        }
      },
      { versions: [{ target_version_id: 'v2', provenance: { release_stage: 'stable' } }] },
      { entries: [{ target_role: 'seer', target_version_id: 'v2', game_count: '3' }] },
      {
        items: [{ run_id: 'run-1', role: 'seer', status: 'running' }],
        pagination: { total: 1, offset: 0, limit: 20 }
      },
      { run: { run_id: 'run-2', role: 'wolf', status: 'queued' } },
      { data: { run_id: 'run-3', role: 'guard', status: 'completed' } },
      { diff: ['patch'] },
      {
        rows: [{ proposal_id: 'p1', summary: 'change claim' }],
        paired_seed_pairs: [{ seed: 'seed-1' }]
      },
      {
        data: {
          trust_bundle_id: 'tb-1',
          trust_bundle: { bundle_hash: 'hash-1' }
        }
      },
      { batch_id: 'batch-1', roles: ['seer'], status: 'cancelled' }
    ])
    const evolution = createEvolutionService({ client })

    const roles = await evolution.roles()
    const overview = await evolution.roleOverview()
    const versions = await evolution.versions('seer role')
    const leaderboard = await evolution.leaderboard('seer role')
    const runs = await evolution.runs({ status: 'running', limit: 20 })
    const started = await evolution.start({ roles: ['wolf'], training_games: 3 })
    const detail = await evolution.run('run id/3')
    const diff = await evolution.diff('run id/3')
    const proposals = await evolution.proposals('run id/3', detail)
    const trustBundle = await evolution.trustBundle('run id/3')
    const actionResult = await evolution.action('batch id/1', { action: 'terminate' })

    expectTypeOf(started).toMatchTypeOf<EvolutionRun>()
    expectTypeOf(proposals).toMatchTypeOf<ProposalReview>()
    expect(roles).toEqual(['seer', 'wolf'])
    expect(overview.roles).toEqual(['seer'])
    expect(overview.leaderboards.seer.entries[0]).toMatchObject({ versionId: 'v1', score: 0.6 })
    expect(versions[0]).toMatchObject({ version_id: 'v2', releaseStage: 'stable' })
    expect(leaderboard.entries[0]).toMatchObject({ role: 'seer', versionId: 'v2', gameCount: 3 })
    expect(runs.runs[0]).toMatchObject({ id: 'run-1', isActive: true })
    expect(started).toMatchObject({ id: 'run-2', displayRole: 'wolf', isActive: true })
    expect(detail).toMatchObject({ id: 'run-3', isTerminal: true })
    expect(diff.diff).toEqual(['patch'])
    expect(proposals.proposals[0]).toMatchObject({ id: 'p1', title: 'change claim' })
    expect(proposals.pairedSeeds[0]).toMatchObject({ seed: 'seed-1' })
    expect(trustBundle).toMatchObject({ trust_bundle_id: 'tb-1', bundle_hash: 'hash-1' })
    expect(actionResult).toMatchObject({ id: 'batch-1', isBatch: true, isTerminal: true })
    expect(requests).toEqual([
      { path: '/roles', options: {} },
      { path: '/roles/overview', options: {} },
      { path: '/roles/seer%20role/versions', options: {} },
      { path: '/roles/seer%20role/leaderboard', options: {} },
      {
        path: '/evolution-runs',
        options: { query: { status: 'running', limit: 20 } }
      },
      {
        path: '/evolution-runs',
        options: { method: 'POST', body: { roles: ['wolf'], training_games: 3 } }
      },
      { path: '/evolution-runs/run%20id%2F3', options: {} },
      { path: '/evolution-runs/run%20id%2F3/diff', options: {} },
      { path: '/evolution-runs/run%20id%2F3/proposals', options: {} },
      { path: '/evolution-runs/run%20id%2F3/trust-bundle', options: {} },
      {
        path: '/evolution-runs/batch%20id%2F1/actions',
        options: { method: 'POST', body: { action: 'terminate' } }
      }
    ])
  })

  it('normalizes benchmark service DTO responses into domain contracts', async () => {
    const { client } = recordingSequenceClient([
      {
        benchmarks: [
          {
            benchmark_id: 'suite-1',
            version: '2',
            name: 'Model gate',
            target_type: 'model',
            seed_set_id: 'seed-A',
            roles: ['seer', ''],
            status: 'draft'
          }
        ]
      },
      {
        seed_sets: [
          {
            seed_set_id: 'seed-A',
            seeds: '101 202',
            target_type: 'model',
            enabled: false
          }
        ],
        summary: { total: 'bad' }
      },
      {
        scope: 'model',
        rows: [
          {
            model_id: 'gpt-x',
            model_config_hash: 'hash1234567890',
            score: '0.7',
            games: '5'
          }
        ]
      },
      {
        runs: [
          {
            batch_id: 'batch-1',
            status: 'running',
            roles: ['seer'],
            benchmark: { id: 'suite-1', target_type: 'role_version' }
          }
        ],
        pagination: { total: '2', offset: '0', limit: '10' }
      },
      { run: { run_id: 'batch-2', status: 'completed', role: 'wolf' } },
      {
        diagnostics: [{ level: 'warning', message: 'bad seed', history_game_id: 'game-1' }],
        summary: { warning: 1 },
        pagination: { total: 1, offset: 0, limit: 10 }
      },
      {
        snapshots: [
          {
            snapshot_id: 'snap-1',
            scope: 'model',
            rows: [{ model_id: 'gpt-x', score: '0.8' }]
          }
        ]
      }
    ])
    const benchmark = createBenchmarkService({ client })

    const suites = await benchmark.suites()
    const seedSets = await benchmark.seedSets()
    const leaderboard = await benchmark.leaderboard({ scope: 'model' })
    const runs = await benchmark.runs({ status: 'running' })
    const launched = await benchmark.launch({ roles: ['seer'] })
    const diagnostics = await benchmark.diagnostics('batch-1')
    const snapshots = await benchmark.snapshots({ scope: 'model' })

    expect(suites[0]).toMatchObject({
      id: 'suite-1',
      target_type: 'model',
      roles: ['seer'],
      launchable: false
    })
    expect(seedSets).toMatchObject({
      summary: { total: 1 },
      items: [{ id: 'seed-A', seed_preview: ['101', '202'], enabled: false }]
    })
    expect(leaderboard[0]).toMatchObject({
      primary: 'gpt-x',
      secondary: 'hash12345678',
      score: 0.7,
      games: 5
    })
    expect(runs.items[0]).toMatchObject({
      id: 'batch-1',
      displayRole: 'seer',
      isActive: true
    })
    expect(runs.pagination).toMatchObject({ total: 2, returned: 1 })
    expect(launched).toMatchObject({
      id: 'batch-2',
      displayRole: 'wolf',
      isTerminal: true
    })
    expect(diagnostics).toMatchObject({
      summary: { warning: 1 },
      diagnostics: [{ level: 'warning', message: 'bad seed', history_game_id: 'game-1' }]
    })
    expect(snapshots[0]).toMatchObject({
      snapshot_id: 'snap-1',
      scope: 'model',
      rows: [{ primary: 'gpt-x', score: 0.8 }]
    })
  })
})
