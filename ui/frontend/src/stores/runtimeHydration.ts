import { isRef } from 'vue'
import type { GameRuntimeHydration } from './game'
import type { HistoryRuntimeHydration } from './history'
import type { ReplayRuntimeHydration } from './replay'
import type { SessionRuntimeHydration } from './session'
import type { UiRuntimeHydration } from './ui'

type RuntimeHydrationSource = Record<string, unknown>

interface StoreHydrator<TPayload> {
  hydrateFromRuntime(payload: TPayload): void
}

export interface RuntimeHydrationStores {
  session: StoreHydrator<SessionRuntimeHydration>
  game: StoreHydrator<GameRuntimeHydration>
  history: StoreHydrator<HistoryRuntimeHydration>
  replay: StoreHydrator<ReplayRuntimeHydration>
  ui: StoreHydrator<UiRuntimeHydration>
}

export interface RuntimeHydrationPayloads {
  session: SessionRuntimeHydration
  game: GameRuntimeHydration
  history: HistoryRuntimeHydration
  replay: ReplayRuntimeHydration
  ui: UiRuntimeHydration
}

export interface IncrementalRuntimeHydrator {
  hydrate(runtime: RuntimeHydrationSource): RuntimeHydrationPayloads
  reset(): void
}

export const runtimeHydrationKeys = {
  session: ['currentView', 'backendMode', 'activeSession', 'returnToMatchAvailable'],
  game: [
    'liveGame',
    'game',
    'loading',
    'error',
    'watchRunning',
    'roleAssignmentComplete',
    'judgeBoardStarted',
    'judgeBoardStarting'
  ],
  history: [
    'gameHistory',
    'selectedHistoryGameId',
    'selectedHistoryGame',
    'historyWorkspaceTab',
    'historyLoading',
    'historyNotice'
  ],
  replay: ['replayGame', 'isReplayMode', 'replayCursor', 'replayPlaying', 'replaySpeed'],
  ui: ['error', 'matchNotice', 'historyNotice']
} as const satisfies {
  session: readonly (keyof SessionRuntimeHydration)[]
  game: readonly (keyof GameRuntimeHydration)[]
  history: readonly (keyof HistoryRuntimeHydration)[]
  replay: readonly (keyof ReplayRuntimeHydration)[]
  ui: readonly (keyof UiRuntimeHydration)[]
}

function readRuntimeValue(runtime: RuntimeHydrationSource, key: string): unknown {
  const value = runtime[key]
  return isRef(value) ? value.value : value
}

function pickRuntimePayload<TPayload extends object>(
  runtime: RuntimeHydrationSource,
  keys: readonly (keyof TPayload & string)[]
): TPayload {
  return Object.fromEntries(keys.map((key) => [key, readRuntimeValue(runtime, key)])) as TPayload
}

export function createStoreRuntimeHydration(runtime: RuntimeHydrationSource): RuntimeHydrationPayloads {
  return {
    session: pickRuntimePayload<SessionRuntimeHydration>(runtime, runtimeHydrationKeys.session),
    game: pickRuntimePayload<GameRuntimeHydration>(runtime, runtimeHydrationKeys.game),
    history: pickRuntimePayload<HistoryRuntimeHydration>(runtime, runtimeHydrationKeys.history),
    replay: pickRuntimePayload<ReplayRuntimeHydration>(runtime, runtimeHydrationKeys.replay),
    ui: pickRuntimePayload<UiRuntimeHydration>(runtime, runtimeHydrationKeys.ui)
  }
}

export function hydrateStoresFromRuntime(
  runtime: RuntimeHydrationSource,
  stores: RuntimeHydrationStores
): RuntimeHydrationPayloads {
  const payloads = createStoreRuntimeHydration(runtime)
  stores.session.hydrateFromRuntime(payloads.session)
  stores.game.hydrateFromRuntime(payloads.game)
  stores.history.hydrateFromRuntime(payloads.history)
  stores.replay.hydrateFromRuntime(payloads.replay)
  stores.ui.hydrateFromRuntime(payloads.ui)
  return payloads
}

function payloadChanged<TPayload extends object>(previous: TPayload | undefined, next: TPayload): boolean {
  if (!previous) return true
  const previousKeys = Object.keys(previous)
  const nextKeys = Object.keys(next)
  if (previousKeys.length !== nextKeys.length) return true
  return nextKeys.some((key) => !Object.is(
    previous[key as keyof TPayload],
    next[key as keyof TPayload]
  ))
}

export function createIncrementalRuntimeHydrator(stores: RuntimeHydrationStores): IncrementalRuntimeHydrator {
  let previous: Partial<RuntimeHydrationPayloads> = {}

  return {
    hydrate(runtime) {
      const payloads = createStoreRuntimeHydration(runtime)

      if (payloadChanged(previous.session, payloads.session)) {
        stores.session.hydrateFromRuntime(payloads.session)
        previous.session = payloads.session
      }
      if (payloadChanged(previous.game, payloads.game)) {
        stores.game.hydrateFromRuntime(payloads.game)
        previous.game = payloads.game
      }
      if (payloadChanged(previous.history, payloads.history)) {
        stores.history.hydrateFromRuntime(payloads.history)
        previous.history = payloads.history
      }
      if (payloadChanged(previous.replay, payloads.replay)) {
        stores.replay.hydrateFromRuntime(payloads.replay)
        previous.replay = payloads.replay
      }
      if (payloadChanged(previous.ui, payloads.ui)) {
        stores.ui.hydrateFromRuntime(payloads.ui)
        previous.ui = payloads.ui
      }

      return payloads
    },
    reset() {
      previous = {}
    }
  }
}
