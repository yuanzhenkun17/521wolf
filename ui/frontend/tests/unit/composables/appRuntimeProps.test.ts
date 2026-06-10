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
    gameHistory: ref([{ game_id: 'history-a' }]),
    backendMode: ref('api'),
    externalStatus: ref({ healthy: true }),
    loading: ref(false),
    playerCount: ref(12),
    apiFetch,
    game: ref({ game_id: 'match-a' }),
    selectedHistoryPageKey: ref('day-1')
  }

  assert.equal(bindRuntimeValue(ref('value-a')), 'value-a')
  assert.equal(readRuntimeValue(runtime, 'backendMode'), 'api')
  assert.deepEqual(pickRuntime(runtime, ['backendMode', 'playerCount']), {
    backendMode: 'api',
    playerCount: 12
  })

  const props = useAppRuntimeProps(runtime)

  assert.equal('gameHistory' in props.logsProps.value, false)
  assert.equal(props.logsProps.value.selectedHistoryPageKey, 'day-1')
  assert.equal(props.lobbyProps.value.backendMode, 'api')
  assert.equal(props.lobbyProps.value.apiFetch, apiFetch)
  assert.equal('game' in props.matchProps.value, false)
  assert.equal('backendMode' in props.matchProps.value, false)
})
