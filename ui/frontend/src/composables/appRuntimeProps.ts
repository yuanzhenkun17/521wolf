import { computed, isRef } from 'vue'

type RuntimeRecord = Record<string, unknown>

const logsPropKeys = [
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
  'deleteHistoryGame',
  'loadArchive',
  'loadReview',
  'loadFlowData',
  'formatJson'
]

const matchPropKeys = [
  'playerLabel',
  'roleIconImage',
  'logSpeaker',
  'logMessage',
  'historyPhaseName'
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
  return {
    logsProps: computed(() => pickRuntime(runtime, logsPropKeys)),
    lobbyProps: computed(() => pickRuntime(runtime, ['backendMode', 'externalStatus', 'loading', 'playerCount', 'apiFetch'])),
    matchProps: computed(() => pickRuntime(runtime, matchPropKeys))
  }
}
