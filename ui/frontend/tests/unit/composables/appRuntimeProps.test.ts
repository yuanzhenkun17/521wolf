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
  const roleIconImage = () => '/role-icons/optimized/villager.webp'
  const loadArchive = () => Promise.resolve({})
  const runtime = {
    currentView: ref('logs'),
    gameHistory: ref([{ game_id: 'history-a' }]),
    backendMode: ref('api'),
    externalStatus: ref({ healthy: true }),
    loading: ref(false),
    playerCount: ref(12),
    apiFetch,
    game: ref({ game_id: 'match-a' }),
    speech: ref('runtime speech'),
    actionTarget: ref(2),
    selectedHistoryPageKey: ref('day-1'),
    historyWorkspaceTab: ref('archive'),
    selectedHistoryPage: ref({ key: 'day-1' }),
    historyLogs: ref([{ message: 'runtime log' }]),
    playerAssessmentScores: ref([{ player: { id: 1 } }]),
    archiveByGameId: ref({ 'history-a': { archive_id: 'archive-a' } }),
    archiveLoading: ref(true),
    roleIconImage,
    loadArchive
  }

  assert.equal(bindRuntimeValue(ref('value-a')), 'value-a')
  assert.equal(readRuntimeValue(runtime, 'backendMode'), 'api')
  assert.deepEqual(pickRuntime(runtime, ['backendMode', 'playerCount']), {
    backendMode: 'api',
    playerCount: 12
  })

  const props = useAppRuntimeProps(runtime)

  assert.equal('gameHistory' in props.logsProps.value, false)
  assert.equal('selectedHistoryPageKey' in props.logsProps.value, false)
  assert.equal('historyWorkspaceTab' in props.logsProps.value, false)
  assert.equal('selectedHistoryPage' in props.logsProps.value, false)
  assert.equal('historyLogs' in props.logsProps.value, false)
  assert.equal('playerAssessmentScores' in props.logsProps.value, false)
  assert.equal('archiveByGameId' in props.logsProps.value, false)
  assert.equal('archiveLoading' in props.logsProps.value, false)
  assert.equal(props.logsProps.value.roleIconImage, roleIconImage)
  assert.equal('loadArchive' in props.logsProps.value, false)
  assert.equal(props.lobbyProps.value.backendMode, 'api')
  assert.equal(props.lobbyProps.value.apiFetch, apiFetch)
  assert.equal('game' in props.matchProps.value, false)
  assert.equal('backendMode' in props.matchProps.value, false)
  assert.equal('speech' in props.matchProps.value, false)
  assert.equal('actionTarget' in props.matchProps.value, false)
})
