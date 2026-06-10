import { ref } from 'vue'
import { normalizeHistoryDisplayText } from '../components/history/historyDisplay.ts'
import { createHistoryDerivedState } from './useHistoryDerivedState.ts'
import { createLiveGameState } from './useLiveGameState.ts'
import {
  compactList,
  createRefs,
  decisionActionText,
  fallbackCardImage,
  fallbackRoleIconImage,
  formatJson,
  historyPhaseTabs,
  judgeVisibleTypes,
  phaseLabel,
  phaseText,
  roleIconSpecs,
  roleMatches,
  seatHash
} from './gameStateShared.ts'

type LooseRecord = Record<string, any>

const PLAYER_HIDDEN_NIGHT_ACTION_TYPES = new Set([
  'guard_protect',
  'guard',
  'werewolf_kill',
  'werewolf_attack',
  'wolf_kill',
  'seer_check',
  'seer_inspect',
  'inspect',
  'witch_act',
  'witch_save',
  'witch_poison'
])

function logTypes(log: LooseRecord = {}) {
  return [
    log.type,
    log.event_type,
    log.action,
    log.action_type,
    log.kind,
    log.category
  ].map((value) => String(value || '').trim()).filter(Boolean)
}

function useGameState() {
  const refs = createRefs()
  const injectedUtils = ref<LooseRecord>({})
  const { game } = refs
  let liveState: LooseRecord = {}

  function setGameStateUtils(utils: LooseRecord = {}) {
    injectedUtils.value = utils || {}
  }

  function playerNumberFallback(player: LooseRecord | null | undefined) {
    if (!player) return ''
    return player.seat || player.id || ''
  }

  function playerLabel(player: LooseRecord | null | undefined) {
    const fn = injectedUtils.value.playerLabel
    if (typeof fn === 'function') return fn(player)
    const number = playerNumberFallback(player)
    return number ? String(number) + '号' : ''
  }

  function playerNumberById(id: unknown) {
    const fn = injectedUtils.value.playerNumberById
    if (typeof fn === 'function') return fn(id)
    const player = game.value?.players?.find((item) => item.id === id)
    return player ? playerNumberFallback(player) : id
  }

  function normalizePlayerText(text = '') {
    const fn = injectedUtils.value.normalizePlayerText
    return typeof fn === 'function' ? fn(text) : normalizeHistoryDisplayText(text)
  }

  function cardImage(player: LooseRecord | null | undefined) {
    const fn = injectedUtils.value.cardImage
    return typeof fn === 'function' ? fn(player) : fallbackCardImage(liveState.isWatch?.value, player)
  }

  function roleIconImage(player: LooseRecord | null | undefined) {
    const fn = injectedUtils.value.roleIconImage
    return typeof fn === 'function' ? fn(player) : fallbackRoleIconImage(player)
  }

  function logSpeaker(log: LooseRecord | null | undefined) {
    const fn = injectedUtils.value.logSpeaker
    return typeof fn === 'function' ? fn(log) : (log?.speaker || '')
  }

  function logMessage(log: LooseRecord | null | undefined) {
    const fn = injectedUtils.value.logMessage
    return typeof fn === 'function' ? fn(log) : normalizeHistoryDisplayText(log?.message || '')
  }

  function canSeeLog(log: LooseRecord) {
    if (liveState.isWatch?.value || refs.isReplayMode.value) return true
    if (log.visibility === 'private') return false
    if (log.visibility === 'god' && !liveState.isWatch?.value) return false
    if (!liveState.isWatch?.value && !refs.isReplayMode.value && !game.value?.winner) {
      if (logTypes(log).some((type) => PLAYER_HIDDEN_NIGHT_ACTION_TYPES.has(type))) return false
    }
    return true
  }

  liveState = createLiveGameState(refs, {
    canSeeLog,
    playerLabel,
    playerNumberById,
    normalizePlayerText,
    cardImage,
    roleIconImage,
    logSpeaker,
    logMessage
  })
  const historyState = createHistoryDerivedState(refs, liveState, { logSpeaker, logMessage })

  return {
    phaseText,
    phaseLabel,
    roleIconSpecs,
    roleMatches,
    decisionActionText,
    historyPhaseTabs,
    judgeVisibleTypes,
    ...refs,
    ...liveState,
    ...historyState,
    setGameStateUtils,
    canSeeLog,
    seatHash,
    formatJson,
    compactList
  }
}

export {
  phaseText,
  phaseLabel,
  decisionActionText,
  historyPhaseTabs,
  seatHash,
  formatJson,
  compactList,
  useGameState
}
