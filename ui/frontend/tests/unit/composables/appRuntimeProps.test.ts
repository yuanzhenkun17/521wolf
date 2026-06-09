import assert from 'node:assert/strict'
import { ref } from 'vue'
import { test } from 'vitest'
import {
  bindRuntimeValue,
  pickRuntime,
  readRuntimeValue,
  useAppRuntimeProps
} from '../../../src/composables/appRuntimeProps'

test('unwraps runtime refs when building page prop payloads', () => {
  const apiFetch = () => Promise.resolve({})
  const runtime = {
    currentView: ref('logs'),
    returnToMatchAvailable: ref(true),
    gameHistory: ref([{ game_id: 'history-a' }]),
    backendMode: ref('api'),
    externalStatus: ref({ healthy: true }),
    loading: ref(false),
    playerCount: ref(12),
    apiFetch,
    game: ref({ game_id: 'match-a' }),
    audioEnabled: ref(true),
    ttsEnabled: ref(false),
    ttsAvailable: ref(true)
  }

  assert.equal(bindRuntimeValue(ref('value-a')), 'value-a')
  assert.equal(readRuntimeValue(runtime, 'backendMode'), 'api')
  assert.deepEqual(pickRuntime(runtime, ['backendMode', 'playerCount']), {
    backendMode: 'api',
    playerCount: 12
  })

  const props = useAppRuntimeProps(runtime)

  assert.equal(props.runtimeCurrentView.value, 'logs')
  assert.equal(props.logsProps.value.returnToMatchAvailable, true)
  assert.deepEqual(props.logsProps.value.gameHistory, [{ game_id: 'history-a' }])
  assert.equal(props.lobbyProps.value.backendMode, 'api')
  assert.equal(props.lobbyProps.value.apiFetch, apiFetch)
  assert.deepEqual(props.matchProps.value.game, { game_id: 'match-a' })
  assert.equal(props.activeSession.value, undefined)
  assert.equal(props.audioEnabled.value, true)
  assert.equal(props.ttsEnabled.value, false)
  assert.equal(props.ttsAvailable.value, true)
})

test('falls back to lobby for invalid runtime views', () => {
  const props = useAppRuntimeProps({ currentView: ref('unknown-view') })

  assert.equal(props.runtimeCurrentView.value, 'lobby')
})
