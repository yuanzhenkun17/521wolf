import { computed, ref } from 'vue'
import { currentLegacyView } from '../router/legacyViewNavigation'
import { roleIconSpecs, roleMatches } from './useMatchUtils.ts'

export { roleIconSpecs, roleMatches }

export const phaseText = {
  lobby: '选择模式',
  setup: '开局配置',
  night: '第{day}夜',
  day_speech: '第{day}天 · 白天发言',
  sheriff: '第{day}天 · 警长竞选',
  sheriff_election: '第{day}天 · 警长竞选',
  sheriff_result: '第{day}天 · 警长结果',
  sheriff_election_end: '第{day}天 · 警长结果',
  speech: '第{day}天 · 白天发言',
  vote: '第{day}天 · 公投放逐',
  exile_vote: '第{day}天 · 放逐投票',
  pk_vote: '第{day}天 · 对决投票',
  result: '第{day}天 · 结算',
  finished: '游戏结束',
  ended: '游戏结束'
}

export const phaseLabel = {
  lobby: '选择模式',
  setup: '开局配置',
  night: '黑夜行动',
  night_start: '黑夜开始',
  night_end: '黑夜结果',
  night_result: '黑夜结果',
  night_death_reveal: '死亡公布',
  day_speech: '白天发言',
  day_speech_start: '白天发言',
  day_speech_end: '发言结束',
  sheriff: '警长竞选',
  sheriff_election: '警长竞选',
  sheriff_election_start: '警长竞选',
  sheriff_election_end: '警长结果',
  sheriff_result: '警长结果',
  speech: '白天发言',
  vote: '公投放逐',
  exile_vote: '放逐投票',
  pk_vote: '对决投票',
  result: '结算',
  finished: '结束',
  ended: '终局'
}

export const decisionActionText = {
  speak: '发言',
  vote: '投票',
  kill: '狼人袭击',
  inspect: '预言查验',
  poison: '女巫毒药',
  antidote: '女巫解药',
  guard: '守卫守护',
  shoot: '猎人开枪',
  sheriff_run: '上警',
  sheriff_pass: '不上警',
  sheriff_speak: '警上发言',
  sheriff_withdraw: '退水',
  sheriff_stay: '留警上',
  sheriff_vote: '警长投票',
  sheriff_elect: '警长当选',
  sheriff_transfer: '移交警徽',
  sheriff_destroy: '撕毁警徽',
  white_wolf_burst: '白狼王自爆',
  white_wolf_explode: '白狼王自爆',
  guard_protect: '守卫守护',
  werewolf_kill: '狼人夜刀',
  seer_check: '预言查验',
  witch_act: '女巫行动',
  last_word: '遗言',
  pk_speak: '对决发言',
  pk_vote: '对决投票',
  hunter_shoot: '猎人开枪',
  speech_order: '发言顺序',
  sheriff_badge: '警徽处理',
  sheriff_badge_transfer: '移交警徽',
  sheriff_badge_destroy: '撕毁警徽',
  action_request: '行动请求',
  action_response: '行动响应',
  invalid_response: '非法响应',
  default_action: '默认行动',
  agent_error: '智能体错误',
  night_start: '黑夜开始',
  night_end: '黑夜结果',
  night_result: '黑夜结果',
  night_death_reveal: '死亡公布',
  day_speech_start: '白天发言',
  day_speech_end: '发言结束',
  vote_prompt: '投票提醒',
  exile: '放逐',
  exile_vote_start: '放逐投票',
  exile_vote_end: '放逐结果',
  exile_vote_tie: '平票',
  pk_vote_end: '对决投票结果',
  sheriff_start: '警长竞选',
  sheriff_result: '警长结果',
  sheriff_election_start: '警长竞选',
  sheriff_election_end: '警长结果',
  game_over: '游戏结束',
  game_end: '游戏结束',
  finished: '结束',
  ended: '终局'
}

export const historyPhaseTabs = [
  { key: 'all', label: '全部' },
  { key: 'setup', label: '配置' },
  { key: 'night', label: '黑夜' },
  { key: 'sheriff', label: '警长竞选' },
  { key: 'sheriff_result', label: '警长结果' },
  { key: 'speech', label: '发言' },
  { key: 'vote', label: '投票' },
  { key: 'result', label: '结算' },
  { key: 'ended', label: '终局' }
]

export function seatHash(value) {
  let hash = 2166136261
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function formatJson(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

export function compactList(value) {
  if (!value) return []
  return Array.isArray(value) ? value : [value]
}

export function fallbackCardImage(isWatch, player) {
  if (!isWatch && player && !player.is_human && !player.role_visible) return '/cards/card-back.png'
  const hint = player?.role_hint || ''
  if (hint.includes('预言')) return '/cards/seer.png'
  if (hint.includes('女巫')) return '/cards/witch.png'
  if (hint.includes('猎人')) return '/cards/hunter.png'
  if (hint.includes('守卫')) return '/cards/guard.png'
  if (hint.includes('白狼王')) return '/cards/white-wolf-king.png'
  if (hint.includes('狼人')) return '/cards/wolf.png'
  return '/cards/villager.png'
}

export function fallbackRoleIconImage(player) {
  const hint = player?.role_hint || ''
  if (hint.includes('预言')) return '/role-icons/optimized/预言家.webp'
  if (hint.includes('女巫')) return '/role-icons/optimized/女巫.webp'
  if (hint.includes('猎人')) return '/role-icons/optimized/猎人.webp'
  if (hint.includes('守卫')) return '/role-icons/optimized/守卫.webp'
  if (hint.includes('白狼王')) return '/role-icons/optimized/白狼王.webp'
  if (hint.includes('狼人')) return '/role-icons/optimized/普通狼.webp'
  return '/role-icons/optimized/平民.webp'
}

export function createRefs() {
  const liveGame = ref(null)
  const replayGame = ref(null)
  const isReplayMode = ref(false)
  const game = computed({
    get: () => (isReplayMode.value ? replayGame.value : liveGame.value),
    set: (value) => {
      if (isReplayMode.value) replayGame.value = value
      else liveGame.value = value
    }
  })
  return {
    game,
    liveGame,
    replayGame,
    loading: ref(false),
    error: ref(''),
    matchNotice: ref({ type: '', message: '' }),
    speech: ref('我先报一下自己的视角：目前重点听发言逻辑和票型。'),
    speechRemaining: ref(180),
    voteTarget: ref(1),
    actionTarget: ref(null),
    actionChoice: ref(''),
    witchChoice: ref('skip'),
    burstArmed: ref(false),
    playerCount: ref(12),
    watchRunning: ref(false),
    activeSession: ref({ gameId: null, mode: '', running: false, sseConnected: false }),
    backendMode: ref('mock'),
    externalStatus: ref(null),
    archiveByGameId: ref({}),
    reviewByGameId: ref({}),
    archiveLoading: ref(false),
    reviewLoading: ref(false),
    judgeBoardStarted: ref(false),
    judgeBoardStarting: ref(false),
    roleAssignmentComplete: ref(false),
    roleAssignmentCompleteNotice: ref(false),
    currentView: ref(currentLegacyView()),
    gameHistory: ref([]),
    selectedHistoryGameId: ref(null),
    selectedHistoryGame: ref(null),
    selectedHistoryShell: ref(null),
    selectedPhaseDetail: ref(null),
    phaseDetailByGameId: ref({}),
    phaseLoadingByKey: ref({}),
    phaseErrorByKey: ref({}),
    replayByGameId: ref({}),
    replayLoadingByGameId: ref({}),
    flowDataByGameId: ref({}),
    flowLoadingByGameId: ref({}),
    historyLoading: ref(false),
    historyPhase: ref('all'),
    historyWorkspaceTab: ref('phase'),
    assessDimension: ref('speech'),
    selectedHistoryPageKey: ref(''),
    isReplayMode,
    replaySourceGameId: ref(null),
    replayPageKey: ref(''),
    replayCursor: ref(0),
    replayPlaying: ref(false),
    replaySpeed: ref(1),
    replayTotal: ref(0),
    replayEventLabel: ref(''),
    lastLiveGame: ref(null),
    skipIntroGameId: ref(null),
    visualSeatSalt: ref(Math.random().toString(36).slice(2)),
    returnToMatchAvailable: ref(false),
    selectedDecision: ref(null),
    detailTab: ref('summary'),
    chatLogExpanded: ref(false),
    chatListRef: ref(null),
    judgeListRef: ref(null),
    judgeStripRef: ref(null),
    gameSceneRef: ref(null)
  }
}

export const judgeVisibleTypes = new Set([
  'action_prompt',
  'guard_protect',
  'werewolf_kill',
  'seer_check',
  'witch_act',
  'hunter_shoot',
  'white_wolf_explode',
  'sheriff_run',
  'sheriff_pass',
  'sheriff_withdraw',
  'sheriff_stay',
  'sheriff_vote',
  'exile_vote',
  'pk_vote',
  'sheriff_badge'
])
