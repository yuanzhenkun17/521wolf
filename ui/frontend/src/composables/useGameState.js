import { ref } from 'vue'
import { createHistoryDerivedState } from './useHistoryDerivedState.js'
import { createLiveGameState } from './useLiveGameState.js'
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
} from './gameStateShared.js'

function useGameState() {
  const refs = createRefs()
  const injectedUtils = ref({})
  const { game } = refs
  let liveState = {}

  function setGameStateUtils(utils = {}) {
    injectedUtils.value = utils || {}
  }

  function playerNumberFallback(player) {
    if (!player) return ''
    return player.seat || player.id || ''
  }

  function playerLabel(player) {
    const fn = injectedUtils.value.playerLabel
    if (typeof fn === 'function') return fn(player)
    const number = playerNumberFallback(player)
    return number ? String(number) + '号' : ''
  }

  function playerNumberById(id) {
    const fn = injectedUtils.value.playerNumberById
    if (typeof fn === 'function') return fn(id)
    const player = game.value?.players?.find((item) => item.id === id)
    return player ? playerNumberFallback(player) : id
  }

  function normalizePlayerText(text = '') {
    const fn = injectedUtils.value.normalizePlayerText
    return typeof fn === 'function' ? fn(text) : String(text || '')
  }

  function cardImage(player) {
    const fn = injectedUtils.value.cardImage
    return typeof fn === 'function' ? fn(player) : fallbackCardImage(liveState.isWatch?.value, player)
  }

  function roleIconImage(player) {
    const fn = injectedUtils.value.roleIconImage
    return typeof fn === 'function' ? fn(player) : fallbackRoleIconImage(player)
  }

  function logSpeaker(log) {
    const fn = injectedUtils.value.logSpeaker
    return typeof fn === 'function' ? fn(log) : (log?.speaker || '')
  }

  function logMessage(log) {
    const fn = injectedUtils.value.logMessage
    return typeof fn === 'function' ? fn(log) : (log?.message || '')
  }

  function canSeeLog(log) {
    return log.visibility !== 'private' && (log.visibility !== 'god' || liveState.isWatch?.value)
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
