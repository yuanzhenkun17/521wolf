import { computed, isRef } from 'vue'
import { isAppView } from '../router/appViews'
import type { AppView } from '../types/ui'

type RuntimeRecord = Record<string, unknown>

const logsPropKeys = [
  'returnToMatchAvailable',
  'gameHistory',
  'selectedHistoryGameId',
  'selectedHistoryGame',
  'historyLoading',
  'historyPagination',
  'historyLoadingMore',
  'historySourceFilter',
  'historyStatusFilter',
  'historyCounts',
  'historyFacets',
  'historyNotice',
  'historyHasMore',
  'historyCurrentPage',
  'historyTotalPages',
  'historyPages',
  'selectedHistoryPageKey',
  'historyWorkspaceTab',
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
  'isReplayMode',
  'replayCursor',
  'replayPlaying',
  'replaySpeed',
  'replayTotal',
  'replayEventLabel',
  'assessDimension',
  'playerAssessmentScores',
  'activeAssessScores',
  'selectedDecision',
  'detailTab',
  'roleIconImage',
  'historyPageTitle',
  'historyPhaseName',
  'historyLogSpeaker',
  'historyNormalizeText',
  'nightActionDetail',
  'playerAliveAtPage',
  'archiveByGameId',
  'reviewByGameId',
  'flowDataByGameId',
  'flowLoadingByGameId',
  'archiveLoading',
  'reviewLoading',
  'loadMoreHistory',
  'loadMoreHistoryPhaseDetail',
  'goHistoryPage',
  'setHistorySourceFilter',
  'setHistoryStatusFilter',
  'deleteHistoryGame',
  'loadArchive',
  'loadReview',
  'loadFlowData',
  'formatJson'
]

const matchPropKeys = [
  'game',
  'loading',
  'matchNotice',
  'backendMode',
  'isNight',
  'isWatch',
  'isReplayMode',
  'replayCursor',
  'replayPlaying',
  'replaySpeed',
  'replayTotal',
  'replayEventLabel',
  'watchRunning',
  'skipIntroGameId',
  'roleAssignmentComplete',
  'judgeBoardStarted',
  'judgeBoardStarting',
  'promptText',
  'judgeStripMessage',
  'playerIdentityList',
  'chatLogExpanded',
  'chatLogs',
  'matchRecordLogs',
  'groupedJudgeLogs',
  'displayPhase',
  'livingPlayers',
  'roleStats',
  'speakerCarousel',
  'speakerMessage',
  'humanPlayer',
  'roleName',
  'skillState',
  'isHumanWitch',
  'isHumanWhiteWolf',
  'canUseWitchAntidote',
  'canUseWitchPoison',
  'canWhiteWolfBurst',
  'pendingActionType',
  'pendingChoiceOptions',
  'actionInstruction',
  'speechCountdownText',
  'canVotePlayers',
  'actionCandidates',
  'whiteWolfTargets',
  'needsTarget',
  'speech',
  'witchChoice',
  'actionChoice',
  'burstArmed',
  'actionTarget',
  'sceneVoteTally',
  'sceneEffects',
  'playerLabel',
  'roleIconImage',
  'logSpeaker',
  'logMessage',
  'historyPhaseName',
  'chooseScenePlayer'
]

export function bindRuntimeValue(value: unknown): unknown {
  return isRef(value) ? value.value : value
}

export function readRuntimeValue(runtime: RuntimeRecord, key: string): unknown {
  return bindRuntimeValue(runtime[key])
}

export function pickRuntime(runtime: RuntimeRecord, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(keys.map((key) => [key, readRuntimeValue(runtime, key)]))
}

export function useAppRuntimeProps(runtime: RuntimeRecord) {
  const readRuntime = (key: string) => readRuntimeValue(runtime, key)

  const runtimeCurrentView = computed<AppView>(() => {
    const view = String(readRuntime('currentView') || '')
    return isAppView(view) ? view : 'lobby'
  })

  return {
    readRuntime,
    logsProps: computed(() => pickRuntime(runtime, logsPropKeys)),
    benchmarkProps: computed(() => pickRuntime(runtime, ['returnToMatchAvailable'])),
    evolutionProps: computed(() => pickRuntime(runtime, ['returnToMatchAvailable'])),
    lobbyProps: computed(() => pickRuntime(runtime, ['backendMode', 'externalStatus', 'loading', 'playerCount', 'apiFetch'])),
    matchProps: computed(() => pickRuntime(runtime, matchPropKeys)),
    activeSession: computed(() => readRuntime('activeSession')),
    audioEnabled: computed(() => readRuntime('audioEnabled')),
    ttsEnabled: computed(() => readRuntime('ttsEnabled')),
    ttsAvailable: computed(() => readRuntime('ttsAvailable')),
    runtimeCurrentView
  }
}
