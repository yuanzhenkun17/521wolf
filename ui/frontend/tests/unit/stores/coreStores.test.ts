import assert from 'node:assert/strict'
import { afterEach, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { useEvolutionStore } from '../../../src/stores/evolution'
import { useGameStore } from '../../../src/stores/game'
import { useHistoryStore } from '../../../src/stores/history'
import { useReplayStore } from '../../../src/stores/replay'
import {
  createIncrementalRuntimeHydrator,
  createStoreRuntimeHydration,
  hydrateStoresFromRuntime,
  runtimeHydrationKeys
} from '../../../src/stores/runtimeHydration'
import { useSessionStore } from '../../../src/stores/session'
import { useUiStore } from '../../../src/stores/ui'
import type { EvolutionRun } from '../../../src/types/evolution'
import type { Game } from '../../../src/types/game'
import type { HistoryGame, ReplaySnapshot } from '../../../src/types/history'

afterEach(() => {
  vi.restoreAllMocks()
})

function gameFixture(id: string, overrides: Partial<Game> = {}): Game {
  return {
    game_id: id,
    mode: 'watch',
    status: 'running',
    phase: 'night',
    player_count: 2,
    players: [],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    ...overrides
  }
}

function historyGameFixture(id: string, overrides: Partial<HistoryGame> = {}): HistoryGame {
  return {
    ...gameFixture(id),
    event_count: 0,
    decision_count: 0,
    phases: [],
    history_pages: [],
    ...overrides
  }
}

function replaySnapshotFixture(id: string, overrides: Partial<ReplaySnapshot> = {}): ReplaySnapshot {
  return {
    ...gameFixture(id),
    cursor: 0,
    limit: 100,
    next_cursor: null,
    has_more: false,
    ...overrides
  }
}

function evolutionRunFixture(id: string, overrides: Partial<EvolutionRun> = {}): EvolutionRun {
  return {
    id,
    run_id: id,
    entityType: 'run',
    isBatch: false,
    childRuns: [],
    childRunCount: 0,
    role: 'werewolf',
    roles: ['werewolf'],
    displayRole: '狼人',
    status: 'running',
    currentStage: 'training',
    recommendation: 'pending',
    recommendationLabel: '等待',
    progressPercent: 0,
    progressLabel: '0%',
    overallProgressPercent: 0,
    stageProgressPercent: 0,
    trainingProgressPercent: 0,
    battleProgressPercent: 0,
    trainingGameRequested: 0,
    trainingGameCompleted: 0,
    battleGameRequested: 0,
    battleGameCompleted: 0,
    proposalCount: 0,
    diffCount: 0,
    diagnosticCount: 0,
    warningCount: 0,
    errorCount: 0,
    isReviewing: false,
    isTerminal: false,
    isActive: true,
    ...overrides
  }
}

test('session store hydrates runtime state and updates view/session actions', () => {
  setActivePinia(createPinia())
  const store = useSessionStore()

  store.hydrateFromRuntime({
    currentView: 'match',
    backendMode: 'api',
    activeSession: { gameId: 'game-1', mode: 'watch', running: true, sseConnected: true },
    returnToMatchAvailable: true
  })

  assert.equal(store.currentView, 'match')
  assert.equal(store.backendMode, 'api')
  assert.equal(store.activeSession.gameId, 'game-1')
  assert.equal(store.activeSession.running, true)
  assert.equal(store.returnToMatchAvailable, true)
  assert.equal(store.backendAvailable, true)
  assert.equal(store.inMatch, true)
  assert.equal(store.inLobby, false)

  store.setView('logs')
  store.setActiveSession({ gameId: 'game-2', mode: 'play', running: false, sseConnected: false })

  assert.equal(store.currentView, 'logs')
  assert.equal(store.inLogs, true)
  assert.equal(store.activeSession.gameId, 'game-2')
  assert.equal(store.activeSession.mode, 'play')

  store.setBackendMode('offline')
  assert.equal(store.backendMode, 'offline')
  assert.equal(store.backendAvailable, false)

  store.setBackendMode('api')
  store.patchActiveSession({ running: true, sseConnected: true })
  store.setReturnToMatchAvailable(false)

  assert.equal(store.backendMode, 'api')
  assert.equal(store.backendAvailable, true)
  assert.equal(store.activeSession.gameId, 'game-2')
  assert.equal(store.activeSession.running, true)
  assert.equal(store.activeSession.sseConnected, true)
  assert.equal(store.returnToMatchAvailable, false)

  store.setView('benchmark')

  assert.equal(store.inLogs, false)
  assert.equal(store.inBenchmark, true)

  store.hydrateFromRuntime({ currentView: 'unknown-view' })

  assert.equal(store.currentView, 'benchmark')

  store.hydrateFromRuntime({ backendMode: null, activeSession: null, returnToMatchAvailable: null })

  assert.equal(store.backendMode, 'mock')
  assert.deepEqual(store.activeSession, { gameId: null, mode: '', running: false, sseConnected: false })
  assert.equal(store.returnToMatchAvailable, false)
})

test('game store hydrates snapshots and clears live watch state', () => {
  setActivePinia(createPinia())
  const store = useGameStore()
  const liveGame = gameFixture('game-1', { mode: 'watch', phase: 'night' })

  store.hydrateFromRuntime({
    game: liveGame,
    loading: true,
    error: 'failed to load',
    watchRunning: true,
    roleAssignmentComplete: false,
    judgeBoardStarted: true,
    judgeBoardStarting: false,
    promptText: '今晚行动',
    judgeStripMessage: [{ message: '法官提示' }],
    playerIdentityList: [{ id: 1, speaking: true }],
    matchRecordLogs: [{ message: '日志' }],
    livingPlayers: [{ id: 1 }],
    speakerCarousel: [{ key: 1, label: '1号' }],
    speakerMessage: '正在发言',
    sceneVoteTally: [{ target: 1, count: 2 }],
    sceneEffects: [{ type: 'speech' }],
    skipIntroGameId: 'game-1',
    speechRemaining: 64
  })

  assert.equal(store.liveGame?.game_id, 'game-1')
  assert.equal(store.loading, true)
  assert.equal(store.error, 'failed to load')
  assert.equal(store.watchRunning, true)
  assert.equal(store.roleAssignmentComplete, false)
  assert.equal(store.judgeBoardStarted, true)
  assert.equal(store.judgeBoardStarting, false)
  assert.equal(store.promptText, '今晚行动')
  assert.deepEqual(store.judgeStripMessage, [{ message: '法官提示' }])
  assert.deepEqual(store.playerIdentityList, [{ id: 1, speaking: true }])
  assert.deepEqual(store.matchRecordLogs, [{ message: '日志' }])
  assert.deepEqual(store.livingPlayers, [{ id: 1 }])
  assert.deepEqual(store.speakerCarousel, [{ key: 1, label: '1号' }])
  assert.equal(store.speakerMessage, '正在发言')
  assert.deepEqual(store.sceneVoteTally, [{ target: 1, count: 2 }])
  assert.deepEqual(store.sceneEffects, [{ type: 'speech' }])
  assert.equal(store.skipIntroGameId, 'game-1')
  assert.equal(store.speechRemaining, 64)
  assert.equal(store.isNight, true)
  assert.equal(store.isWatch, true)

  store.setGame(gameFixture('game-2', { mode: 'play', phase: 'speech' }))

  assert.equal(store.liveGame?.game_id, 'game-2')
  assert.equal(store.isNight, false)
  assert.equal(store.isWatch, false)

  store.setLoading(false)
  store.setError(null)
  store.setWatchRunning(true)

  assert.equal(store.loading, false)
  assert.equal(store.error, '')
  assert.equal(store.watchRunning, true)

  store.setError('manual failure')

  assert.equal(store.error, 'manual failure')

  store.clearGame()

  assert.equal(store.liveGame, null)
  assert.equal(store.watchRunning, false)
  assert.equal(store.roleAssignmentComplete, false)
  assert.equal(store.judgeBoardStarted, false)
  assert.equal(store.judgeBoardStarting, false)
  assert.equal(store.promptText, '')
  assert.deepEqual(store.judgeStripMessage, [])
  assert.deepEqual(store.playerIdentityList, [])
  assert.deepEqual(store.matchRecordLogs, [])
  assert.deepEqual(store.livingPlayers, [])
  assert.deepEqual(store.speakerCarousel, [])
  assert.equal(store.speakerMessage, '')
  assert.deepEqual(store.sceneVoteTally, [])
  assert.deepEqual(store.sceneEffects, [])
  assert.equal(store.skipIntroGameId, null)
  assert.equal(store.chatLogExpanded, false)
  assert.equal(store.speech, '我先报一下自己的视角：目前重点听发言逻辑和票型。')
  assert.equal(store.speechRemaining, 180)
  assert.equal(store.witchChoice, 'skip')
  assert.equal(store.actionChoice, '')
  assert.equal(store.burstArmed, false)
  assert.equal(store.actionTarget, null)

  store.hydrateFromRuntime({
    roleAssignmentComplete: null,
    judgeBoardStarted: null,
    judgeBoardStarting: null
  })

  assert.equal(store.roleAssignmentComplete, false)
  assert.equal(store.judgeBoardStarted, false)
  assert.equal(store.judgeBoardStarting, false)
})

test('game store owns match action controls and derives action prompts', () => {
  setActivePinia(createPinia())
  const store = useGameStore()
  const liveGame = gameFixture('action-game', {
    mode: 'play',
    phase: 'night',
    human_player_id: 1,
    waiting_for: 'action',
    players: [
      { id: 1, seat: 1, name: 'Human', role_hint: '女巫', alive: true, is_human: true, is_sheriff: false },
      { id: 2, seat: 2, name: 'Target', role_hint: '狼人', alive: true, is_human: false, is_sheriff: false },
      { id: 3, seat: 3, name: 'Dead', role_hint: '平民', alive: false, is_human: false, is_sheriff: false }
    ],
    pending_action: {
      type: 'witch_act',
      prompt: '女巫请选择是否发动技能。',
      candidate_ids: [2],
      target_required: false,
      allow_no_target: true,
      options: {
        poison_available: true,
        antidote_available: true,
        attacked_player: 2
      }
    },
    skill_state: {
      witch_antidote_used: false,
      witch_poison_used: false
    }
  })

  store.hydrateFromRuntime({
    game: liveGame,
    livingPlayers: liveGame.players.filter((player) => player.alive),
    speechRemaining: 65
  })
  store.setWitchChoice('poison')

  assert.equal(store.humanPlayer?.id, 1)
  assert.equal(store.roleName, '女巫')
  assert.equal(store.pendingActionType, 'witch_act')
  assert.equal(store.canUseWitchAntidote, true)
  assert.equal(store.canUseWitchPoison, true)
  assert.equal(store.needsTarget, true)
  assert.equal(store.speechCountdownText, '1:05')
  assert.deepEqual(store.actionCandidates.map((player) => player.id), [2])
  assert.equal(store.actionInstruction, '法官提醒：点击一名玩家模型使用毒药。')

  store.setActionTarget(null)
  store.selectScenePlayer(2)

  assert.equal(store.actionTarget, 2)

  store.setSpeech('更新后的发言')
  store.setWitchChoice('antidote')
  store.setActionChoice('skip')
  store.setBurstArmed(true)
  store.setChatLogExpanded(true)

  assert.equal(store.speech, '更新后的发言')
  assert.equal(store.witchChoice, 'antidote')
  assert.equal(store.actionChoice, 'skip')
  assert.equal(store.burstArmed, true)
  assert.equal(store.chatLogExpanded, true)
  assert.equal(store.actionInstruction, '法官提醒：确认使用解药救 2 号。')
})

test('history store hydrates selection and derives selection state', () => {
  setActivePinia(createPinia())
  const store = useHistoryStore()
  const selectedGame = historyGameFixture('history-1')

  store.hydrateFromRuntime({
    gameHistory: [selectedGame],
    selectedHistoryGameId: 'history-1',
    selectedHistoryGame: selectedGame,
    historyWorkspaceTab: 'review',
    historyLoading: true,
    historyPagination: { total: 8, limit: 2, offset: 2, returned: 2 },
    historyLoadingMore: true,
    historySourceFilter: 'benchmark',
    historyCounts: { all: 8, benchmark: 3 },
    historyFacets: { source: { normal: 5, benchmark: 3 } },
    historyNotice: { type: 'warning', message: 'history is stale' },
    historyHasMore: true,
    historyCurrentPage: 2,
    historyTotalPages: 4,
    historyPages: [{ key: 'day-1-night' }],
    selectedHistoryPageKey: 'day-1-night',
    selectedHistoryPage: { key: 'day-1-night', phase: 'night' },
    phaseLoadingByKey: { 'day-1-night': true },
    historyLogs: [{ event_type: 'night_result', message: '昨夜平安' }],
    pageNightActions: [{ actor: 1, action: 'guard' }],
    pageSpeechDecisions: [{ player_id: 2, decision: 'claim' }],
    sheriffVotes: [{ voter: 1, target: 2 }],
    voteDecisions: [{ voter: 2, target: 3 }],
    currentVoteTally: [{ target: 3, count: 2 }],
    sheriffVoteTally: [{ target: 2, count: 1 }],
    pageLastWords: [{ player_id: 4, text: '遗言' }],
    nightResult: 'peace',
    sheriffResult: { elected: 2 },
    playerAssessmentScores: [{ player_id: 1, score: 0.8 }],
    activeAssessScores: [{ player_id: 2, score: 0.6 }],
    playerAliveAtPage: { 1: true, 4: false },
    archiveByGameId: { 'history-1': { archive_id: 'archive-1' } },
    reviewByGameId: { 'history-1': { report_id: 'review-1' } },
    flowDataByGameId: { 'history-1': { nodes: [] } },
    flowLoadingByGameId: { 'history-1': false },
    archiveLoading: true,
    reviewLoading: true
  })

  assert.equal(store.games.length, 1)
  assert.equal(store.games[0].game_id, 'history-1')
  assert.equal(store.selectedHistoryGameId, 'history-1')
  assert.equal(store.selectedHistoryGame?.game_id, 'history-1')
  assert.equal(store.historyWorkspaceTab, 'review')
  assert.equal(store.loading, true)
  assert.deepEqual(store.pagination, { total: 8, limit: 2, offset: 2, returned: 2 })
  assert.equal(store.loadingMore, true)
  assert.equal(store.sourceFilter, 'benchmark')
  assert.deepEqual(store.counts, { all: 8, benchmark: 3 })
  assert.deepEqual(store.facets, { source: { normal: 5, benchmark: 3 } })
  assert.equal(store.error, 'history is stale')
  assert.equal(store.hasMore, true)
  assert.equal(store.currentPage, 2)
  assert.equal(store.totalPages, 4)
  assert.deepEqual(store.pages, [{ key: 'day-1-night' }])
  assert.equal(store.selectedHistoryPageKey, 'day-1-night')
  assert.deepEqual(store.selectedHistoryPage, { key: 'day-1-night', phase: 'night' })
  assert.deepEqual(store.phaseLoadingByKey, { 'day-1-night': true })
  assert.deepEqual(store.historyLogs, [{ event_type: 'night_result', message: '昨夜平安' }])
  assert.deepEqual(store.pageNightActions, [{ actor: 1, action: 'guard' }])
  assert.deepEqual(store.pageSpeechDecisions, [{ player_id: 2, decision: 'claim' }])
  assert.deepEqual(store.sheriffVotes, [{ voter: 1, target: 2 }])
  assert.deepEqual(store.voteDecisions, [{ voter: 2, target: 3 }])
  assert.deepEqual(store.currentVoteTally, [{ target: 3, count: 2 }])
  assert.deepEqual(store.sheriffVoteTally, [{ target: 2, count: 1 }])
  assert.deepEqual(store.pageLastWords, [{ player_id: 4, text: '遗言' }])
  assert.equal(store.nightResult, 'peace')
  assert.deepEqual(store.sheriffResult, { elected: 2 })
  assert.deepEqual(store.playerAssessmentScores, [{ player_id: 1, score: 0.8 }])
  assert.deepEqual(store.activeAssessScores, [{ player_id: 2, score: 0.6 }])
  assert.deepEqual(store.playerAliveAtPage, { 1: true, 4: false })
  assert.deepEqual(store.archiveByGameId, { 'history-1': { archive_id: 'archive-1' } })
  assert.deepEqual(store.reviewByGameId, { 'history-1': { report_id: 'review-1' } })
  assert.deepEqual(store.flowDataByGameId, { 'history-1': { nodes: [] } })
  assert.deepEqual(store.flowLoadingByGameId, { 'history-1': false })
  assert.equal(store.archiveLoading, true)
  assert.equal(store.reviewLoading, true)
  assert.equal(store.hasSelection, true)

  store.selectGame(null)

  assert.equal(store.selectedHistoryGame, null)
  assert.equal(store.selectedHistoryGameId, null)
  assert.equal(store.hasSelection, false)

  store.setGames([historyGameFixture('history-2')])

  assert.equal(store.games.length, 1)
  assert.equal(store.games[0].game_id, 'history-2')
})

test('history store forwards runtime actions through a thin facade', async () => {
  setActivePinia(createPinia())
  const store = useHistoryStore()
  const loadReview = vi.fn().mockResolvedValue('review-loaded')
  const loadArchive = vi.fn().mockResolvedValue('archive-loaded')
  const loadMoreHistory = vi.fn().mockResolvedValue('history-loaded')

  assert.equal(store.hasRuntimeActions, false)
  assert.equal(store.hasRuntimeAction('loadReview'), false)
  assert.equal(store.loadReview('history-1'), undefined)

  store.bindRuntimeActions({
    loadReview,
    loadArchive,
    loadMoreHistory
  })

  assert.equal(store.hasRuntimeActions, true)
  assert.equal(store.hasRuntimeAction('loadReview'), true)
  assert.equal(await store.loadReview('history-1'), 'review-loaded')
  assert.equal(await store.loadArchive('history-1'), 'archive-loaded')
  assert.equal(await store.loadMoreHistory(), 'history-loaded')
  assert.deepEqual(loadReview.mock.calls[0], ['history-1'])
  assert.deepEqual(loadArchive.mock.calls[0], ['history-1'])

  store.clearRuntimeActions()

  assert.equal(store.hasRuntimeActions, false)
  assert.equal(store.hasRuntimeAction('loadReview'), false)
  assert.equal(store.loadReview('history-1'), undefined)
})

test('evolution store hydrates workbench shell state and forwards actions', async () => {
  setActivePinia(createPinia())
  const store = useEvolutionStore()
  const run = evolutionRunFixture('run-1')
  const detail = evolutionRunFixture('run-1', { proposalCount: 3, progressLabel: 'loaded detail' })
  const batch = evolutionRunFixture('batch-1', {
    batch_id: 'batch-1',
    entityType: 'batch',
    isBatch: true,
    run_id: undefined,
    roles: ['werewolf', 'seer'],
    displayRole: '批量运行'
  })
  const refreshAll = vi.fn().mockResolvedValue('refreshed')
  const selectRole = vi.fn().mockReturnValue('role-selected')
  const selectRun = vi.fn().mockResolvedValue('run-selected')

  store.hydrateFromWorkbench({
    loading: true,
    error: 'evolution failed',
    notice: { type: 'warning', message: 'stale' },
    roles: ['werewolf'],
    roleRows: [{ key: 'werewolf', label: '狼人' }],
    versionsByRole: {
      werewolf: [{
        version_id: 'v1',
        releaseStage: 'baseline',
        rollbackDisabled: false,
        rollbackDisabledReason: '',
        short: 'v1'
      }]
    },
    runs: [run],
    runRows: [run, batch],
    selectedRole: 'werewolf',
    selectedRunId: 'run-1',
    selectedRun: detail,
    selectedRunSummary: { id: 'run-1', statusLabel: '运行中' },
    selectedProposalReview: { source: 'api' },
    selectedGames: { training: [{ id: 'game-1' }] },
    selectedCanPromote: true,
    selectedPromoteDisabledReason: '',
    selectedCanReject: true,
    selectedRejectDisabledReason: '',
    selectedCanTerminate: true,
    selectedTerminateDisabledReason: '',
    selectedRollbackDisabledReason: '当前运行不可回滚'
  })

  assert.equal(store.loading, true)
  assert.equal(store.error, 'evolution failed')
  assert.deepEqual(store.notice, { type: 'warning', message: 'stale' })
  assert.deepEqual(store.roleRows, [{ key: 'werewolf', label: '狼人' }])
  assert.equal(store.selectedRole, 'werewolf')
  assert.equal(store.selectedRun?.proposalCount, 3)
  assert.equal(store.selectedRun?.progressLabel, 'loaded detail')
  assert.equal(store.selectedIsRun, true)
  assert.equal(store.selectedIsBatch, false)
  assert.deepEqual(store.selectedRunSummary, { id: 'run-1', statusLabel: '运行中' })
  assert.deepEqual(store.selectedProposalReview, { source: 'api' })
  assert.deepEqual(store.selectedGames, { training: [{ id: 'game-1' }] })
  assert.equal(store.selectedCanPromote, true)
  assert.equal(store.selectedCanReject, true)
  assert.equal(store.selectedCanTerminate, true)
  assert.equal(store.selectedRollbackDisabledReason, '当前运行不可回滚')
  assert.deepEqual(store.selectedRoleVersions.map((version) => version.version_id), ['v1'])

  store.hydrateFromWorkbench({
    runs: [run],
    runRows: [run, batch],
    selectedRole: 'werewolf',
    selectedRunId: 'batch-1',
    selectedRun: null
  })

  assert.equal(store.selectedRun?.id, 'batch-1')
  assert.equal(store.selectedIsBatch, true)
  assert.equal(store.hasSelection, true)

  store.bindRuntimeActions({ refreshAll, selectRole, selectRun })

  assert.equal(store.hasRuntimeActions, true)
  assert.equal(store.hasRuntimeAction('selectRole'), true)
  assert.equal(store.selectRole('seer'), 'role-selected')
  assert.equal(store.selectedRole, 'seer')
  assert.deepEqual(selectRole.mock.calls[0], ['seer'])
  assert.equal(await store.selectRun('run-1'), 'run-selected')
  assert.equal(store.selectedRunId, 'run-1')
  assert.equal(store.selectedRun?.id, 'run-1')
  assert.equal(await store.refreshAll(), 'refreshed')

  store.clearRuntimeActions()

  assert.equal(store.hasRuntimeActions, false)
  assert.equal(store.hasRuntimeAction('selectRole'), false)
  assert.equal(store.selectRun(''), undefined)
})

test('replay store hydrates replay state and toggles replay actions', () => {
  setActivePinia(createPinia())
  const store = useReplayStore()

  store.hydrateFromRuntime({
    replayGame: replaySnapshotFixture('replay-1', { cursor: 4 }),
    isReplayMode: true,
    replayCursor: 4,
    replayPlaying: true,
    replaySpeed: 2,
    replayTotal: 12,
    replayEventLabel: '事件 4 / 12'
  })

  assert.equal(store.replayGame?.game_id, 'replay-1')
  assert.equal(store.isReplayMode, true)
  assert.equal(store.replayCursor, 4)
  assert.equal(store.replayPlaying, true)
  assert.equal(store.replaySpeed, 2)
  assert.equal(store.replayTotal, 12)
  assert.equal(store.replayEventLabel, '事件 4 / 12')
  assert.equal(store.hasReplay, true)

  store.exitReplay()

  assert.equal(store.replayGame, null)
  assert.equal(store.isReplayMode, false)
  assert.equal(store.replayPlaying, false)
  assert.equal(store.replayTotal, 0)
  assert.equal(store.replayEventLabel, '')
  assert.equal(store.hasReplay, false)

  store.enterReplay(replaySnapshotFixture('replay-2', { cursor: 7 }))

  assert.equal(store.replayGame?.game_id, 'replay-2')
  assert.equal(store.isReplayMode, true)
  assert.equal(store.replayCursor, 7)
  assert.equal(store.hasReplay, true)

  store.hydrateFromRuntime({
    replayCursor: 0,
    replaySpeed: 0
  })

  assert.equal(store.replayCursor, 0)
  assert.equal(store.replaySpeed, 0)
})

test('ui store hydrates notices and manages deterministic toast actions', () => {
  setActivePinia(createPinia())
  const store = useUiStore()
  const toastId = '00000000-0000-4000-8000-000000000001' as `${string}-${string}-${string}-${string}-${string}`

  vi.spyOn(Date, 'now').mockReturnValue(1710000000000)
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(toastId)

  store.hydrateFromRuntime({ error: 'backend failed' })

  assert.deepEqual(store.notice, { type: 'error', message: 'backend failed' })
  assert.equal(store.errorMessage, 'backend failed')
  assert.equal(store.audioEnabled, false)
  assert.equal(store.ttsEnabled, false)
  assert.equal(store.ttsAvailable, false)

  store.hydrateFromRuntime({
    error: 'still failed',
    matchNotice: { type: 'success', message: 'match ready' },
    historyNotice: { type: 'warning', message: 'history stale' },
    audioEnabled: true,
    ttsEnabled: true,
    ttsAvailable: false
  })

  assert.deepEqual(store.notice, { type: 'success', message: 'match ready' })
  assert.equal(store.errorMessage, 'still failed')
  assert.equal(store.audioEnabled, true)
  assert.equal(store.ttsEnabled, true)
  assert.equal(store.ttsAvailable, false)

  store.setNotice({ type: 'info', message: 'manual notice' })
  const createdToastId = store.pushToast({ type: 'success', message: 'saved', timeoutMs: 5000 })

  assert.equal(createdToastId, toastId)
  assert.deepEqual(store.notice, { type: 'info', message: 'manual notice' })
  assert.deepEqual(store.toasts, [
    {
      type: 'success',
      message: 'saved',
      timeoutMs: 5000,
      id: toastId,
      createdAt: 1710000000000
    }
  ])

  store.removeToast(toastId)

  assert.deepEqual(store.toasts, [])
})

test('runtime hydration helper unwraps runtime refs and applies core store payloads', () => {
  setActivePinia(createPinia())
  const sessionStore = useSessionStore()
  const gameStore = useGameStore()
  const historyStore = useHistoryStore()
  const replayStore = useReplayStore()
  const uiStore = useUiStore()
  const liveGame = gameFixture('runtime-game', { mode: 'play', phase: 'speech' })
  const historyGame = historyGameFixture('runtime-history')
  const replayGame = replaySnapshotFixture('runtime-replay', { cursor: 3 })

  const runtime = {
    currentView: ref('match'),
    backendMode: ref('api'),
    activeSession: ref({ gameId: 'runtime-game', mode: 'play', running: true, sseConnected: false }),
    returnToMatchAvailable: ref(true),
    liveGame: ref(liveGame),
    game: ref(replayGame),
    loading: ref(false),
    error: ref(''),
    watchRunning: ref(false),
    roleAssignmentComplete: ref(true),
    judgeBoardStarted: ref(true),
    judgeBoardStarting: ref(false),
    promptText: ref('runtime prompt'),
    judgeStripMessage: ref([{ message: 'runtime judge' }]),
    playerIdentityList: ref([{ id: 2, speaking: true }]),
    matchRecordLogs: ref([{ message: 'runtime log' }]),
    livingPlayers: ref([{ id: 2 }]),
    speakerCarousel: ref([{ key: 2, label: '2号' }]),
    speakerMessage: ref('runtime speaker'),
    sceneVoteTally: ref([{ target: 2, count: 1 }]),
    sceneEffects: ref([{ type: 'vote' }]),
    skipIntroGameId: ref('runtime-game'),
    speechRemaining: ref(42),
    gameHistory: ref([historyGame]),
    selectedHistoryGameId: ref('runtime-history'),
    selectedHistoryGame: ref(historyGame),
    historyWorkspaceTab: ref('archive'),
    historyLoading: ref(true),
    historyPagination: ref({ total: 6, limit: 2, offset: 4, returned: 2 }),
    historyLoadingMore: ref(true),
    historySourceFilter: ref('evolution'),
    historyCounts: ref({ all: 2, evolution: 1 }),
    historyFacets: ref({ source: { evolution: 1 } }),
    historyNotice: ref({ type: 'warning', message: 'history warning' }),
    historyHasMore: ref(true),
    historyCurrentPage: ref(3),
    historyTotalPages: ref(5),
    historyPages: ref([{ key: 'runtime-page' }]),
    selectedHistoryPageKey: ref('runtime-page'),
    selectedHistoryPage: ref({ key: 'runtime-page', phase: 'speech' }),
    phaseLoadingByKey: ref({ 'runtime-page': false }),
    historyLogs: ref([{ event_type: 'speech', message: 'runtime log' }]),
    pageNightActions: ref([{ actor: 3, action: 'inspect' }]),
    pageSpeechDecisions: ref([{ player_id: 3, decision: 'vote' }]),
    sheriffVotes: ref([{ voter: 3, target: 1 }]),
    voteDecisions: ref([{ voter: 4, target: 1 }]),
    currentVoteTally: ref([{ target: 1, count: 3 }]),
    sheriffVoteTally: ref([{ target: 1, count: 2 }]),
    pageLastWords: ref([{ player_id: 5, text: 'runtime last words' }]),
    nightResult: ref('runtime night result'),
    sheriffResult: ref({ elected: 1 }),
    playerAssessmentScores: ref([{ player_id: 3, score: 0.7 }]),
    activeAssessScores: ref([{ player_id: 4, score: 0.5 }]),
    playerAliveAtPage: ref({ 3: true, 5: false }),
    archiveByGameId: ref({ 'runtime-history': { archive_id: 'runtime-archive' } }),
    reviewByGameId: ref({ 'runtime-history': { report_id: 'runtime-review' } }),
    flowDataByGameId: ref({ 'runtime-history': { edges: [] } }),
    flowLoadingByGameId: ref({ 'runtime-history': true }),
    archiveLoading: ref(true),
    reviewLoading: ref(true),
    replayGame: ref(replayGame),
    isReplayMode: ref(true),
    replayCursor: ref(3),
    replayPlaying: ref(false),
    replaySpeed: ref(1.5),
    replayTotal: ref(9),
    replayEventLabel: ref('第 3 / 9 条'),
    audioEnabled: ref(true),
    ttsEnabled: ref(false),
    ttsAvailable: ref(true),
    matchNotice: ref({ type: 'success', message: 'match hydrated' })
  }

  const payloads = hydrateStoresFromRuntime(runtime, {
    session: sessionStore,
    game: gameStore,
    history: historyStore,
    replay: replayStore,
    ui: uiStore
  })

  assert.deepEqual(runtimeHydrationKeys.session, [
    'currentView',
    'backendMode',
    'activeSession',
    'returnToMatchAvailable'
  ])
  assert.deepEqual(runtimeHydrationKeys.game, [
    'liveGame',
    'game',
    'loading',
    'error',
    'watchRunning',
    'roleAssignmentComplete',
    'judgeBoardStarted',
    'judgeBoardStarting',
    'promptText',
    'judgeStripMessage',
    'playerIdentityList',
    'matchRecordLogs',
    'livingPlayers',
    'speakerCarousel',
    'speakerMessage',
    'sceneVoteTally',
    'sceneEffects',
    'skipIntroGameId',
    'speechRemaining'
  ])
  assert.deepEqual(runtimeHydrationKeys.history, [
    'gameHistory',
    'selectedHistoryGameId',
    'selectedHistoryGame',
    'historyWorkspaceTab',
    'historyLoading',
    'historyPagination',
    'historyLoadingMore',
    'historySourceFilter',
    'historyCounts',
    'historyFacets',
    'historyNotice',
    'historyHasMore',
    'historyCurrentPage',
    'historyTotalPages',
    'historyPages',
    'selectedHistoryPageKey',
    'selectedHistoryPage',
    'phaseLoadingByKey',
    'historyLogs',
    'pageNightActions',
    'pageSpeechDecisions',
    'sheriffVotes',
    'voteDecisions',
    'currentVoteTally',
    'sheriffVoteTally',
    'pageLastWords',
    'nightResult',
    'sheriffResult',
    'playerAssessmentScores',
    'activeAssessScores',
    'playerAliveAtPage',
    'archiveByGameId',
    'reviewByGameId',
    'flowDataByGameId',
    'flowLoadingByGameId',
    'archiveLoading',
    'reviewLoading'
  ])
  assert.equal(payloads.game.liveGame?.game_id, 'runtime-game')
  assert.equal(payloads.game.game?.game_id, 'runtime-replay')
  assert.equal(payloads.game.roleAssignmentComplete, true)
  assert.equal(sessionStore.currentView, 'match')
  assert.equal(sessionStore.activeSession.gameId, 'runtime-game')
  assert.equal(gameStore.liveGame?.game_id, 'runtime-game')
  assert.equal(gameStore.roleAssignmentComplete, true)
  assert.equal(gameStore.judgeBoardStarted, true)
  assert.equal(gameStore.judgeBoardStarting, false)
  assert.equal(gameStore.promptText, 'runtime prompt')
  assert.deepEqual(gameStore.judgeStripMessage, [{ message: 'runtime judge' }])
  assert.deepEqual(gameStore.playerIdentityList, [{ id: 2, speaking: true }])
  assert.deepEqual(gameStore.matchRecordLogs, [{ message: 'runtime log' }])
  assert.deepEqual(gameStore.livingPlayers, [{ id: 2 }])
  assert.deepEqual(gameStore.speakerCarousel, [{ key: 2, label: '2号' }])
  assert.equal(gameStore.speakerMessage, 'runtime speaker')
  assert.deepEqual(gameStore.sceneVoteTally, [{ target: 2, count: 1 }])
  assert.deepEqual(gameStore.sceneEffects, [{ type: 'vote' }])
  assert.equal(gameStore.skipIntroGameId, 'runtime-game')
  assert.equal(gameStore.speechRemaining, 42)
  assert.equal(historyStore.games[0].game_id, 'runtime-history')
  assert.equal(historyStore.historyWorkspaceTab, 'archive')
  assert.deepEqual(historyStore.pagination, { total: 6, limit: 2, offset: 4, returned: 2 })
  assert.equal(historyStore.loadingMore, true)
  assert.equal(historyStore.sourceFilter, 'evolution')
  assert.deepEqual(historyStore.counts, { all: 2, evolution: 1 })
  assert.deepEqual(historyStore.facets, { source: { evolution: 1 } })
  assert.equal(historyStore.hasMore, true)
  assert.equal(historyStore.currentPage, 3)
  assert.equal(historyStore.totalPages, 5)
  assert.deepEqual(historyStore.pages, [{ key: 'runtime-page' }])
  assert.equal(payloads.history.selectedHistoryPageKey, 'runtime-page')
  assert.equal(historyStore.selectedHistoryPageKey, 'runtime-page')
  assert.deepEqual(historyStore.selectedHistoryPage, { key: 'runtime-page', phase: 'speech' })
  assert.deepEqual(historyStore.phaseLoadingByKey, { 'runtime-page': false })
  assert.deepEqual(historyStore.historyLogs, [{ event_type: 'speech', message: 'runtime log' }])
  assert.deepEqual(historyStore.pageNightActions, [{ actor: 3, action: 'inspect' }])
  assert.deepEqual(historyStore.pageSpeechDecisions, [{ player_id: 3, decision: 'vote' }])
  assert.deepEqual(historyStore.sheriffVotes, [{ voter: 3, target: 1 }])
  assert.deepEqual(historyStore.voteDecisions, [{ voter: 4, target: 1 }])
  assert.deepEqual(historyStore.currentVoteTally, [{ target: 1, count: 3 }])
  assert.deepEqual(historyStore.sheriffVoteTally, [{ target: 1, count: 2 }])
  assert.deepEqual(historyStore.pageLastWords, [{ player_id: 5, text: 'runtime last words' }])
  assert.equal(historyStore.nightResult, 'runtime night result')
  assert.deepEqual(historyStore.sheriffResult, { elected: 1 })
  assert.deepEqual(historyStore.playerAssessmentScores, [{ player_id: 3, score: 0.7 }])
  assert.deepEqual(historyStore.activeAssessScores, [{ player_id: 4, score: 0.5 }])
  assert.deepEqual(historyStore.playerAliveAtPage, { 3: true, 5: false })
  assert.deepEqual(historyStore.archiveByGameId, { 'runtime-history': { archive_id: 'runtime-archive' } })
  assert.deepEqual(historyStore.reviewByGameId, { 'runtime-history': { report_id: 'runtime-review' } })
  assert.deepEqual(historyStore.flowDataByGameId, { 'runtime-history': { edges: [] } })
  assert.deepEqual(historyStore.flowLoadingByGameId, { 'runtime-history': true })
  assert.equal(historyStore.archiveLoading, true)
  assert.equal(historyStore.reviewLoading, true)
  assert.equal(replayStore.replayGame?.game_id, 'runtime-replay')
  assert.equal(replayStore.replaySpeed, 1.5)
  assert.equal(replayStore.replayTotal, 9)
  assert.equal(replayStore.replayEventLabel, '第 3 / 9 条')
  assert.deepEqual(runtimeHydrationKeys.ui, [
    'error',
    'matchNotice',
    'historyNotice',
    'audioEnabled',
    'ttsEnabled',
    'ttsAvailable'
  ])
  assert.deepEqual(uiStore.notice, { type: 'success', message: 'match hydrated' })
  assert.equal(uiStore.audioEnabled, true)
  assert.equal(uiStore.ttsEnabled, false)
  assert.equal(uiStore.ttsAvailable, true)
})

test('runtime hydration helper creates typed payloads without mutating stores', () => {
  setActivePinia(createPinia())
  const store = useGameStore()
  const liveGame = gameFixture('payload-game')

  const payloads = createStoreRuntimeHydration({
    currentView: ref('logs'),
    liveGame: ref(liveGame),
    replayCursor: ref(0),
    replaySpeed: ref(0)
  })

  assert.equal(payloads.session.currentView, 'logs')
  assert.equal(payloads.game.liveGame?.game_id, 'payload-game')
  assert.equal(payloads.replay.replayCursor, 0)
  assert.equal(payloads.replay.replaySpeed, 0)
  assert.equal(store.liveGame, null)
})

test('incremental runtime hydrator skips unchanged store payloads', () => {
  const stores = {
    session: { hydrateFromRuntime: vi.fn() },
    game: { hydrateFromRuntime: vi.fn() },
    history: { hydrateFromRuntime: vi.fn() },
    replay: { hydrateFromRuntime: vi.fn() },
    ui: { hydrateFromRuntime: vi.fn() }
  }
  const runtime = {
    currentView: ref('logs'),
    backendMode: ref('mock'),
    activeSession: ref(null),
    returnToMatchAvailable: ref(false),
    liveGame: ref(null),
    game: ref(null),
    loading: ref(false),
    error: ref(''),
    watchRunning: ref(false),
    roleAssignmentComplete: ref(false),
    judgeBoardStarted: ref(false),
    judgeBoardStarting: ref(false),
    promptText: ref(''),
    judgeStripMessage: ref([]),
    playerIdentityList: ref([]),
    matchRecordLogs: ref([]),
    livingPlayers: ref([]),
    speakerCarousel: ref([]),
    speakerMessage: ref(''),
    sceneVoteTally: ref([]),
    sceneEffects: ref([]),
    gameHistory: ref([]),
    selectedHistoryGameId: ref(null),
    selectedHistoryGame: ref(null),
    historyWorkspaceTab: ref('phase'),
    historyLoading: ref(false),
    historyPagination: ref({}),
    historyLoadingMore: ref(false),
    historySourceFilter: ref('all'),
    historyCounts: ref({}),
    historyFacets: ref({}),
    historyNotice: ref(null),
    historyHasMore: ref(false),
    historyCurrentPage: ref(1),
    historyTotalPages: ref(1),
    historyPages: ref([]),
    replayGame: ref(null),
    isReplayMode: ref(false),
    replayCursor: ref(0),
    replayPlaying: ref(false),
    replaySpeed: ref(1),
    audioEnabled: ref(false),
    ttsEnabled: ref(false),
    ttsAvailable: ref(true),
    matchNotice: ref(null)
  }
  const hydrator = createIncrementalRuntimeHydrator(stores)

  hydrator.hydrate(runtime)
  hydrator.hydrate(runtime)

  assert.equal(stores.session.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.game.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.history.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.replay.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.ui.hydrateFromRuntime.mock.calls.length, 1)

  runtime.audioEnabled.value = true
  hydrator.hydrate(runtime)

  assert.equal(stores.session.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.game.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.history.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.replay.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.ui.hydrateFromRuntime.mock.calls.length, 2)

  runtime.roleAssignmentComplete.value = true
  hydrator.hydrate(runtime)

  assert.equal(stores.session.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.game.hydrateFromRuntime.mock.calls.length, 2)
  assert.equal(stores.history.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.replay.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.ui.hydrateFromRuntime.mock.calls.length, 2)

  runtime.historyLoading.value = true
  const payloads = hydrator.hydrate(runtime)

  assert.equal(payloads.history.historyLoading, true)
  assert.equal(stores.session.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.game.hydrateFromRuntime.mock.calls.length, 2)
  assert.equal(stores.history.hydrateFromRuntime.mock.calls.length, 2)
  assert.equal(stores.replay.hydrateFromRuntime.mock.calls.length, 1)
  assert.equal(stores.ui.hydrateFromRuntime.mock.calls.length, 2)

  hydrator.reset()
  hydrator.hydrate(runtime)

  assert.equal(stores.session.hydrateFromRuntime.mock.calls.length, 2)
  assert.equal(stores.game.hydrateFromRuntime.mock.calls.length, 3)
  assert.equal(stores.history.hydrateFromRuntime.mock.calls.length, 3)
  assert.equal(stores.replay.hydrateFromRuntime.mock.calls.length, 2)
  assert.equal(stores.ui.hydrateFromRuntime.mock.calls.length, 3)
})
