import { computed, isRef } from 'vue'

type RuntimeRecord = Record<string, unknown>

export function bindRuntimeValue(value: unknown): unknown {
  return isRef(value) ? value.value : value
}

export function readRuntimeValue(runtime: RuntimeRecord, key: string): unknown {
  return bindRuntimeValue(runtime[key])
}

export function pickRuntime(runtime: RuntimeRecord, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(keys.map((key) => [key, readRuntimeValue(runtime, key)]))
}

export function buildLogsRuntimeProps(runtime: RuntimeRecord): Record<string, unknown> {
  return {
    roleIconImage: readRuntimeValue(runtime, 'roleIconImage'),
    historyPageTitle: readRuntimeValue(runtime, 'historyPageTitle'),
    historyPhaseName: readRuntimeValue(runtime, 'historyPhaseName'),
    historyLogSpeaker: readRuntimeValue(runtime, 'historyLogSpeaker'),
    historyNormalizeText: readRuntimeValue(runtime, 'historyNormalizeText'),
    nightActionDetail: readRuntimeValue(runtime, 'nightActionDetail'),
    formatJson: readRuntimeValue(runtime, 'formatJson')
  }
}

export function buildLobbyRuntimeProps(runtime: RuntimeRecord): Record<string, unknown> {
  return {
    backendMode: readRuntimeValue(runtime, 'backendMode'),
    externalStatus: readRuntimeValue(runtime, 'externalStatus'),
    loading: readRuntimeValue(runtime, 'loading'),
    playerCount: readRuntimeValue(runtime, 'playerCount'),
    apiFetch: readRuntimeValue(runtime, 'apiFetch')
  }
}

export function buildMatchRuntimeProps(runtime: RuntimeRecord): Record<string, unknown> {
  return {
    playerLabel: readRuntimeValue(runtime, 'playerLabel'),
    roleIconImage: readRuntimeValue(runtime, 'roleIconImage'),
    logSpeaker: readRuntimeValue(runtime, 'logSpeaker'),
    logMessage: readRuntimeValue(runtime, 'logMessage'),
    historyPhaseName: readRuntimeValue(runtime, 'historyPhaseName')
  }
}

export function useAppRuntimeProps(runtime: RuntimeRecord) {
  return {
    logsProps: computed(() => buildLogsRuntimeProps(runtime)),
    lobbyProps: computed(() => buildLobbyRuntimeProps(runtime)),
    matchProps: computed(() => buildMatchRuntimeProps(runtime))
  }
}
