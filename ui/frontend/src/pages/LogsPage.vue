<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import type { PropType } from 'vue'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import HistoryGameList from '../components/HistoryGameList.vue'
import MultiAssess from '../components/MultiAssess.vue'
import NightSection from '../components/NightSection.vue'
import PhaseTabs from '../components/PhaseTabs.vue'
import SeatLedger from '../components/SeatLedger.vue'
import SpeechSection from '../components/SpeechSection.vue'
import VoteSection from '../components/VoteSection.vue'
import EvidenceContextBar from '../components/history/EvidenceContextBar.vue'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../composables/apiErrorDisplay.ts'
import {
  displayActionLabel,
  displayPhaseLabel,
  displayRoleLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.ts'

const GameArchivePanel = defineAsyncComponent(() => import('../components/history/GameArchivePanel.vue'))
const ReviewReportPanel = defineAsyncComponent(() => import('../components/history/ReviewReportPanel.vue'))

type LooseRecord = Record<string, any>
type LooseFn = (...args: any[]) => any
type RowFilterOptions = {
  includeTarget?: boolean
  includeText?: boolean
}

const props = defineProps({
  returnToMatchAvailable: Boolean,
  gameHistory: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  selectedHistoryGameId: [String, Number, null],
  selectedHistoryGame: Object as PropType<LooseRecord | null>,
  historyLoading: Boolean,
  historyPagination: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  historyLoadingMore: Boolean,
  historySourceFilter: { type: String, default: 'all' },
  historyCounts: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  historyFacets: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  historyNotice: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  historyHasMore: Boolean,
  historyCurrentPage: { type: Number, default: 1 },
  historyTotalPages: { type: Number, default: 1 },
  historyPages: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  selectedHistoryPageKey: { type: String, default: '' },
  historyWorkspaceTab: { type: String, default: 'phase' },
  selectedHistoryPage: Object as PropType<LooseRecord | null>,
  phaseLoadingByKey: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  historyLogs: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  pageNightActions: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  pageSpeechDecisions: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  sheriffVotes: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  voteDecisions: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  currentVoteTally: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  sheriffVoteTally: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  pageLastWords: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  nightResult: { type: String, default: '' },
  sheriffResult: Object as PropType<LooseRecord | null>,
  isReplayMode: Boolean,
  replayCursor: { type: Number, default: 0 },
  replayPlaying: Boolean,
  replaySpeed: { type: Number, default: 1 },
  replayTotal: { type: Number, default: 0 },
  replayEventLabel: { type: String, default: '' },
  assessDimension: { type: String, default: 'speech' },
  playerAssessmentScores: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  activeAssessScores: { type: Array as PropType<LooseRecord[]>, default: () => [] },
  selectedDecision: Object as PropType<LooseRecord | null>,
  detailTab: { type: String, default: 'summary' },
  roleIconImage: Function as PropType<(player: any) => string>,
  historyPageTitle: Function as PropType<(page: LooseRecord) => string>,
  historyPhaseName: Function as PropType<(phase: any) => string>,
  historyLogSpeaker: Function as PropType<(log: LooseRecord) => string>,
  historyNormalizeText: Function as PropType<(text: any) => string>,
  nightActionDetail: Function as PropType<(decision: LooseRecord) => unknown>,
  playerAliveAtPage: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  archiveByGameId: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  reviewByGameId: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  flowDataByGameId: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  flowLoadingByGameId: { type: Object as PropType<LooseRecord>, default: () => ({}) },
  archiveLoading: Boolean,
  reviewLoading: Boolean,
  loadMoreHistory: Function as PropType<LooseFn>,
  loadMoreHistoryPhaseDetail: Function as PropType<LooseFn>,
  goHistoryPage: Function as PropType<LooseFn>,
  setHistorySourceFilter: Function as PropType<LooseFn>,
  deleteHistoryGame: Function as PropType<LooseFn>,
  loadArchive: Function as PropType<LooseFn>,
  loadReview: Function as PropType<LooseFn>,
  loadFlowData: Function as PropType<LooseFn>,
  formatJson: Function as PropType<LooseFn>
})

const emit = defineEmits([
  'back-to-match',
  'select-history-game',
  'replay-game',
  'select-page',
  'update:selectedHistoryPageKey',
  'update:historyWorkspaceTab',
  'update:assessDimension',
  'update:selectedDecision',
  'update:detailTab',
  'return-to-history',
  'exit-replay',
  'play-replay',
  'pause-replay',
  'step-replay',
  'seek-replay',
  'set-replay-speed'
])

const selectedAssessPlayerId = ref<any>(null)
const workspaceTab = ref('phase')
const rawLogFilter = ref('all')
const expandedPhaseEvidenceKeys = ref<Set<string>>(new Set())
const WORKSPACE_TAB_KEYS = new Set(['phase', 'review', 'archive'])
const NIGHT_PHASES = new Set(['night'])
const SPEECH_PHASES = new Set(['speech', 'sheriff'])
const VOTE_PHASES = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote', 'sheriff_result'])
const RESULT_PHASES = new Set(['result', 'finished', 'ended'])
const SHERIFF_VOTE_PHASES = new Set(['sheriff_vote', 'sheriff_result'])
const RAW_LOG_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'system', label: '系统' },
  { key: 'action', label: '行动' },
  { key: 'vote', label: '投票' },
  { key: 'error', label: '异常' }
]
const canShowRawLogs = computed(() =>
  props.historyLogs.length > 0
  && props.selectedHistoryPage
)
const gameHistoryForList = computed<any[]>(() => props.gameHistory)
const historyPagesForTabs = computed<any[]>(() => props.historyPages)
const activeAssessScoresForPanel = computed<any[]>(() => props.activeAssessScores)
const focusedPlayerId = computed(() => normalizePlayerId(selectedAssessPlayerId.value))
const focusedPlayer = computed(() => {
  const id = focusedPlayerId.value
  if (id == null) return null
  return (props.selectedHistoryGame?.players || []).find((player) => samePlayer(player?.id ?? player?.seat, id)) || null
})
const hasPlayerFocus = computed(() => focusedPlayerId.value != null)
const rawLogsForFocus = computed(() => props.historyLogs.filter((log) => rowMatchesFocusedPlayer(log, { includeText: true })))
const filteredRawLogs = computed(() =>
  rawLogsForFocus.value.filter((log) => rawLogFilter.value === 'all' || rawLogKind(log) === rawLogFilter.value)
)
const visibleRawLogs = computed(() => filteredRawLogs.value.slice(0, 180))
const rawLogFilters = computed(() =>
  RAW_LOG_FILTERS.map((item) => ({
    ...item,
    count: item.key === 'all'
      ? rawLogsForFocus.value.length
      : rawLogsForFocus.value.filter((log) => rawLogKind(log) === item.key).length
  })).filter((item) => item.key === 'all' || item.count > 0)
)
const selectedReview = computed(() => props.reviewByGameId[props.selectedHistoryGame?.game_id] || null)
const selectedArchive = computed(() => props.archiveByGameId[props.selectedHistoryGame?.game_id] || null)
const selectedFlowData = computed(() => props.flowDataByGameId[props.selectedHistoryGame?.game_id] || null)
const selectedFlowLoading = computed(() => Boolean(props.flowLoadingByGameId[props.selectedHistoryGame?.game_id]))
const detailInlineNotice = computed(() => inlineNoticeForDisplay(props.historyNotice))
const detailErrorNotice = computed(() => noticeErrorForPanel(props.historyNotice))
const selectedGameConfig = computed(() => {
  const game = props.selectedHistoryGame || {}
  const config = game.config && typeof game.config === 'object' ? game.config : {}
  return {
    ...config,
    seed: game.seed ?? config.seed,
    max_days: game.max_days ?? config.max_days,
    enable_sheriff: game.enable_sheriff ?? config.enable_sheriff,
    skill_dir: game.skill_dir ?? config.skill_dir,
    role_skill_dirs: game.role_skill_dirs ?? config.role_skill_dirs,
    player_count: game.player_count ?? config.player_count,
    human_player_id: game.human_player_id ?? config.human_player_id
  }
})
const reviewLoaded = computed(() => Boolean(selectedReview.value && !selectedReview.value.error))
const archiveLoaded = computed(() => Boolean(selectedArchive.value && !selectedArchive.value.error))
const selectedPhasePagination = computed(() => props.selectedHistoryPage?.pagination || {})
const phaseHasMore = computed(() =>
  Boolean(selectedPhasePagination.value.logs?.has_more || selectedPhasePagination.value.decisions?.has_more)
)
const selectedPhaseLoadingKey = computed(() => {
  const gameId = props.selectedHistoryGame?.game_id || props.selectedHistoryGameId || ''
  const pageKey = props.selectedHistoryPage?.key || props.selectedHistoryPageKey || ''
  return gameId && pageKey ? `${gameId}:${pageKey}` : ''
})
const selectedPhaseLoading = computed(() =>
  Boolean(props.phaseLoadingByKey[selectedPhaseLoadingKey.value])
)
const detailRetrying = computed(() =>
  Boolean(
    props.historyLoading ||
    selectedPhaseLoading.value ||
    props.archiveLoading ||
    props.reviewLoading ||
    selectedFlowLoading.value
  )
)
const detailRetryAvailable = computed(() => {
  const gameId = props.selectedHistoryGame?.game_id || props.selectedHistoryGameId
  if (!gameId) return false
  if (workspaceTab.value === 'review') return Boolean(props.loadReview)
  if (workspaceTab.value === 'archive') return Boolean(props.loadArchive)
  return Boolean(props.loadMoreHistoryPhaseDetail && (props.selectedHistoryPage?.key || props.selectedHistoryPageKey))
})
const detailRetryDisabled = computed(() => detailRetrying.value || !detailRetryAvailable.value)
const phaseMoreMeta = computed(() => {
  const logs = selectedPhasePagination.value.logs || {}
  const decisions = selectedPhasePagination.value.decisions || {}
  const parts = []
  if (logs.has_more) {
    const loaded = Number(logs.offset || 0) + Number(logs.returned || props.historyLogs.length || 0)
    parts.push(`日志 ${loaded}/${Number(logs.total || loaded)}`)
  }
  if (decisions.has_more) {
    const currentDecisions = props.pageNightActions.length + props.pageSpeechDecisions.length + props.voteDecisions.length + props.sheriffVotes.length + props.pageLastWords.length
    const loaded = Number(decisions.offset || 0) + Number(decisions.returned || currentDecisions || 0)
    parts.push(`决策 ${loaded}/${Number(decisions.total || loaded)}`)
  }
  return parts.join(' · ')
})

function assessOverallScore(item: any) {
  const value = Number(item?.role_score ?? item?.score ?? 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, value))
}

const activeAssessPlayerId = computed(() => {
  const current = selectedAssessPlayerId.value
  if (current != null && props.activeAssessScores.some((item) => item.player?.id === current)) {
    return current
  }
  const topScore = [...props.activeAssessScores]
    .sort((a, b) => assessOverallScore(b) - assessOverallScore(a) || Number(a.player?.seat || 0) - Number(b.player?.seat || 0))[0]
  return topScore?.player?.id || props.selectedHistoryGame?.players?.[0]?.id || null
})

const phaseCategory = computed(() => {
  const phase = props.selectedHistoryPage?.phase || ''
  if (NIGHT_PHASES.has(phase)) return 'night'
  if (SPEECH_PHASES.has(phase)) return 'speech'
  if (VOTE_PHASES.has(phase)) return 'vote'
  if (RESULT_PHASES.has(phase)) return 'result'
  if (phase === 'setup') return 'setup'
  return 'event'
})

const focusedNightActions = computed(() =>
  props.pageNightActions.filter((item) => rowMatchesFocusedPlayer(item))
)
const focusedSpeechDecisions = computed(() =>
  props.pageSpeechDecisions.filter((item) => rowMatchesFocusedPlayer(item, { includeText: true }))
)
const activeVoteDecisions = computed(() =>
  SHERIFF_VOTE_PHASES.has(props.selectedHistoryPage?.phase) ? props.sheriffVotes : props.voteDecisions
)
const activeVoteTally = computed(() =>
  SHERIFF_VOTE_PHASES.has(props.selectedHistoryPage?.phase) ? props.sheriffVoteTally : props.currentVoteTally
)
const focusedVoteDecisions = computed(() =>
  activeVoteDecisions.value.filter((item) => rowMatchesFocusedPlayer(item, { includeTarget: true }))
)
const focusedVoteTally = computed(() =>
  hasPlayerFocus.value ? tallyVoteRows(focusedVoteDecisions.value) : activeVoteTally.value
)
const focusedLastWords = computed(() =>
  props.pageLastWords.filter((item) => rowMatchesFocusedPlayer(item, { includeText: true }))
)
const focusedDecisionCount = computed(() =>
  focusedNightActions.value.length
  + focusedSpeechDecisions.value.length
  + focusedVoteDecisions.value.length
  + focusedLastWords.value.length
)
const focusLabel = computed(() => {
  const player = focusedPlayer.value
  if (!player) return focusedPlayerId.value == null ? '' : `${focusedPlayerId.value}号`
  return `${player.seat ?? player.id}号 ${roleLabel(player.role_hint || player.role)}`
})
const phaseDetailCount = computed(() => {
  if (phaseCategory.value === 'night') return focusedNightActions.value.length
  if (phaseCategory.value === 'speech') return focusedSpeechDecisions.value.length + focusedLastWords.value.length
  if (phaseCategory.value === 'vote') return focusedVoteDecisions.value.length
  return focusedDecisionCount.value
})
const canShowPhaseDecisionPanel = computed(() =>
  ['night', 'speech', 'vote'].includes(phaseCategory.value) || focusedLastWords.value.length > 0
)
const phaseDecisionPanelMeta = computed(() => {
  const scope = hasPlayerFocus.value ? focusLabel.value : '全员'
  if (phaseCategory.value === 'vote') return `${scope} · ${phaseDetailCount.value} 条投票决策`
  if (phaseCategory.value === 'speech') return `${scope} · ${phaseDetailCount.value} 条发言/遗言`
  if (phaseCategory.value === 'night') return `${scope} · ${phaseDetailCount.value} 条夜间行动`
  return `${scope} · ${phaseDetailCount.value} 条结构化记录`
})
const nightMatrixRows = computed(() =>
  focusedNightActions.value.map((action, index) => ({
    key: decisionKey(action, index),
    action,
    actor: actorLabel(action),
    actionName: actionLabel(action),
    target: targetLabel(action) || '无目标',
    result: props.nightActionDetail ? props.nightActionDetail(action) : decisionSummary(action),
    confidence: confidencePercent(action)
  }))
)
const speechTimelineRows = computed(() =>
  focusedSpeechDecisions.value.map((decision, index) => ({
    key: decisionKey(decision, index),
    decision,
    actor: actorLabel(decision),
    role: roleLabel(decision.roleName || decision.role || decision.role_hint),
    summary: decisionSummary(decision),
    tags: speechTags(decision),
    confidence: confidencePercent(decision)
  }))
)
const voteRankingRows = computed(() => {
  const max = Math.max(...focusedVoteTally.value.map((item) => voteCount(item)), 1)
  return [...focusedVoteTally.value].sort((a, b) => voteCount(b) - voteCount(a) || String(targetLabel(a)).localeCompare(String(targetLabel(b)))).map((item, index) => ({
    key: targetLabel(item) || `vote-target-${index}`,
    label: targetLabel(item) || '未知目标',
    count: voteCount(item),
    percent: Math.round((voteCount(item) / max) * 100),
    voters: voterLabels(item),
    tone: index === 0 ? 'lead' : 'normal'
  }))
})
const voteAnomalyRows = computed(() => {
  if (phaseCategory.value !== 'vote') return []
  const rows = []
  const votes = focusedVoteDecisions.value
  const abstains = votes.filter((vote) => !targetLabel(vote) || targetLabel(vote) === '无目标')
  const top = voteRankingRows.value[0]
  const tied = top && voteRankingRows.value.filter((row) => row.count === top.count).length > 1
  if (abstains.length) rows.push({ key: 'abstain', tone: 'warning', text: `${abstains.length} 票未指向有效目标` })
  if (tied) rows.push({ key: 'tie', tone: 'warning', text: `最高票出现并列：${voteRankingRows.value.filter((row) => row.count === top.count).map((row) => row.label).join('、')}` })
  if (!hasPlayerFocus.value) {
    const totalPlayers = props.selectedHistoryGame?.players?.length || 0
    const participated = new Set(votes.map((vote) => String(normalizePlayerId(rowActorId(vote)))).filter(Boolean)).size
    if (totalPlayers && participated && participated < totalPlayers) {
      rows.push({ key: 'missing', tone: 'info', text: `${totalPlayers - participated} 名玩家未留下投票决策记录` })
    }
  }
  if (hasPlayerFocus.value && !votes.length) rows.push({ key: 'focus-empty', tone: 'info', text: `${focusLabel.value}在本阶段没有可匹配的投票记录` })
  return rows.slice(0, 3)
})
const phaseConclusion = computed(() => {
  const focusPrefix = hasPlayerFocus.value ? `${focusLabel.value}：` : ''
  if (phaseCategory.value === 'night') {
    if (hasPlayerFocus.value && focusedNightActions.value.length) return `${focusPrefix}${focusedNightActions.value.length} 条夜间行动，${props.nightResult || '暂无结算文本'}`
    return props.nightResult || `${focusedNightActions.value.length} 条夜间行动记录`
  }
  if (phaseCategory.value === 'speech') {
    const speakers = new Set(focusedSpeechDecisions.value.map((item) => String(normalizePlayerId(rowActorId(item)))).filter(Boolean)).size
    return `${focusPrefix}${speakers || focusedSpeechDecisions.value.length} 名玩家发言，${speechTimelineRows.value.flatMap((row) => row.tags).length} 个关键信号`
  }
  if (phaseCategory.value === 'vote') {
    const top = voteRankingRows.value[0]
    const result = props.selectedHistoryPage?.phase === 'sheriff_result' ? props.sheriffResult?.message : ''
    if (top) return `${focusPrefix}最高票 ${top.label}，${top.count} 票${result ? `；${normalizeText(result)}` : ''}`
    return `${focusPrefix}暂无可统计票型`
  }
  if (phaseCategory.value === 'result') return `最终胜方：${winnerLabel(props.selectedHistoryGame?.winner)}`
  if (phaseCategory.value === 'setup') return `角色、规则和初始状态已记录，原始记录 ${rawLogsForFocus.value.length} 条`
  return hasPlayerFocus.value ? `${focusPrefix}${focusedDecisionCount.value || rawLogsForFocus.value.length} 条相关记录` : selectedPhaseSummary.value
})
const phaseSummaryCards = computed(() => {
  if (phaseCategory.value === 'night') {
    const targets = new Set(focusedNightActions.value.map((item) => targetLabel(item)).filter((item) => item && item !== '无目标'))
    return [
      { label: '行动', value: focusedNightActions.value.length },
      { label: '目标', value: targets.size },
      { label: '结算', value: props.nightResult ? '有' : '无' },
      { label: '原始', value: rawLogsForFocus.value.length }
    ]
  }
  if (phaseCategory.value === 'speech') {
    const tags = new Set(speechTimelineRows.value.flatMap((row) => row.tags))
    return [
      { label: '发言', value: focusedSpeechDecisions.value.length },
      { label: '玩家', value: new Set(focusedSpeechDecisions.value.map((item) => String(normalizePlayerId(rowActorId(item)))).filter(Boolean)).size },
      { label: '信号', value: tags.size },
      { label: '原始', value: rawLogsForFocus.value.length }
    ]
  }
  if (phaseCategory.value === 'vote') {
    return [
      { label: '投票', value: focusedVoteDecisions.value.length },
      { label: '候选', value: focusedVoteTally.value.length },
      { label: '最高', value: voteRankingRows.value[0]?.count ?? 0 },
      { label: '提示', value: voteAnomalyRows.value.length }
    ]
  }
  return [
    { label: '日志', value: rawLogsForFocus.value.length },
    { label: '夜间', value: focusedNightActions.value.length },
    { label: '发言', value: focusedSpeechDecisions.value.length },
    { label: '投票', value: focusedVoteDecisions.value.length }
  ]
})

const phaseEvidenceKey = computed(() => {
  const gameId = props.selectedHistoryGame?.game_id ?? props.selectedHistoryGameId ?? 'game'
  const pageKey = props.selectedHistoryPage?.key ?? props.selectedHistoryPageKey ?? props.selectedHistoryPage?.phase ?? 'phase'
  return `${gameId}::${pageKey}`
})

const phaseEvidenceBodyId = computed(() =>
  `phase-evidence-body-${String(phaseEvidenceKey.value).replace(/[^a-zA-Z0-9_-]/g, '-')}`
)

const phaseEvidenceExpanded = computed(() =>
  expandedPhaseEvidenceKeys.value.has(phaseEvidenceKey.value)
)
const phaseEvidenceExpandedAttr = computed(() => String(phaseEvidenceExpanded.value) as 'true' | 'false')

const phaseEvidenceScope = computed(() =>
  hasPlayerFocus.value ? focusLabel.value : '全员'
)

const phaseEvidenceCountLabel = computed(() => {
  if (phaseCategory.value === 'vote') return `${voteRankingRows.value.length} 组票型`
  if (phaseCategory.value === 'night') return `${nightMatrixRows.value.length} 条行动`
  if (phaseCategory.value === 'speech') return `${speechTimelineRows.value.length} 条发言`
  return `${phaseSummaryCards.value.length} 项摘要`
})

const phaseEvidenceSummary = computed(() => {
  if (phaseCategory.value === 'vote') {
    const top = voteRankingRows.value[0]
    if (!top) return '暂无可统计票型'
    const alertText = voteAnomalyRows.value.length ? ` · ${voteAnomalyRows.value.length} 条提示` : ''
    return `最高票 ${top.label} · ${top.count} 票${alertText}`
  }
  if (phaseCategory.value === 'night') {
    const targets = new Set(nightMatrixRows.value.map((row) => row.target).filter((item) => item && item !== '无目标'))
    return `${nightMatrixRows.value.length} 次行动 · ${targets.size} 个目标 · ${props.nightResult ? '有结算' : '无结算'}`
  }
  if (phaseCategory.value === 'speech') {
    const speakers = new Set(speechTimelineRows.value.map((row) => String(row.actor || '')).filter(Boolean)).size
    const signals = speechTimelineRows.value.flatMap((row) => row.tags || []).length
    return `${speakers || speechTimelineRows.value.length} 名玩家 · ${signals} 个信号 · ${rawLogsForFocus.value.length} 条原始`
  }
  return `${rawLogsForFocus.value.length} 条日志 · ${focusedDecisionCount.value} 条结构化记录`
})

const selectedHistoryGameNumber = computed(() => {
  const gameId = props.selectedHistoryGame?.game_id
  if (!gameId) return null
  const index = props.gameHistory.findIndex((game) => game.game_id === gameId)
  return index >= 0 ? index + 1 : null
})

const selectedHistoryGameLabel = computed(() => {
  const number = selectedHistoryGameNumber.value
  return number ? `对局${number}` : '历史对局'
})

const selectedLogSource = computed(() =>
  props.selectedHistoryGame?.log_source || selectedGameConfig.value.log_source || 'normal'
)

const selectedGameModeLabel = computed(() => {
  const source = selectedLogSource.value
  if (source === 'benchmark') return '批量评测'
  if (source === 'evolution') return '自进化'
  return props.selectedHistoryGame?.mode === 'watch' ? '人机局' : '玩家局'
})

const selectedGameTimeValue = computed(() => {
  const game = props.selectedHistoryGame || {}
  const config = selectedGameConfig.value || {}
  return game.log_time || game.finished_at || game.started_at || config.log_time || config.finished_at || config.started_at || ''
})

const selectedGameDateLabel = computed(() => formatGameDate(selectedGameTimeValue.value, { fallback: '日期未知' }))

const selectedGameSubLabel = computed(() => {
  if (selectedLogSource.value === 'normal') return selectedGameDateLabel.value
  const phaseLabel = props.selectedHistoryGame?.source_phase_label || selectedGameConfig.value.source_phase_label
  return phaseLabel ? `${selectedGameDateLabel.value} · ${phaseLabel}` : selectedGameDateLabel.value
})

const selectedPhaseTitle = computed(() => {
  return props.selectedHistoryPage ? pageTitle(props.selectedHistoryPage) : '阶段详情'
})

const selectedPhaseKind = computed(() => {
  const phase = props.selectedHistoryPage?.phase
  return displayPhaseLabel(phase) || normalizeHistoryDisplayText(phaseName(phase)) || '阶段'
})

const selectedPhaseSummary = computed(() => {
  const phase = props.selectedHistoryPage?.phase
  if (phase === 'night') return '夜间行动、技能目标与结算结果'
  if (['speech', 'sheriff'].includes(phase)) return '玩家发言、公开表述与决策依据'
  if (['vote', 'exile_vote', 'pk_vote', 'sheriff_vote', 'sheriff_result'].includes(phase)) return '票型分布、投票理由与阶段结果'
  if (phase === 'result' || phase === 'finished') return '最终胜负、死亡记录与游戏结束事件'
  return '阶段事件、系统记录与关键上下文'
})

const archiveButtonText = computed(() => {
  if (props.archiveLoading) return '读取中'
  if (archiveLoaded.value) return '档案已载入'
  return selectedArchive.value?.error ? '重试档案' : '对局档案'
})
function asyncTabState({ loading = false, loaded = false, error = false, missing = false } = {}) {
  if (loading) return { state: 'loading', badge: '读取中' }
  if (error) return { state: 'error', badge: '错误' }
  if (missing) return { state: 'missing', badge: '缺失' }
  if (loaded) return { state: 'loaded', badge: '已载入' }
  return { state: 'idle', badge: '未载入' }
}
const reviewTabState = computed(() => asyncTabState({
  loading: props.reviewLoading,
  loaded: reviewLoaded.value,
  error: Boolean(selectedReview.value?.error),
  missing: selectedReview.value?.missing === true || selectedReview.value?.status === 'missing'
}))
const archiveTabState = computed(() => asyncTabState({
  loading: props.archiveLoading,
  loaded: archiveLoaded.value,
  error: Boolean(selectedArchive.value?.error),
  missing: selectedArchive.value?.missing === true || selectedArchive.value?.status === 'missing'
}))
const workspaceTabs = computed(() => [
  { key: 'phase', label: '阶段详情', badge: props.historyLogs.length ? String(props.historyLogs.length) : '', state: 'loaded' },
  { key: 'review', label: '复盘报告', ...reviewTabState.value },
  { key: 'archive', label: '对局档案', ...archiveTabState.value }
])

function normalizeWorkspaceTab(tab: any) {
  const text = String(tab || '').trim().toLowerCase()
  return WORKSPACE_TAB_KEYS.has(text) ? text : 'phase'
}

function setWorkspaceTab(tab: any, { emitUpdate = true, load = true }: { emitUpdate?: boolean, load?: boolean } = {}) {
  const next = normalizeWorkspaceTab(tab)
  if (workspaceTab.value !== next) workspaceTab.value = next
  if (emitUpdate && props.historyWorkspaceTab !== next) emit('update:historyWorkspaceTab', next)
  if (!load || !props.selectedHistoryGame?.game_id) return
  if (next === 'review' && !reviewLoaded.value && !props.reviewLoading) {
    props.loadReview?.(props.selectedHistoryGame.game_id)
  }
  if (next === 'archive' && !archiveLoaded.value && !props.archiveLoading) {
    props.loadArchive?.(props.selectedHistoryGame.game_id)
  }
}

watch(() => props.selectedHistoryGameId, () => {
  selectedAssessPlayerId.value = null
  rawLogFilter.value = 'all'
  expandedPhaseEvidenceKeys.value = new Set()
})

watch(() => props.historyWorkspaceTab, (tab) => {
  setWorkspaceTab(tab, { emitUpdate: false })
}, { immediate: true })

watch(() => props.selectedHistoryGame?.game_id, () => {
  setWorkspaceTab(props.historyWorkspaceTab, { emitUpdate: false })
})

watch(() => props.selectedHistoryPage?.key, () => {
  rawLogFilter.value = 'all'
})

function togglePhaseEvidence() {
  const key = phaseEvidenceKey.value
  if (!key) return
  const next = new Set(expandedPhaseEvidenceKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedPhaseEvidenceKeys.value = next
}

function phaseName(phase: any) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : (phase || '未知阶段')
}

function pageTitle(page: any) {
  return props.historyPageTitle ? props.historyPageTitle(page) : page.key
}

function logSpeaker(log: any) {
  return props.historyLogSpeaker ? props.historyLogSpeaker(log) : (log?.speaker || '系统')
}

function normalizeText(text: any) {
  const value = props.historyNormalizeText ? props.historyNormalizeText(text) : (text || '')
  return normalizeHistoryDisplayText(value) || '—'
}

function winnerLabel(winner: any) {
  return displayWinnerLabel(winner)
}

function formatGameDate(value: any, options: { fallback?: string } = {}) {
  if (!value) return options.fallback || '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return options.fallback || '时间未知'
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDiff = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86400000)
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (dayDiff === 0) return `今天 ${time}`
  if (dayDiff === 1) return `昨天 ${time}`
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

function roleLabel(role: any) {
  return displayRoleLabel(role)
}

function actionLabel(value: any) {
  const action = typeof value === 'object' && value !== null
    ? value.action || value.action_type || value.event_type || value.type || value.selected_action || value.phase
    : value
  return displayActionLabel(action) || normalizeHistoryDisplayText(action) || '行动'
}

function normalizePlayerId(value: any) {
  const raw = value && typeof value === 'object'
    ? value.id ?? value.player_id ?? value.actor_id ?? value.seat ?? value.target_id ?? value.value
    : value
  if (raw == null || raw === '') return null
  const text = String(raw).trim()
  if (!text || /^(none|null|无|无目标|no_target|skip|pass)$/i.test(text)) return null
  const match = text.match(/^#?(\d+)\s*号?(?:\b|\s|$)/)
  if (match) return Number(match[1])
  const num = Number(text)
  return Number.isFinite(num) ? num : text
}

function samePlayer(a: any, b: any) {
  const left = normalizePlayerId(a)
  const right = normalizePlayerId(b)
  return left != null && right != null && String(left) === String(right)
}

function rowActorId(row: any = {}) {
  return normalizePlayerId(
    row.actor_id
    ?? row.player_id
    ?? row.actor
    ?? row.player
    ?? row.speaker_id
    ?? row.speakerId
    ?? row.payload?.actor_id
    ?? row.payload?.player_id
  )
}

function rowTargetId(row: any = {}) {
  return normalizePlayerId(
    row.target_id
    ?? row.selected_target
    ?? row.target_player_id
    ?? row.target
    ?? row.payload?.target_id
    ?? row.payload?.selected_target
    ?? row.payload?.target
  )
}

function rowTargetIds(row: any = {}) {
  return [
    rowTargetId(row),
    row.target,
    row.targetName,
    row.target_name,
    row.selected_target_name
  ].map((item) => normalizePlayerId(item)).filter((item) => item != null)
}

function rowText(row: any = {}) {
  return normalizeHistoryDisplayText([
    row.message,
    row.public_summary,
    row.public_text,
    row.summary,
    row.reason,
    row.private_reasoning,
    row.targetName,
    row.actorName,
    row.speaker,
    row.target_name,
    row.actor_name
  ].filter(Boolean).join(' '))
}

function rowMentionsPlayer(row: any = {}, playerId: any) {
  const id = normalizePlayerId(playerId)
  if (id == null) return false
  const text = rowText(row)
  return text.includes(`${id}号`) || text.includes(`#${id}`) || text.includes(`玩家${id}`)
}

function rowMatchesFocusedPlayer(row: any = {}, options: RowFilterOptions = {}) {
  if (!hasPlayerFocus.value) return true
  const id = focusedPlayerId.value
  if (samePlayer(rowActorId(row), id)) return true
  if (options.includeTarget && rowTargetIds(row).some((targetId) => samePlayer(targetId, id))) return true
  if (Array.isArray(row.votes) && row.votes.some((vote) => rowMatchesFocusedPlayer(vote, options))) return true
  if (Array.isArray(row.voter_ids) && row.voter_ids.some((voterId) => samePlayer(voterId, id))) return true
  if (Array.isArray(row.voters) && row.voters.some((voter) => samePlayer(voter, id) || rowMentionsPlayer({ message: voter }, id))) return true
  if (options.includeText && rowMentionsPlayer(row, id)) return true
  return false
}

function rawLogKind(log: any = {}) {
  const type = String(log.event_type || log.type || log.action || log.action_type || log.kind || '').toLowerCase()
  const phase = String(log.phase || '').toLowerCase()
  const text = rowText(log).toLowerCase()
  if (/(error|failed|fail|timeout|exception|invalid|异常|错误|失败|超时)/.test(`${type} ${text}`)) return 'error'
  if (/(vote|exile|pk|sheriff_vote|投票|票|放逐|警长票)/.test(`${type} ${phase} ${text}`)) return 'vote'
  if (rowActorId(log) != null || rowTargetId(log) != null || /(kill|guard|seer|witch|poison|shoot|speech|speak|死亡|查验|守护|发言|击杀|开枪)/.test(`${type} ${text}`)) return 'action'
  return 'system'
}

function decisionKey(decision: any, index = 0) {
  if (!decision) return `empty-${index}`
  return [
    decision.id ?? decision.decision_id ?? decision.sequence ?? decision.index ?? index,
    decision.day ?? '',
    decision.phase ?? '',
    decision.action ?? decision.action_type ?? decision.type ?? '',
    rowActorId(decision) ?? decision.actorName ?? '',
    rowTargetId(decision) ?? decision.targetName ?? ''
  ].map((part) => String(part)).join('|')
}

function actorLabel(row: any = {}) {
  const name = row.actorName || row.actor_name || row.player_name || row.name || row.speaker
  if (name) return normalizeHistoryDisplayText(name)
  const id = rowActorId(row)
  return id == null ? '系统' : `${id}号`
}

function targetLabel(row: any = {}) {
  const named = row.targetName || row.target_name || row.selected_target_name || row.target
  if (named != null && named !== '') {
    const text = normalizeHistoryDisplayText(named)
    if (!/^(无目标|无|none|null|no_target|未选择|跳过|pass|skip)$/i.test(text)) return text
  }
  const id = rowTargetId(row)
  return id == null ? '' : `${id}号`
}

function decisionSummary(row: any = {}) {
  return normalizeText(row.public_summary || row.public_text || row.summary || row.reason || row.private_reasoning || row.message || '')
}

function confidencePercent(row: any = {}) {
  const value = Number(row.confidence)
  if (!Number.isFinite(value)) return null
  return Math.round(Math.max(0, Math.min(value > 1 ? value : value * 100, 100)))
}

function speechTags(row: any = {}) {
  const text = decisionSummary(row).toLowerCase()
  const tags: string[] = []
  const tests: Array<[string, RegExp]> = [
    ['跳身份', /(我是|跳|身份|预言家|女巫|猎人|守卫|seer|witch|hunter|guard)/],
    ['查验', /(查验|验了|金水|查杀|银水|checked|inspect)/],
    ['踩人', /(怀疑|偏狼|像狼|出|踩|投|wolf)/],
    ['保人', /(好人|偏好|可信|站边|保|villager|good)/],
    ['对跳', /(对跳|悍跳|不认|假预言家)/],
    ['划水', /(过|先过|没信息|不知道|暂无)/]
  ]
  tests.forEach(([label, pattern]) => {
    if (pattern.test(text)) tags.push(label)
  })
  return tags.slice(0, 4)
}

function voteCount(item: any = {}) {
  const count = Number(item.count)
  if (Number.isFinite(count) && count > 0) return count
  if (Array.isArray(item.votes)) return item.votes.length
  if (Array.isArray(item.voter_ids)) return item.voter_ids.length
  if (Array.isArray(item.voters)) return item.voters.length
  return 0
}

function voterLabels(item: any = {}) {
  if (Array.isArray(item.voters) && item.voters.length) return item.voters.map((value) => normalizeHistoryDisplayText(value)).filter(Boolean)
  if (Array.isArray(item.votes) && item.votes.length) return item.votes.map(actorLabel).filter(Boolean)
  if (Array.isArray(item.voter_ids) && item.voter_ids.length) return item.voter_ids.map((id) => `${id}号`)
  return []
}

function tallyVoteRows(votes: any[] = []) {
  const map = new Map()
  votes.forEach((vote) => {
    const target = targetLabel(vote) || '无目标'
    if (!map.has(target)) map.set(target, { target, targetName: target, count: 0, voters: [], votes: [] })
    const row = map.get(target)
    row.count += 1
    row.votes.push(vote)
    const actor = actorLabel(vote)
    if (actor && !row.voters.includes(actor)) row.voters.push(actor)
  })
  return [...map.values()].sort((a, b) => voteCount(b) - voteCount(a) || String(a.target).localeCompare(String(b.target)))
}

function rawLogPhaseName(log: any) {
  const phase = log?.phase || log?.event_type || log?.type || props.selectedHistoryPage?.phase
  return displayPhaseLabel(phase) || normalizeHistoryDisplayText(phaseName(phase))
}

function setupInitMessage(log: any) {
  return normalizeText(log?.message || '').replace(/^游戏初始化[：:]\s*/, '')
}

function rawLogDayLabel(log: any) {
  const day = log?.day || props.selectedHistoryPage?.day
  return day ? `第${day}天` : '对局'
}

function candidateLabel(item: any) {
  return `${item.seat}号${roleLabel(item.role)}`
}

function updatePage(key: any) {
  emit('update:selectedHistoryPageKey', key)
  emit('select-page', key)
}

function updateDecision(decision: any) {
  emit('update:selectedDecision', decision)
}

function updateDetailTab(tab: any) {
  emit('update:detailTab', tab)
}

function selectHistoryGameFromList(gameId) {
  setWorkspaceTab('phase')
  emit('select-history-game', gameId)
}

function loadSelectedReview() {
  props.loadReview?.(props.selectedHistoryGame?.game_id)
}

function loadSelectedFlowData() {
  return props.loadFlowData?.(props.selectedHistoryGame?.game_id, { clearNotice: true })
}

function loadSelectedArchive() {
  setWorkspaceTab('archive', { load: false })
  props.loadArchive?.(props.selectedHistoryGame?.game_id)
}

function loadMoreSelectedPhase() {
  return props.loadMoreHistoryPhaseDetail?.(
    props.selectedHistoryGame?.game_id || props.selectedHistoryGameId,
    props.selectedHistoryPage?.key || props.selectedHistoryPageKey
  )
}

function retrySelectedDetail() {
  if (detailRetryDisabled.value) return null
  if (workspaceTab.value === 'review') return loadSelectedReview()
  if (workspaceTab.value === 'archive') return loadSelectedArchive()
  return loadMoreSelectedPhase()
}

function selectWorkspaceTab(tab: any) {
  setWorkspaceTab(tab)
}

function selectAssessPlayer(player: any) {
  const nextId = player?.id ?? player?.seat ?? null
  selectedAssessPlayerId.value = samePlayer(selectedAssessPlayerId.value, nextId) ? null : nextId
  rawLogFilter.value = 'all'
}

function clearPlayerFocus() {
  selectedAssessPlayerId.value = null
  rawLogFilter.value = 'all'
}
</script>

<template>
  <section class="battle-log-page" aria-label="对战日志">
    <section class="battle-log-shell parchment-logbook">
      <HistoryGameList
        :games="gameHistoryForList"
        :selected-game-id="selectedHistoryGameId"
        :loading="historyLoading"
        :loading-more="historyLoadingMore"
        :has-more="historyHasMore"
        :source-filter="historySourceFilter"
        :pagination="historyPagination"
        :counts="historyCounts"
        :facets="historyFacets"
        :notice="historyNotice"
        @select-game="selectHistoryGameFromList"
        @replay-game="emit('replay-game', $event)"
        @delete-game="deleteHistoryGame?.($event)"
        @change-source="setHistorySourceFilter?.($event)"
        @change-page="goHistoryPage?.($event)"
        @load-more="loadMoreHistory?.()"
      />

      <main class="history-detail-panel">
        <ApiErrorPanel
          v-if="detailErrorNotice"
          class="detail-error-panel"
          :error="detailErrorNotice"
          title="历史记录读取失败"
          retry-label="重试读取"
          retry-busy-label="读取中"
          :retrying="detailRetrying"
          :retry-disabled="detailRetryDisabled"
          compact
          @retry="retrySelectedDetail"
        />
        <div
          v-else-if="detailInlineNotice"
          :class="['detail-notice', detailInlineNotice.type]"
          role="status"
          aria-live="polite"
        >
          <span>{{ detailInlineNotice.message }}</span>
        </div>

        <!-- ── Phase navigator + game config ── -->
        <div v-if="selectedHistoryGame" :class="['detail-topbar', 'workspace-' + workspaceTab]">
          <nav class="detail-workspace-tabs" aria-label="日志详情视图">
            <button
              v-for="item in workspaceTabs"
              :key="item.key"
              type="button"
              :class="{ active: workspaceTab === item.key }"
              @click="selectWorkspaceTab(item.key)"
            >
              <span>{{ item.label }}</span>
              <small
                v-if="item.badge"
                class="detail-workspace-badge"
                :data-state="item.state"
              >
                {{ item.badge }}
              </small>
            </button>
          </nav>
          <EvidenceContextBar v-if="workspaceTab === 'phase'" :game="selectedHistoryGame" />
          <PhaseTabs
            v-if="workspaceTab === 'phase'"
            :pages="historyPagesForTabs"
            :selected-page-key="selectedHistoryPage?.key || selectedHistoryPageKey"
            :page-title="pageTitle"
            @update:selectedPageKey="updatePage"
          />
        </div>

        <!-- ── Scrollable content ── -->
        <div v-if="selectedHistoryGame" :class="['detail-content', 'workspace-' + workspaceTab]">
          <div class="detail-main-column">
            <!-- Phase content -->
            <section v-if="workspaceTab === 'phase' && selectedHistoryPage" class="history-page-detail">
              <header class="phase-overview" :data-phase="phaseCategory">
                <div class="phase-overview-copy">
                  <small>{{ selectedPhaseKind }}</small>
                  <h3>{{ selectedPhaseTitle }}</h3>
                  <p>{{ phaseConclusion }}</p>
                  <button
                    v-if="hasPlayerFocus"
                    type="button"
                    class="phase-focus-clear"
                    @click="clearPlayerFocus"
                  >
                    {{ focusLabel }} · 清除聚焦
                  </button>
                </div>
                <div class="phase-overview-stats" aria-label="阶段摘要">
                  <span v-for="item in phaseSummaryCards" :key="item.label">
                    <small>{{ item.label }}</small>
                    <b>{{ item.value }}</b>
                  </span>
                </div>
              </header>

              <section :class="['phase-evidence-panel', { 'is-expanded': phaseEvidenceExpanded }]">
                <header class="phase-section-head phase-evidence-head">
                  <button
                    type="button"
                    class="phase-evidence-toggle"
                    :aria-expanded="phaseEvidenceExpandedAttr"
                    :aria-controls="phaseEvidenceBodyId"
                    @click="togglePhaseEvidence"
                  >
                    <span class="phase-evidence-heading">
                      <span class="phase-evidence-title">阶段摘要</span>
                      <small>{{ phaseEvidenceCountLabel }}</small>
                    </span>
                    <span class="phase-evidence-meta">
                      <span>{{ phaseEvidenceScope }}</span>
                      <i aria-hidden="true"></i>
                    </span>
                  </button>
                </header>

                <div v-if="!phaseEvidenceExpanded" class="phase-evidence-brief">
                  <span>{{ phaseEvidenceSummary }}</span>
                </div>

                <div
                  v-show="phaseEvidenceExpanded"
                  :id="phaseEvidenceBodyId"
                  class="phase-evidence-body"
                >
                  <div v-if="phaseCategory === 'vote'" class="phase-vote-layout">
                    <div v-if="voteRankingRows.length" class="phase-vote-rank">
                      <article
                        v-for="row in voteRankingRows"
                        :key="row.key"
                        :data-tone="row.tone"
                        class="phase-vote-row"
                      >
                        <div class="phase-vote-main">
                          <b>{{ row.label }}</b>
                          <span>{{ row.voters.length ? row.voters.join('、') : '暂无投票人记录' }}</span>
                        </div>
                        <div class="phase-vote-track">
                          <i :style="{ width: row.percent + '%' }"></i>
                        </div>
                        <strong>{{ row.count }}票</strong>
                      </article>
                    </div>
                    <div v-else class="phase-empty-state">暂无可统计票型</div>
                    <div v-if="voteAnomalyRows.length" class="phase-alert-list">
                      <span v-for="item in voteAnomalyRows" :key="item.key" :data-tone="item.tone">
                        {{ item.text }}
                      </span>
                    </div>
                  </div>

                  <div v-else-if="phaseCategory === 'night'" class="phase-night-matrix">
                    <div class="phase-matrix-head">
                      <span>行动者</span><span>动作</span><span>目标</span><span>结果</span><span>置信</span>
                    </div>
                    <article v-for="row in nightMatrixRows" :key="row.key" class="phase-matrix-row">
                      <b>{{ row.actor }}</b>
                      <span>{{ row.actionName }}</span>
                      <span>{{ row.target }}</span>
                      <p>{{ row.result }}</p>
                      <strong>{{ row.confidence == null ? '--' : row.confidence + '%' }}</strong>
                    </article>
                    <div v-if="!nightMatrixRows.length" class="phase-empty-state">暂无夜间行动记录</div>
                  </div>

                  <div v-else-if="phaseCategory === 'speech'" class="phase-speech-timeline">
                    <article v-for="row in speechTimelineRows" :key="row.key" class="phase-speech-row">
                      <div class="phase-speech-id">
                        <b>{{ row.actor }}</b>
                        <small>{{ row.role }}</small>
                      </div>
                      <p>{{ row.summary }}</p>
                      <div class="phase-speech-tags">
                        <span v-for="tag in row.tags" :key="row.key + '-' + tag">{{ tag }}</span>
                        <em v-if="row.confidence != null">{{ row.confidence }}%</em>
                      </div>
                    </article>
                    <div v-if="!speechTimelineRows.length" class="phase-empty-state">暂无发言决策记录</div>
                  </div>

                  <div v-else class="phase-generic-evidence">
                    <span v-for="item in phaseSummaryCards" :key="'generic-' + item.label">
                      <small>{{ item.label }}</small><b>{{ item.value }}</b>
                    </span>
                  </div>
                </div>
              </section>

              <section v-if="canShowPhaseDecisionPanel" class="phase-decision-panel">
                <header class="phase-section-head">
                  <h4>决策明细</h4>
                  <span>{{ phaseDecisionPanelMeta }}</span>
                </header>

                <NightSection
                  v-if="phaseCategory === 'night' && focusedNightActions.length"
                  :night-actions="focusedNightActions"
                  :night-result="nightResult"
                  :selected-decision="selectedDecision"
                  :detail-tab="detailTab"
                  :night-action-detail="nightActionDetail"
                  :role-icon-image="props.roleIconImage"
                  @update:selectedDecision="updateDecision"
                  @update:detailTab="updateDetailTab"
                />
                <SpeechSection
                  v-if="phaseCategory === 'speech' && focusedSpeechDecisions.length"
                  :decisions="focusedSpeechDecisions"
                  :selected-decision="selectedDecision"
                  :detail-tab="detailTab"
                  :role-icon-image="props.roleIconImage"
                  @update:selectedDecision="updateDecision"
                  @update:detailTab="updateDetailTab"
                />
                <VoteSection
                  v-if="phaseCategory === 'vote' && (focusedVoteDecisions.length || sheriffResult?.message)"
                  :decisions="focusedVoteDecisions"
                  :tally="focusedVoteTally"
                  :result-message="selectedHistoryPage.phase === 'sheriff_result' ? (sheriffResult?.message || '') : ''"
                  :selected-decision="selectedDecision"
                  :detail-tab="detailTab"
                  :role-icon-image="props.roleIconImage"
                  @update:selectedDecision="updateDecision"
                  @update:detailTab="updateDetailTab"
                />

                <section v-if="focusedLastWords.length" class="history-lastwords-section">
                  <div v-for="(word, index) in focusedLastWords" :key="'last-word-' + index" class="last-word-card">
                    <header>
                      <span class="last-word-actor">{{ word.actorName }}玩家</span>
                      <span class="last-word-role">{{ roleLabel(word.roleName) }}</span>
                      <span class="last-word-label">遗言</span>
                    </header>
                    <p class="last-word-message">{{ word.public_summary || word.reason }}</p>
                    <details class="last-word-decision">
                      <summary>决策过程</summary>
                      <small v-if="word.private_reasoning || word.reason">{{ word.private_reasoning || word.reason }}</small>
                      <small v-if="word.candidates?.length">
                        候选：{{ word.candidates.map(candidateLabel).join('、') }}
                      </small>
                    </details>
                  </div>
                </section>

                <div v-if="!phaseDetailCount" class="phase-empty-state phase-detail-empty">
                  当前筛选范围没有结构化决策，展开原始记录查看系统事件。
                </div>
              </section>

              <details v-if="canShowRawLogs" class="history-raw-section">
                <summary>
                  <span>原始记录</span>
                  <b>{{ filteredRawLogs.length }}</b>
                </summary>
                <nav v-if="rawLogFilters.length > 1" class="raw-log-filter-tabs" aria-label="原始记录筛选">
                  <button
                    v-for="item in rawLogFilters"
                    :key="item.key"
                    type="button"
                    :class="{ active: rawLogFilter === item.key }"
                    @click="rawLogFilter = item.key"
                  >
                    {{ item.label }}<small>{{ item.count }}</small>
                  </button>
                </nav>
                <div v-if="!filteredRawLogs.length" class="empty-log">暂无日志</div>
                <div v-else class="history-timeline">
                  <article
                    v-for="(log, index) in visibleRawLogs"
                    :key="'raw-log-' + (log.sequence || log.event_type || log.type || index)"
                    :class="[
                      'history-raw-log',
                      {
                        'setup-init-log': selectedHistoryPage?.phase === 'setup',
                        'judge-message-log': !log.role_assignments
                      }
                    ]"
                  >
                    <span class="timeline-rail" aria-hidden="true">
                      <img v-if="!log.role_assignments" src="/livehall-assets/props/optimized/judge-avatar-160.webp" alt="" />
                      <i v-else></i>
                    </span>
                    <div class="timeline-card">
                      <template v-if="selectedHistoryPage?.phase === 'setup'">
                        <p><b>游戏初始化：</b>{{ setupInitMessage(log) }}</p>
                      </template>
                      <template v-else-if="log.role_assignments">
                        <header>
                          <span>{{ rawLogDayLabel(log) }} · {{ rawLogPhaseName(log) }}</span>
                          <em>角色分配</em>
                        </header>
                        <p class="role-assignment-title">角色分配如下</p>
                        <div class="role-assignment-grid">
                          <div v-for="item in log.role_assignments" :key="item.seat" class="role-assignment-cell">
                            <span class="ra-seat">{{ item.seat }}号</span>
                            <span class="ra-role">{{ roleLabel(item.role) }}</span>
                          </div>
                        </div>
                      </template>
                      <template v-else-if="selectedHistoryPage?.phase !== 'setup'">
                        <p>{{ normalizeText(log.message || '') }}</p>
                      </template>
                    </div>
                  </article>
                  <div v-if="filteredRawLogs.length > visibleRawLogs.length" class="history-raw-more">
                    还有 {{ filteredRawLogs.length - visibleRawLogs.length }} 条日志未显示
                  </div>
                </div>
              </details>

              <div v-if="phaseHasMore" class="phase-load-more-strip">
                <span>{{ phaseMoreMeta || '还有阶段记录未加载' }}</span>
                <button
                  type="button"
                  :disabled="selectedPhaseLoading"
                  @click="loadMoreSelectedPhase"
                >
                  {{ selectedPhaseLoading ? '加载中' : '加载更多阶段记录' }}
                </button>
              </div>
            </section>

            <section v-else-if="workspaceTab === 'review'" class="history-page-detail">
              <ReviewReportPanel
                :report="reviewByGameId[selectedHistoryGame.game_id]"
                :game="selectedHistoryGame"
                :flow-data="selectedFlowData"
                :flow-loading="selectedFlowLoading"
                :load-flow-data="loadSelectedFlowData"
                :format-json="formatJson"
              />
            </section>

            <section v-else-if="workspaceTab === 'archive'" class="history-page-detail archive-workbench-detail">
              <GameArchivePanel
                v-if="archiveByGameId[selectedHistoryGame.game_id]"
                :archive="archiveByGameId[selectedHistoryGame.game_id]"
                :game="selectedHistoryGame"
                :format-json="formatJson"
              />
              <div v-else class="document-empty">
                <strong>对局档案尚未载入</strong>
                <span>读取后会展示决策来源、错误回退和智能体档案字段。</span>
                <button type="button" :disabled="archiveLoading" @click="loadSelectedArchive">
                  {{ archiveLoading ? '读取中' : '读取对局档案' }}
                </button>
              </div>
            </section>
          </div>

          <aside v-if="workspaceTab === 'phase'" class="detail-side-column" aria-label="对局上下文">
            <section class="history-side-card history-side-card--context has-assess">
              <div class="history-side-card--seats">
                <header class="history-side-card-header">
                  <span>玩家席位</span>
                </header>
                <SeatLedger
                  :players="selectedHistoryGame.players || []"
                  :alive-map="playerAliveAtPage"
                  :sheriff-id="selectedHistoryGame.sheriff_id"
                  :selected-page="selectedHistoryPage"
                  :role-icon-image="props.roleIconImage"
                  selectable
                  :selected-player-id="selectedAssessPlayerId"
                  @select-player="selectAssessPlayer"
                />
              </div>

              <div class="history-side-card--assess">
                <MultiAssess
                  v-if="playerAssessmentScores.length"
                  :scores="activeAssessScoresForPanel"
                  :dimension="assessDimension"
                  :role-icon-image="props.roleIconImage"
                  :selected-player-id="activeAssessPlayerId"
                  compact
                  @update:dimension="emit('update:assessDimension', $event)"
                  @select-player="selectAssessPlayer"
                />
                <div v-else class="history-assess-empty">
                  <header class="history-side-card-header">
                    <span>多维测评</span>
                  </header>
                  <div class="history-assess-empty-body">
                    <strong>暂无测评数据</strong>
                    <button type="button" :disabled="reviewLoading" @click="loadSelectedReview">
                      {{ reviewLoading ? '读取中' : (selectedReview?.error ? '重试报告' : '读取复盘报告') }}
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </aside>
        </div>

        <p v-if="!selectedHistoryGame && !historyLoading" class="empty-log">选择一局历史对局查看详情</p>
      </main>
    </section>

  </section>
</template>

<style scoped>
/* ──────────────────────────────────────────────
   Design tokens
   ────────────────────────────────────────────── */
.battle-log-page {
  --log-bg: #f8f0e0;
  --log-surface: rgba(255, 252, 245, 0.7);
  --log-border: rgba(139, 94, 52, 0.15);
  --log-text: #3a2a18;
  --log-text-secondary: #8b6b4a;
  --log-accent: #8b5e34;
  --log-accent-strong: #5a3319;
  --log-input-bg: rgba(255, 255, 250, 0.8);
  --log-input-border: rgba(139, 94, 52, 0.2);
  --log-hover: rgba(139, 94, 52, 0.06);
  --log-active-bg: rgba(139, 94, 52, 0.1);
  --status-danger: #993026;
  --text-main: var(--log-text);
  --text-muted: var(--log-text-secondary);
}

/* ── Analysis command bar ── */
.detail-analysis-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(420px, 0.9fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin: 0;
  padding: 18px 18px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(58, 42, 24, 0.96), rgba(90, 51, 25, 0.9)),
    repeating-linear-gradient(90deg, rgba(232, 196, 132, 0.08) 0 1px, transparent 1px 18px);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.1);
  overflow: hidden;
}

.detail-analysis-title {
  display: flex;
  align-items: center;
  min-width: 0;
}

.detail-title-main {
  display: grid;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
}

.detail-title-row {
  display: inline-grid;
  grid-template-columns: minmax(0, auto) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}

.detail-analysis-title h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #fff4d9;
  font-size: 25px;
  font-weight: 950;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-game-id {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: rgba(255, 244, 217, 0.58);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-analysis-title .mode-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  align-self: center;
  width: max-content;
  min-width: 58px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(232, 196, 132, 0.32);
  border-radius: 6px;
  color: #ffd96a;
  background: rgba(242, 202, 80, 0.13);
  font-size: 12px;
  font-weight: 900;
  line-height: 1;
  white-space: nowrap;
}

.detail-analysis-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(68px, 1fr));
  gap: 8px;
  min-width: 0;
}

.detail-analysis-metrics span {
  display: grid;
  align-content: center;
  gap: 5px;
  height: 48px;
  min-width: 0;
  padding: 0 11px;
  border: 1px solid rgba(232, 196, 132, 0.18);
  border-radius: 7px;
  background: rgba(255, 246, 218, 0.08);
}

.detail-analysis-metrics small {
  color: rgba(232, 210, 170, 0.68);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.detail-analysis-metrics b {
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 15px;
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-analysis-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  min-width: max-content;
}

.detail-analysis-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 92px;
  height: 42px;
  padding: 0 15px;
  border: 1px solid rgba(232, 196, 132, 0.25);
  border-radius: 7px;
  color: #2d1e10;
  background: #e8c484;
  box-shadow: 0 3px 10px rgba(18, 10, 5, 0.18);
  font-size: 13px;
  font-weight: 950;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
  white-space: nowrap;
}

.detail-analysis-actions button:nth-child(2) {
  background: #fff4d9;
}

.detail-analysis-actions button.active {
  border-color: rgba(255, 244, 214, 0.68);
  background: #fff4d9;
  box-shadow: 0 0 0 2px rgba(232, 196, 132, 0.16), 0 5px 14px rgba(18, 10, 5, 0.22);
}

.detail-analysis-actions button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(18, 10, 5, 0.22);
}

.detail-analysis-actions button:disabled {
  cursor: default;
  opacity: 0.48;
  transform: none;
  box-shadow: none;
}

/* ── Detail top bar ── */
.detail-topbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    "workspace"
    "context"
    "phases";
  align-items: center;
  gap: 10px 14px;
  margin: 0;
  padding: 10px 16px 11px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.4);
  flex-shrink: 0;
  overflow: hidden;
}

.detail-workspace-tabs {
  grid-area: workspace;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 0;
  scrollbar-width: none;
}

.detail-workspace-tabs::-webkit-scrollbar {
  display: none;
}

.detail-workspace-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  flex: 0 0 auto;
  padding: 0 12px;
  border: 1px solid var(--log-input-border);
  border-radius: 7px;
  color: var(--log-accent-strong);
  background: rgba(255, 252, 245, 0.62);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.detail-workspace-tabs button.active {
  border-color: var(--log-accent-strong);
  color: #fff7dc;
  background: var(--log-accent-strong);
}

.detail-workspace-tabs small {
  display: inline-grid;
  max-width: 68px;
  min-width: 20px;
  height: 18px;
  place-items: center;
  padding: 0 6px;
  border-radius: 999px;
  color: inherit;
  background: rgba(255, 255, 255, 0.18);
  font-size: 10px;
  font-weight: 950;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-workspace-badge[data-state="idle"] {
  color: rgba(74, 37, 15, 0.72);
  background: rgba(74, 37, 15, 0.08);
}

.detail-workspace-badge[data-state="loading"] {
  color: #6a461b;
  background: rgba(212, 158, 56, 0.18);
}

.detail-workspace-badge[data-state="loaded"] {
  color: #335d35;
  background: rgba(80, 139, 73, 0.16);
}

.detail-workspace-badge[data-state="error"],
.detail-workspace-badge[data-state="missing"] {
  color: #8a2c21;
  background: rgba(161, 57, 42, 0.14);
}

.detail-workspace-tabs button.active .detail-workspace-badge {
  color: #fff7dc;
  background: rgba(255, 255, 255, 0.2);
}

.detail-topbar :deep(.history-phase-tabs) {
  grid-area: phases;
  min-width: 0;
  max-width: 100%;
  border-top: none;
  border-bottom: none;
  padding: 0;
  height: 54px;
  min-height: 54px;
  max-height: 54px;
}

.detail-actions {
  grid-area: actions;
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.detail-actions button {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--log-input-border);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.6);
  color: var(--log-accent-strong);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.detail-actions button:hover:not(:disabled) {
  background: var(--log-accent-strong);
  color: #fff;
  border-color: var(--log-accent-strong);
}

.detail-actions button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ── Detail content ── */
.detail-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 320px);
  gap: 14px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.24);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
}

.detail-content.workspace-review,
.detail-content.workspace-archive {
  grid-template-columns: minmax(0, 1fr);
  align-items: stretch;
  overflow: hidden;
}

.detail-content.workspace-review .detail-main-column,
.detail-content.workspace-archive .detail-main-column {
  display: block;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.detail-main-column,
.detail-side-column {
  min-width: 0;
  min-height: 0;
}

.detail-main-column {
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.detail-side-column {
  height: 100%;
  max-height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.detail-main-column::-webkit-scrollbar {
  display: block;
  width: 6px;
}

.detail-main-column::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.34);
}

.detail-side-column::-webkit-scrollbar {
  display: block;
  width: 7px;
}

.detail-side-column::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.34);
}

.detail-main-column {
  display: grid;
  align-content: start;
  grid-auto-rows: max-content;
  gap: 12px;
}

.detail-side-column {
  display: grid;
  grid-template-rows: minmax(0, auto);
  align-content: start;
  gap: 0;
  padding: 2px 2px 12px;
  overflow-x: hidden;
  overflow-y: auto;
}

/* ── Content section cards ── */
.detail-main-column > .history-page-detail,
.history-side-card {
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: var(--log-surface);
  box-shadow: none;
  overflow: hidden;
}

.history-side-card {
  display: grid;
  align-self: start;
  min-height: 0;
  margin-bottom: 10px;
}

.history-side-card--context {
  align-self: start;
  grid-template-rows: auto auto;
  align-content: start;
  border-radius: 8px;
  overflow: hidden;
}

.history-side-card--context:not(.has-assess) {
  grid-template-rows: auto;
}

.history-side-card--seats {
  display: grid;
  min-height: 0;
  max-height: none;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 252, 245, 0.64);
}

.history-side-card--context:not(.has-assess) .history-side-card--seats {
  border-radius: 8px;
  overflow: hidden;
}

.history-side-card--seats .history-side-card-header {
  min-height: 34px;
  padding: 7px 10px;
}

.history-side-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--log-border);
}

.history-side-card-header span {
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
}

.history-side-card-header small {
  margin-left: auto;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.detail-main-column > .history-page-detail {
  align-self: start;
  flex: none;
  padding: 0;
}

.history-document-panel {
  height: 100%;
  min-height: 0;
  max-height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.history-document-panel::-webkit-scrollbar {
  width: 7px;
}

.history-document-panel::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.34);
}

.history-document-panel :deep(.archive-review-panel) {
  margin-top: 0;
}

.document-empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 260px;
  border: 1px dashed rgba(139, 94, 52, 0.28);
  border-radius: 10px;
  background: rgba(255, 252, 245, 0.48);
  text-align: center;
}

.document-empty strong {
  color: var(--log-text);
  font-size: 18px;
  font-weight: 950;
}

.document-empty span {
  max-width: 360px;
  color: var(--log-text-secondary);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.5;
}

.document-empty button {
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--log-accent-strong);
  border-radius: 7px;
  color: #fff7dc;
  background: var(--log-accent-strong);
  font-size: 13px;
  font-weight: 900;
}

.detail-main-column .history-raw-section {
  padding: 0;
}

.history-side-card :deep(.history-seat-ledger) {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  padding: 8px 8px 10px;
  background: transparent;
}

.history-side-card :deep(.history-seat-ledger article) {
  gap: 3px;
  min-height: 31px;
  padding: 5px 7px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.68);
  box-shadow: none;
}

.history-side-card :deep(.history-seat-ledger img) {
  width: 16px;
  height: 16px;
}

.history-side-card--assess {
  min-height: 410px;
  border-radius: 8px;
  overflow: hidden;
}

.history-side-card--seats + .history-side-card--assess {
  border-top: 1px solid var(--log-border);
}

.history-side-card--assess :deep(.multi-assess-module) {
  display: grid;
  grid-template-rows: auto;
  min-height: 0;
  height: 100%;
  border: none;
  border-radius: 8px;
  background: transparent;
  box-shadow: none;
  overflow: hidden;
}

.history-assess-empty {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 100%;
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.48);
  overflow: hidden;
}

.history-assess-empty-body {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 9px;
  min-height: 280px;
  padding: 20px 18px;
  text-align: center;
}

.history-assess-empty-body strong {
  color: var(--log-text);
  font-size: 16px;
  font-weight: 950;
}

.history-assess-empty-body p {
  max-width: 220px;
  margin: 0;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.55;
}

.history-assess-empty-body button {
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--log-accent-strong);
  border-radius: 7px;
  color: #fff7dc;
  background: var(--log-accent-strong);
  font-size: 13px;
  font-weight: 900;
  cursor: pointer;
}

.history-assess-empty-body button:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.history-side-card--assess :deep(.multi-assess-header) {
  min-height: 38px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--log-border);
}

.history-side-card--assess :deep(.multi-assess-body) {
  display: grid;
  gap: 0;
  min-width: 0;
  min-height: 0;
  max-width: 100%;
  overflow: hidden;
  scrollbar-width: none;
}

.history-side-card--assess :deep(.multi-assess-body::-webkit-scrollbar) {
  display: none;
}

.history-side-card--assess :deep(.multi-assess-body::-webkit-scrollbar-thumb) {
  background: transparent;
}

.history-side-card--assess :deep(.ma-compact-body) {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  align-content: start;
  gap: 0;
  min-height: 100%;
  padding: 0;
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.2);
  overflow: hidden;
}

.history-side-card--assess :deep(.ma-compact-section) {
  display: grid;
  gap: 0;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  overflow: hidden;
}

.history-side-card--assess :deep(.ma-compact-section + .ma-compact-section) {
  border-top: 1px solid var(--log-border);
}

.history-side-card--assess :deep(.ma-compact-section-title) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  min-height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid var(--log-border);
}

.history-side-card--assess :deep(.ma-compact-section-title span) {
  color: var(--log-text);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.1;
}

.history-side-card--assess :deep(.ma-compact-section-title small) {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 800;
  line-height: 1.1;
}

.history-side-card--assess :deep(.ma-rank-list) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 8px;
}

.history-side-card--assess :deep(.ma-rank-row) {
  display: grid;
  grid-template-columns: 16px 18px minmax(0, 1fr) 26px;
  grid-template-rows: auto 3px;
  align-items: center;
  gap: 3px 4px;
  min-width: 0;
  min-height: 34px;
  padding: 5px 7px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  color: inherit;
  background: rgba(255, 252, 245, 0.58);
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.history-side-card--assess :deep(.ma-rank-row:hover),
.history-side-card--assess :deep(.ma-rank-row.active) {
  background: rgba(255, 236, 186, 0.62);
}

.history-side-card--assess :deep(.ma-rank-index) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  color: #fff7dc;
  background: rgba(91, 47, 18, 0.76);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.history-side-card--assess :deep(.ma-rank-avatar) {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--log-input-border);
}

.history-side-card--assess :deep(.ma-rank-player) {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.history-side-card--assess :deep(.ma-rank-player b) {
  color: var(--log-text);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
  white-space: nowrap;
}

.history-side-card--assess :deep(.ma-rank-player small) {
  overflow: hidden;
  color: var(--log-text-secondary);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-side-card--assess :deep(.ma-rank-score) {
  color: var(--log-accent-strong);
  font-size: 11px;
  font-weight: 950;
  line-height: 1;
  text-align: right;
}

.history-side-card--assess :deep(.ma-rank-bar) {
  grid-column: 2 / 5;
  display: block;
  min-width: 0;
  height: 3px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(91, 47, 18, 0.08);
}

.history-side-card--assess :deep(.ma-rank-bar i) {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2f7d6b, #d5a93b);
}

.history-side-card--assess :deep(.ma-compact-profile) {
  grid-template-columns: 178px minmax(0, 1fr);
  align-items: start;
  column-gap: 8px;
  min-height: 286px;
  padding: 0 12px 18px;
  border-radius: 8px;
  overflow: hidden;
}

.history-side-card--assess :deep(.ma-compact-profile .ma-profile-head) {
  grid-column: 1 / -1;
}

.history-side-card--assess :deep(.ma-profile-head) {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-height: 46px;
  min-width: 0;
  margin: 0 -12px 8px;
  padding: 0 12px;
  border-bottom: 1px solid var(--log-border);
}

.history-side-card--assess :deep(.ma-profile-avatar) {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--log-input-border);
}

.history-side-card--assess :deep(.ma-profile-meta) {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.history-side-card--assess :deep(.ma-profile-meta b) {
  overflow: hidden;
  color: var(--log-text);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-side-card--assess :deep(.ma-profile-meta small) {
  overflow: hidden;
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 700;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-side-card--assess :deep(.ma-profile-rank) {
  padding: 4px 6px;
  border-radius: 999px;
  color: #2f5f54;
  background: rgba(47, 125, 107, 0.12);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
  white-space: nowrap;
}

.history-side-card--assess :deep(.ma-radar-svg--compact) {
  width: 162px;
  height: auto;
  aspect-ratio: 1;
  justify-self: center;
  align-self: start;
  margin-top: 10px;
  overflow: visible;
  transform: none;
}

.history-side-card--assess :deep(.ma-radar-svg--compact .ma-radar-label) {
  fill: var(--log-text);
  font-size: 18px;
  font-weight: 900;
}

.history-side-card--assess :deep(.ma-compact-metrics) {
  display: grid;
  grid-template-columns: 1fr;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  border: 0;
  border-radius: 8px;
  background: transparent;
}

.history-side-card--assess :deep(.ma-compact-metrics span) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  min-height: 21px;
  padding: 4px 7px;
  border: 1px solid rgba(139, 94, 52, 0.1);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.62);
}

.history-side-card--assess :deep(.ma-compact-metrics small) {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--log-text-secondary);
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.history-side-card--assess :deep(.ma-compact-metrics b) {
  flex: 0 0 auto;
  color: var(--log-text);
  font-size: 12px;
  font-weight: 950;
  line-height: 1;
}

/* ──────────────────────────────────────────────
   Page shell — let global CSS handle layout
   ────────────────────────────────────────────── */
.battle-log-page {
  color: var(--log-text);
  font-family: 'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* ──────────────────────────────────────────────
   Return-to-match button
   ────────────────────────────────────────────── */
.return-match-button {
  position: absolute;
  top: 18px;
  right: 22px;
  z-index: 20;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 14px 0 16px;
  border: 1px solid var(--log-input-border);
  border-radius: 6px;
  color: var(--log-text);
  background: var(--log-surface);
  box-shadow:
    0 2px 8px rgba(91, 47, 18, 0.1),
    inset 0 1px 0 rgba(255, 246, 218, 0.72);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
  transition: background 0.2s ease, box-shadow 0.2s ease, transform 0.15s ease;
}

.return-match-button:hover {
  color: var(--log-accent-strong);
  background: rgba(255, 226, 157, 0.78);
  box-shadow: 0 4px 12px rgba(91, 47, 18, 0.15);
  transform: translateY(-1px);
}

.return-match-button i {
  color: var(--log-accent);
  font-style: normal;
  font-size: 12px;
  transform: translateY(1px);
}

/* ──────────────────────────────────────────────
   Game list sidebar
   ────────────────────────────────────────────── */
.battle-log-shell :deep(.history-games-panel) {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 0 14px 0 0;
  border-right: 1px solid var(--log-border);
  background: transparent;
  border-radius: 8px;
  box-shadow: none;
}

.battle-log-shell :deep(.history-games-panel header) {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--log-border);
}

.battle-log-shell :deep(.history-games-panel header span) {
  color: var(--log-text);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.02em;
  text-shadow: 0 1px 0 rgba(255, 237, 184, 0.5);
}

.battle-log-shell :deep(.history-games-panel header strong) {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  padding: 0 7px;
  border-radius: 11px;
  background: var(--log-active-bg);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 800;
}

.battle-log-shell :deep(.history-source-tabs) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--log-border);
}

.battle-log-shell :deep(.history-source-tabs button) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  height: 30px;
  padding: 0 8px;
  border: 1px solid rgba(139, 94, 52, 0.14);
  border-radius: 7px;
  color: var(--log-accent-strong);
  background: rgba(255, 252, 245, 0.45);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.battle-log-shell :deep(.history-source-tabs button:hover) {
  border-color: rgba(139, 94, 52, 0.24);
  background: var(--log-hover);
}

.battle-log-shell :deep(.history-source-tabs button.active) {
  border-color: rgba(90, 51, 25, 0.38);
  background: rgba(255, 226, 157, 0.34);
  box-shadow: inset 0 0 0 1px rgba(255, 246, 218, 0.62);
}

.battle-log-shell :deep(.history-source-tabs button span) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-source-tabs button small) {
  display: inline-grid;
  min-width: 20px;
  height: 18px;
  place-items: center;
  padding: 0 5px;
  border-radius: 9px;
  color: var(--log-accent);
  background: rgba(91, 47, 18, 0.08);
  font-size: 10px;
  font-weight: 950;
}

.battle-log-shell :deep(.history-source-tabs button.active small) {
  color: #fff7dc;
  background: var(--log-accent-strong);
}

.battle-log-shell :deep(.history-list-more) {
  display: grid;
  justify-items: center;
  gap: 7px;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.detail-topbar :deep(.evidence-context-bar) {
  grid-area: context;
}

.battle-log-shell :deep(.history-pagination) {
  display: grid;
  gap: 7px;
  padding: 9px 10px 10px;
  border-top: 1px solid var(--log-border);
  background: rgba(255, 248, 226, 0.32);
}

.battle-log-shell :deep(.history-page-meta) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 850;
}

.battle-log-shell :deep(.history-page-meta small) {
  color: rgba(74, 37, 15, 0.58);
  font-size: 10px;
  font-weight: 900;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-page-controls) {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(24px, max-content);
  justify-content: center;
  gap: 5px;
}

.battle-log-shell :deep(.history-page-step),
.battle-log-shell :deep(.history-page-number) {
  display: inline-grid;
  min-width: 24px;
  height: 25px;
  place-items: center;
  padding: 0 7px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 11px;
  font-weight: 950;
}

.battle-log-shell :deep(.history-page-step:hover:not(:disabled)),
.battle-log-shell :deep(.history-page-number:hover:not(:disabled)) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.battle-log-shell :deep(.history-page-number.active) {
  color: #fff7dc;
  border-color: rgba(90, 51, 25, 0.46);
  background: #70401e;
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.22);
}

.battle-log-shell :deep(.history-page-step:disabled),
.battle-log-shell :deep(.history-page-number:disabled) {
  cursor: not-allowed;
  opacity: 0.52;
}

.battle-log-shell :deep(.history-load-more) {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--log-input-border);
  border-radius: 6px;
  color: var(--log-accent-strong);
  background: rgba(255, 252, 245, 0.82);
  font-size: 11px;
  font-weight: 850;
}

.battle-log-shell :deep(.history-load-more:hover:not(:disabled)) {
  border-color: rgba(139, 94, 52, 0.32);
  background: rgba(255, 252, 245, 0.96);
}

.battle-log-shell :deep(.history-load-more:disabled) {
  cursor: not-allowed;
  opacity: 0.55;
}

.battle-log-shell :deep(.history-games-list) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* ──────────────────────────────────────────────
   Game items
   ────────────────────────────────────────────── */
.battle-log-shell :deep(.history-game-item) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin: 0 8px 8px;
  padding: 8px 9px 8px 11px;
  border: 1px solid transparent;
  border-left: 3px solid transparent;
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.32);
  transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  cursor: default;
}

.battle-log-shell :deep(.history-game-item:hover) {
  background: var(--log-hover);
  border-color: rgba(139, 94, 52, 0.16);
}

.battle-log-shell :deep(.history-game-item.active) {
  background: rgba(255, 226, 157, 0.28);
  border-color: rgba(139, 94, 52, 0.18);
  border-left-color: var(--log-accent);
  box-shadow: 0 2px 10px rgba(91, 47, 18, 0.08);
}

.battle-log-shell :deep(.history-game-select) {
  display: grid;
  gap: 5px;
  width: 100%;
  min-width: 0;
  text-align: left;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
}

.battle-log-shell :deep(.history-game-main) {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.battle-log-shell :deep(.history-game-title) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.battle-log-shell :deep(.history-game-title b) {
  color: var(--log-text);
  font-size: 15px;
  font-weight: 950;
  line-height: 1.05;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-game-subline) {
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.battle-log-shell :deep(.history-game-subline > span) {
  overflow: hidden;
  color: var(--log-accent-strong);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-game-subline > small) {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: rgba(139, 107, 74, 0.78);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-game-select small) {
  color: var(--log-text-secondary);
  font-size: 12px;
}

.battle-log-shell :deep(.history-game-meta) {
  display: flex;
  gap: 6px;
  min-width: 0;
  height: 20px;
  overflow: hidden;
}

.battle-log-shell :deep(.history-game-meta small) {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  height: 20px;
  padding: 0 6px;
  border: 1px solid rgba(139, 94, 52, 0.1);
  border-radius: 5px;
  background: rgba(255, 252, 245, 0.5);
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 800;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-game-meta .history-game-date) {
  flex: 0 0 auto;
  color: var(--log-accent-strong);
}

.battle-log-shell :deep(.history-game-meta small:last-child) {
  flex: 0 0 auto;
  min-width: 42px;
  text-align: center;
}

.battle-log-shell :deep(.history-game-meta small:not(.history-game-date):not(:last-child)) {
  flex: 1 1 auto;
}

.battle-log-shell :deep(.history-mode-tag),
.battle-log-shell :deep(.history-source-tag) {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

.battle-log-shell :deep(.history-source-tag.benchmark) {
  background: rgba(15, 107, 114, 0.12);
  color: #0f6b72;
}

.battle-log-shell :deep(.history-source-tag.evolution) {
  background: rgba(124, 82, 33, 0.14);
  color: #7c5221;
}

.battle-log-shell :deep(.history-mode-tag.watch) {
  background: rgba(192, 57, 43, 0.1);
  color: #c0392b;
}

.battle-log-shell :deep(.history-mode-tag.play) {
  background: rgba(39, 174, 96, 0.1);
  color: #27ae60;
}

.battle-log-shell :deep(.history-game-replay) {
  display: inline-grid;
  width: 30px;
  height: 30px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--log-input-border);
  border-radius: 7px;
  color: rgba(90, 51, 25, 0.72);
  background: rgba(255, 252, 245, 0.5);
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
  cursor: pointer;
  transition: all 0.18s ease;
  flex-shrink: 0;
}

.battle-log-shell :deep(.history-game-replay:hover) {
  background: var(--log-active-bg);
  border-color: var(--log-accent);
  color: var(--log-accent-strong);
}

.battle-log-shell :deep(.history-list-more) {
  padding: 10px 16px 14px;
  border-bottom: 1px solid var(--log-border);
  text-align: center;
}

/* ──────────────────────────────────────────────
   Detail panel (right side)
   ────────────────────────────────────────────── */
.history-detail-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
  min-height: 0;
  padding: 0 0 24px;
  overflow: hidden;
  overflow-x: hidden;
  scrollbar-width: none;
}

.history-detail-panel::-webkit-scrollbar {
  display: none;
}

.detail-notice {
  display: flex;
  align-items: center;
  min-height: 32px;
  margin: 0 0 10px;
  padding: 7px 10px;
  border: 1px solid rgba(93, 48, 17, 0.2);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.54);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.72);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.35;
}

.detail-notice span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.detail-notice.success {
  border-color: rgba(46, 116, 61, 0.24);
  color: #2f6b3d;
  background: rgba(215, 232, 194, 0.62);
}

.detail-notice.warning {
  border-color: rgba(151, 95, 18, 0.28);
  color: #76510e;
  background: rgba(248, 223, 157, 0.58);
}

.detail-notice.error {
  border-color: rgba(154, 45, 36, 0.3);
  color: #993026;
  background: rgba(248, 205, 181, 0.6);
}

.detail-error-panel {
  margin: 0 0 10px;
}

/* ──────────────────────────────────────────────
   Detail header
   ────────────────────────────────────────────── */
.history-detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 14px 0 12px;
  border-bottom: 1px solid var(--log-border);
}

.history-detail-header span {
  position: relative;
  display: inline-flex;
  align-items: center;
  color: var(--log-text);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.02em;
  line-height: 1;
  text-shadow: 0 1px 0 rgba(255, 237, 184, 0.5);
}

/* ──────────────────────────────────────────────
   Detail action buttons (复盘报告 / 对局档案)
   ────────────────────────────────────────────── */
.history-detail-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  margin-left: auto;
}

.history-detail-actions button {
  min-height: 32px;
  padding: 0 14px;
  border: 1px solid var(--log-input-border);
  border-radius: 6px;
  background: var(--log-surface);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.06);
}

.history-detail-actions button:hover:not(:disabled) {
  background: var(--log-active-bg);
  border-color: var(--log-accent);
  box-shadow: 0 2px 6px rgba(91, 47, 18, 0.1);
}

.history-detail-actions button:disabled {
  cursor: default;
  opacity: 0.5;
}

/* ──────────────────────────────────────────────
   Config strip
   ────────────────────────────────────────────── */
.history-config-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 8px;
  padding: 12px 0;
  margin-top: 4px;
  border-bottom: 1px solid var(--log-border);
}

.history-config-strip span {
  display: grid;
  min-width: 0;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  background: var(--log-surface);
  transition: border-color 0.15s ease;
}

.history-config-strip span:hover {
  border-color: var(--log-accent);
}

.history-config-strip small {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.history-config-strip b {
  min-width: 0;
  overflow: hidden;
  color: var(--log-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ──────────────────────────────────────────────
   Seat ledger
   ────────────────────────────────────────────── */
.battle-log-shell :deep(.history-seat-ledger) {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 18px;
}

.battle-log-shell :deep(.history-seat-ledger article) {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 14px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: var(--log-surface);
  transition: background 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  overflow: hidden;
}

.battle-log-shell :deep(.history-seat-ledger article:hover) {
  border-color: rgba(139, 94, 52, 0.25);
  box-shadow: 0 2px 6px rgba(91, 47, 18, 0.08);
}

.battle-log-shell :deep(.history-seat-ledger article.dead) {
  border-left: 3px solid #c0392b;
  background: rgba(192, 57, 43, 0.03);
}

.battle-log-shell :deep(.history-seat-ledger article.dead::after) {
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 60%;
  height: 2px;
  background: rgba(192, 57, 43, 0.5);
  transform: translate(-50%, -50%);
}

.battle-log-shell :deep(.history-seat-ledger article.dead img) {
  opacity: 0.5;
}

.battle-log-shell :deep(.history-seat-ledger article.sheriff) {
  border-color: rgba(212, 175, 55, 0.35);
  background: rgba(255, 241, 199, 0.35);
  box-shadow: 0 0 0 1px rgba(212, 175, 55, 0.15);
}

.battle-log-shell :deep(.history-seat-ledger img) {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

.battle-log-shell :deep(.history-seat-ledger b) {
  overflow: hidden;
  color: var(--log-text);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-seat-ledger span) {
  overflow: hidden;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-log-shell :deep(.sheriff-badge-inline) {
  width: 14px;
  height: 14px;
  filter: drop-shadow(0 0 4px rgba(255, 211, 115, 0.6));
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger) {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  padding: 8px 8px 10px;
  background: transparent;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article) {
  gap: 3px;
  min-height: 31px;
  padding: 5px 7px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.68);
  box-shadow: none;
  transition: background 0.15s ease;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.selectable) {
  cursor: pointer;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.selectable:hover) {
  background: rgba(255, 244, 215, 0.72);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.selected) {
  background: rgba(255, 226, 157, 0.52);
  box-shadow: inset 3px 0 0 var(--log-accent-strong);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger img) {
  width: 16px;
  height: 16px;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger b) {
  font-size: 11px;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger span) {
  font-size: 10px;
}

.history-side-card :deep(.history-seat-ledger article),
.battle-log-shell :deep(.history-side-card .history-seat-ledger article) {
  display: grid;
  grid-template-columns: 16px max-content max-content;
  align-items: center;
  justify-content: start;
  column-gap: 4px;
  min-width: 0;
  padding: 5px 6px;
}

.history-side-card :deep(.history-seat-ledger b),
.history-side-card :deep(.history-seat-ledger span),
.battle-log-shell :deep(.history-side-card .history-seat-ledger b),
.battle-log-shell :deep(.history-side-card .history-seat-ledger span) {
  flex: none;
  min-width: max-content;
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}

.history-side-card :deep(.history-seat-ledger .sheriff-badge-inline),
.battle-log-shell :deep(.history-side-card .history-seat-ledger .sheriff-badge-inline) {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 12px;
  height: 12px;
}

/* ──────────────────────────────────────────────
   Phase timeline
   ────────────────────────────────────────────── */
.battle-log-shell :deep(.history-phase-tabs) {
  display: flex;
  position: relative;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
  padding: 7px 2px 6px;
  width: 100%;
  min-width: 0;
  border-top: 1px solid var(--log-border);
  border-bottom: 1px solid var(--log-border);
  height: 54px;
  min-height: 54px;
  max-height: 54px;
  flex-wrap: nowrap;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}

.battle-log-shell :deep(.history-phase-tabs)::-webkit-scrollbar {
  display: none;
}

.battle-log-shell :deep(.history-phase-tabs .phase-step) {
  position: relative;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: 14px minmax(44px, max-content);
  align-items: center;
  column-gap: 7px;
  min-width: 70px;
  height: 40px;
  margin-right: 12px;
  padding: 0 8px 0 0;
  border: none;
  border-radius: 7px;
  color: var(--log-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: color 0.15s ease;
}

.battle-log-shell :deep(.history-phase-tabs .phase-step::before) {
  content: "";
  position: absolute;
  top: 20px;
  left: 8px;
  right: -14px;
  height: 1px;
  background: rgba(139, 94, 52, 0.18);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step:last-child::before) {
  right: auto;
  width: 8px;
}

.battle-log-shell :deep(.phase-dot) {
  position: relative;
  z-index: 1;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(139, 94, 52, 0.32);
  border-radius: 999px;
  background: #fff8e8;
  box-shadow: 0 0 0 3px rgba(255, 248, 232, 0.95);
}

.battle-log-shell :deep(.phase-copy) {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 2px 0 0;
  text-align: left;
  white-space: nowrap;
}

.battle-log-shell :deep(.phase-copy small) {
  color: rgba(139, 107, 74, 0.82);
  font-size: 10px;
  font-weight: 850;
  line-height: 1;
}

.battle-log-shell :deep(.phase-copy b) {
  color: var(--log-accent-strong);
  font-size: 12px;
  font-weight: 950;
  line-height: 1.05;
}

.battle-log-shell :deep(.history-phase-tabs .phase-step:hover) {
  color: var(--log-accent-strong);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step:hover .phase-dot) {
  border-color: rgba(139, 94, 52, 0.62);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.active::before) {
  background: linear-gradient(90deg, rgba(90, 51, 25, 0.7), rgba(139, 94, 52, 0.22));
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.active .phase-dot) {
  border-color: var(--log-accent-strong);
  background: var(--log-accent-strong);
  box-shadow: 0 0 0 4px rgba(255, 226, 157, 0.72);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.active .phase-copy small) {
  color: var(--log-accent);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.active .phase-copy b) {
  color: var(--log-accent-strong);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-night .phase-dot) {
  border-color: rgba(70, 58, 110, 0.42);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-vote .phase-dot),
.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-exile_vote .phase-dot),
.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-pk_vote .phase-dot),
.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-sheriff_vote .phase-dot) {
  border-color: rgba(166, 88, 45, 0.45);
}

.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-ended .phase-dot),
.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-result .phase-dot),
.battle-log-shell :deep(.history-phase-tabs .phase-step.phase-finished .phase-dot) {
  border-color: rgba(90, 51, 25, 0.55);
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs) {
  height: 54px;
  min-height: 54px;
  max-height: 54px;
  padding: 7px 2px 6px;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step) {
  height: 40px;
}

/* Legacy fallback for any external plain-button phase tabs. */
.battle-log-shell :deep(.history-phase-tabs button:not(.phase-step)) {
  flex: 0 0 auto;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--log-input-border);
  border-radius: 15px;
  color: var(--log-accent);
  background: var(--log-surface);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-phase-tabs button:not(.phase-step):hover) {
  background: var(--log-hover);
  border-color: var(--log-accent);
}

.battle-log-shell :deep(.history-phase-tabs button:not(.phase-step).active) {
  color: #fff;
  background: var(--log-accent-strong);
  border-color: var(--log-accent-strong);
  box-shadow: 0 2px 6px rgba(90, 51, 25, 0.25);
}

/* ──────────────────────────────────────────────
   Page detail container
   ────────────────────────────────────────────── */
.history-page-detail {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow-y: auto;
  scrollbar-width: none;
  gap: 0;
}

.history-page-detail::-webkit-scrollbar {
  display: none;
}

.detail-main-column > .history-page-detail {
  overflow: hidden auto;
}

.history-page-detail > header:not(.phase-overview) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.phase-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: stretch;
  gap: 12px;
  margin: 0;
  padding: 14px 16px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background:#FAE9BA;
}

.phase-overview-copy {
  display: grid;
  align-content: center;
  gap: 5px;
  min-width: 0;
}

.phase-overview-copy small {
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 900;
  line-height: 1;
}

.phase-overview-copy h3 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--log-text);
  font-size: 18px;
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-overview-copy p {
  margin: 0;
  color: var(--log-text-secondary);
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
}

.phase-overview-stats {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(58px, auto);
  gap: 1px;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 6px;
  background: rgba(139, 94, 52, 0.12);
}

.phase-overview-stats span {
  display: grid;
  align-content: center;
  gap: 5px;
  min-width: 58px;
  padding: 8px 10px;
  border: 1px solid rgba(139, 94, 52, 0.1);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.68);
}

.phase-overview-stats small {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 850;
  line-height: 1;
  white-space: nowrap;
}

.phase-overview-stats b {
  color: var(--log-accent-strong);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  font-weight: 950;
  line-height: 1;
}

/* ──────────────────────────────────────────────
   Night / Speech / Vote sections
   ────────────────────────────────────────────── */
.history-page-detail :deep(.history-night-section) {
  margin: 0;
  padding: 14px 14px 16px 14px;
  border-top: 1px solid var(--log-border);
}

.history-page-detail :deep(.history-night-section:first-child) {
  border-top: 0;
}

.history-page-detail :deep(.night-banner) {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--log-border);
  background: var(--log-surface);
  color: var(--log-text);
  margin-bottom: 14px;
  border-radius: 8px;
  border: 1px solid var(--log-border);
}

.history-page-detail :deep(.night-banner h3) {
  margin: 0;
  font-size: 16px;
  color: var(--log-text);
  font-weight: 800;
}

.history-page-detail :deep(.night-result-bar) {
  padding: 8px 12px;
  margin: 0 0 12px;
  border-width: 1px;
  border-radius: 7px;
  background: var(--log-active-bg);
  border-style: solid;
  border-color: var(--log-border);
  color: var(--log-text);
  font-size: 13px;
  font-weight: 700;
}

.history-page-detail :deep(.night-two-col) {
  display: grid;
  grid-template-columns: 1fr 240px;
  gap: 0;
  min-height: 0;
  height: clamp(360px, calc(100vh - 360px), 620px);
  overflow: hidden;
}

.history-page-detail :deep(.night-left) {
  min-height: 0;
  padding-right: 8px;
  overflow-y: auto;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.history-page-detail :deep(.night-left)::-webkit-scrollbar {
  display: block;
  width: 6px;
}

.history-page-detail :deep(.night-left)::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.34);
}

.history-page-detail :deep(.night-action-grid) {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 6px;
  padding-right: 4px;
  padding-bottom: 4px;
  background: transparent;
}

.history-page-detail :deep(.night-mini-card) {
  padding: 12px 14px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.68);
  cursor: pointer;
  transition: all 0.18s ease;
}

.history-page-detail :deep(.night-mini-card:hover) {
  background: rgba(255, 241, 199, 0.4);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.08);
}

.history-page-detail :deep(.night-mini-card.sel) {
  background: rgba(255, 226, 157, 0.35);
  box-shadow: inset 3px 0 0 var(--log-accent-strong);
}

.history-page-detail :deep(.night-right) {
  border-left: 1px solid var(--log-border);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.history-page-detail :deep(.nmc-tabs) {
  display: flex;
  border-bottom: 1px solid var(--log-border);
  overflow-x: auto;
  scrollbar-width: none;
  flex-shrink: 0;
}

.history-page-detail :deep(.nmc-tabs::-webkit-scrollbar) {
  display: none;
}

.history-page-detail :deep(.nmc-tab) {
  flex: 0 0 auto;
  padding: 8px 12px;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.history-page-detail :deep(.nmc-tab:hover) {
  color: var(--log-accent);
}

.history-page-detail :deep(.nmc-tab.on) {
  color: var(--log-text);
  border-bottom-color: var(--log-accent);
  font-weight: 700;
}

.history-page-detail :deep(.nmc-detail-body) {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
  min-height: 0;
}

.history-page-detail :deep(.nmc-detail-body::-webkit-scrollbar) {
  display: block;
  width: 6px;
}

.history-page-detail :deep(.nmc-detail-body::-webkit-scrollbar-thumb) {
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.34);
}

.history-page-detail :deep(.nmc-dt) {
  margin-bottom: 14px;
}

.history-page-detail :deep(.nmc-dt h4) {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--log-accent);
}

.history-page-detail :deep(.nmc-dt p) {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--log-text);
  line-height: 1.6;
}

.history-page-detail :deep(.nmc-tbl) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.history-page-detail :deep(.nmc-tbl th) {
  text-align: left;
  padding: 5px 8px;
  border-bottom: 1px solid var(--log-border);
  color: var(--log-accent);
  font-weight: 700;
}

.history-page-detail :deep(.nmc-tbl td) {
  padding: 4px 8px;
  border-bottom: 1px solid rgba(139, 94, 52, 0.06);
  color: var(--log-text);
}

/* Night mini-card internal elements */
.history-page-detail :deep(.nmc-header) {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.history-page-detail :deep(.nmc-role) {
  color: var(--log-text);
  font-size: 13px;
  font-weight: 800;
}

.history-page-detail :deep(.nmc-seat) {
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.history-page-detail :deep(.nmc-action) {
  font-size: 13px;
  color: var(--log-text);
  line-height: 1.45;
}

.history-page-detail :deep(.nmc-row) {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 5px;
}

.history-page-detail :deep(.nmc-label) {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.history-page-detail :deep(.nmc-val) {
  color: var(--log-text);
  font-size: 12px;
}

.history-page-detail :deep(.nmc-reason) {
  color: var(--log-text-secondary);
  font-size: 12px;
}

.history-page-detail :deep(.nmc-code) {
  background: rgba(45, 24, 9, 0.04);
  border: 1px solid var(--log-border);
  border-radius: 4px;
  padding: 8px 10px;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  color: var(--log-text);
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ──────────────────────────────────────────────
   Last words section
   ────────────────────────────────────────────── */
.history-lastwords-section {
  margin-top: 16px;
}

.history-page-detail :deep(.history-lastwords-section) {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--log-border);
}

.history-page-detail :deep(.last-word-card) {
  padding: 12px;
  margin-bottom: 8px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.58);
}

.history-page-detail :deep(.last-word-card:last-child) {
  margin-bottom: 0;
  border-bottom: 1px solid var(--log-border);
}

.history-page-detail :deep(.last-word-card header) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.history-page-detail :deep(.last-word-actor) {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--log-accent-strong);
  color: #fff;
  font-size: 13px;
  font-weight: 800;
}

.history-page-detail :deep(.last-word-role) {
  display: inline-block;
  padding: 4px 10px;
  border: 1px solid var(--log-input-border);
  border-radius: 6px;
  background: var(--log-surface);
  color: var(--log-text);
  font-size: 12px;
  font-weight: 700;
}

.history-page-detail :deep(.last-word-label) {
  color: var(--log-accent);
  font-size: 13px;
  font-weight: 800;
}

.history-page-detail :deep(.last-word-message) {
  margin: 0;
  color: var(--log-text);
  font-size: 14px;
  line-height: 1.6;
}

.history-page-detail :deep(.last-word-decision) {
  margin-top: 10px;
  border-top: 1px solid var(--log-border);
  padding-top: 8px;
}

.history-page-detail :deep(.last-word-decision summary) {
  color: var(--log-accent);
  cursor: pointer;
  font-weight: 700;
  font-size: 13px;
  transition: color 0.15s ease;
}

.history-page-detail :deep(.last-word-decision summary:hover) {
  color: var(--log-accent-strong);
}

.history-page-detail :deep(.last-word-decision small) {
  display: block;
  margin-top: 6px;
  color: var(--log-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

/* ──────────────────────────────────────────────
   Raw logs section
   ────────────────────────────────────────────── */
.history-raw-section {
  display: grid;
  gap: 0;
  padding: 0;
  margin-top: 0;
  border-top: 1px solid var(--log-border);
}

.history-raw-more {
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.history-timeline {
  display: grid;
  gap: 8px;
  padding: 12px 16px;
}

.history-raw-log {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 0;
  min-width: 0;
  padding: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  transition: none;
}

.history-raw-log:hover .timeline-card {
  background: rgba(255, 248, 232, 0.72);
}

.timeline-rail {
  position: relative;
  display: grid;
  justify-items: center;
  min-height: 100%;
}

.timeline-rail::before {
  content: "";
  position: absolute;
  top: 16px;
  bottom: -1px;
  width: 1px;
  background: rgba(139, 94, 52, 0.18);
}

.history-raw-log:last-child .timeline-rail::before {
  bottom: calc(100% - 16px);
}

.timeline-rail i {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  margin-top: 14px;
  border: 2px solid rgba(139, 94, 52, 0.42);
  border-radius: 999px;
  background: #fff8e8;
  box-shadow: 0 0 0 4px rgba(255, 246, 224, 0.82);
}

.timeline-card {
  min-width: 0;
  padding: 11px 14px 12px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.68);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.timeline-card:hover {
  background: rgba(255, 252, 245, 0.9);
}

.history-raw-log header {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--log-text-secondary);
  font-size: 12px;
}

.history-raw-log b {
  color: var(--log-accent);
  font-size: 12px;
}

.history-raw-log em {
  margin-left: auto;
  color: var(--log-text);
  font-style: normal;
  font-weight: 700;
  font-size: 12px;
}

.history-raw-log p {
  margin: 0;
  color: var(--log-text);
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
}

.history-raw-log small {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
}

.history-raw-more {
  padding: 6px 0 2px;
  text-align: center;
}

.empty-log {
  padding: 40px 20px;
  text-align: center;
  color: var(--log-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

/* Role assignment grid */
.role-assignment-title {
  margin: 0 0 6px;
  color: var(--log-text);
  font-size: 14px;
  font-weight: 700;
}

.role-assignment-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px 16px;
  padding: 6px 0;
}

.role-assignment-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 7px 8px;
  border: 1px solid var(--log-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.58);
}

.ra-seat {
  font-size: 13px;
  font-weight: 700;
  color: var(--log-accent);
}

.ra-role {
  font-size: 12px;
  color: var(--log-text);
  font-weight: 600;
}

/* ──────────────────────────────────────────────
   Speech cards
   ────────────────────────────────────────────── */
.history-page-detail :deep(.speech-card) {
  padding: 12px;
  margin-bottom: 8px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.58);
}

.history-page-detail :deep(.speech-card:last-child) {
  margin-bottom: 0;
  border-bottom: 1px solid var(--log-border);
}

.history-page-detail :deep(.speech-card header) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.history-page-detail :deep(.speech-actor-badge) {
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--log-accent-strong);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}

.history-page-detail :deep(.speech-role-badge) {
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--log-active-bg);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 600;
}

.history-page-detail :deep(.speech-type-label) {
  color: var(--log-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.history-page-detail :deep(.speech-message) {
  margin: 0 0 8px;
  color: var(--log-text);
  font-size: 14px;
  line-height: 1.55;
}

.history-page-detail :deep(.speech-decision summary) {
  color: var(--log-accent);
  cursor: pointer;
  font-weight: 700;
  font-size: 13px;
}

.history-page-detail :deep(.speech-decision small) {
  display: block;
  margin-top: 6px;
  color: var(--log-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.history-page-detail :deep(.decision-detail-grid) {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin: 8px 0;
  padding: 8px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  background: var(--log-surface);
}

.history-page-detail :deep(.decision-detail-item) {
  font-size: 12px;
  color: var(--log-text);
}

.history-page-detail :deep(.decision-detail-item span:first-child) {
  font-weight: 800;
  color: var(--log-accent);
}

/* ──────────────────────────────────────────────
   Vote section
   ────────────────────────────────────────────── */
.history-page-detail :deep(.history-vote-section) {
  margin-top: 14px;
}

.history-page-detail :deep(.history-vote-section h3) {
  margin: 0 0 12px;
  color: var(--log-accent);
  font-size: 16px;
}

.history-page-detail :deep(.vote-result-card) {
  padding: 12px;
  margin-bottom: 8px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.58);
}

.history-page-detail :deep(.vote-result-card header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.history-page-detail :deep(.vote-target-name) {
  color: var(--log-text);
  font-size: 18px;
  font-weight: 900;
}

.history-page-detail :deep(.vote-target-number) {
  color: var(--log-text);
  font-size: 20px;
  font-weight: 900;
}

.history-page-detail :deep(.vote-target-role) {
  padding: 3px 8px;
  border: 1px solid var(--log-input-border);
  border-radius: 4px;
  background: var(--log-surface);
  color: var(--log-text);
  font-size: 11px;
  font-weight: 800;
}

.history-page-detail :deep(.vote-entry) {
  padding: 8px 10px;
  margin-bottom: 6px;
  border: 1px solid rgba(139, 94, 52, 0.1);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.48);
}

.history-page-detail :deep(.vote-badge) {
  display: inline-block;
  padding: 3px 8px;
  border: 1px solid var(--log-input-border);
  border-radius: 4px;
  background: var(--log-surface);
  color: var(--log-text);
  font-size: 12px;
  font-weight: 800;
}

.history-page-detail :deep(.vote-count) {
  display: block;
  margin-top: 8px;
  color: var(--log-accent);
  font-size: 13px;
  font-weight: 800;
}

.history-page-detail :deep(.vote-decision summary) {
  color: var(--log-accent);
  cursor: pointer;
  font-size: 12px;
}

.history-page-detail :deep(.vote-decision small) {
  display: block;
  margin-top: 4px;
  color: var(--log-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

/* ──────────────────────────────────────────────
   Decision cards & extra sections
   ────────────────────────────────────────────── */
.history-page-detail :deep(.history-log-row),
.history-page-detail :deep(.history-decision-row) {
  border: 1px solid var(--log-border);
  border-radius: 8px;
  color: var(--log-text);
  background: rgba(255, 252, 245, 0.58);
  padding: 10px 12px;
  margin-bottom: 8px;
}

.history-page-detail :deep(.history-log-row span),
.history-page-detail :deep(.history-decision-row span),
.history-page-detail :deep(.history-decision-row small) {
  color: var(--log-text-secondary);
}

.history-page-detail :deep(.history-log-row p),
.history-page-detail :deep(.history-decision-row p),
.history-page-detail :deep(.history-decision-row em) {
  color: var(--log-text);
}

.history-page-detail :deep(.history-log-row b),
.history-page-detail :deep(.history-decision-row b) {
  color: var(--log-accent);
}

.history-page-detail :deep(.history-decision-row em) {
  display: block;
  margin-top: 8px;
  color: var(--log-text);
  font-style: normal;
  font-weight: 800;
  line-height: 1.5;
}

.history-page-detail :deep(.history-decision-row summary) {
  cursor: pointer;
  list-style: none;
}

.history-page-detail :deep(.history-decision-row summary::-webkit-details-marker) {
  display: none;
}

.history-page-detail :deep(.decision-extra-section) {
  margin-top: 8px;
  border-top: 1px solid var(--log-border);
  padding-top: 7px;
}

.history-page-detail :deep(.decision-extra-section summary) {
  color: var(--log-accent);
  cursor: pointer;
  font-weight: 800;
}

.history-page-detail :deep(.decision-json-block) {
  max-height: 240px;
  overflow: auto;
  margin: 8px 0 0;
  padding: 10px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  color: var(--log-text);
  background: rgba(255, 248, 225, 0.5);
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  white-space: pre-wrap;
}

.history-page-detail :deep(.decision-error) {
  color: #8f1f10 !important;
}

.history-page-detail :deep(.decision-policy) {
  color: var(--log-accent) !important;
}

/* Player status grid */
.history-page-detail :deep(.player-status-grid span) {
  padding: 4px 10px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  background: var(--log-surface);
  color: var(--log-text);
  font-size: 12px;
  font-weight: 800;
}

.history-page-detail :deep(.player-status-grid span.dead) {
  opacity: 0.5;
  text-decoration: line-through;
  text-decoration-color: #c0392b;
}

/* ──────────────────────────────────────────────
   Responsive adjustments
   ────────────────────────────────────────────── */
@media (max-width: 1280px) {
  .detail-content {
    grid-template-columns: minmax(0, 1fr) 280px;
  }
}

@media (max-width: 1120px) {
  .detail-analysis-bar {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 0.8fr);
  }

  .detail-analysis-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .detail-topbar {
    align-items: stretch;
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "workspace"
      "context"
      "phases";
  }

  .detail-topbar :deep(.history-phase-tabs) {
    order: 3;
    flex-basis: 100%;
  }

  .detail-actions {
    margin-left: auto;
  }

  .detail-content {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .detail-side-column {
    grid-template-columns: 1fr;
    overflow-x: hidden;
    overflow-y: auto;
  }
}

@media (max-width: 960px) {
  .battle-log-page {
    top: 72px;
    right: 18px;
    bottom: 0;
    left: 18px;
    width: auto;
    margin: 0;
    padding: 0 0 18px;
  }

  .battle-log-shell {
    grid-template-columns: 1fr;
    gap: 16px;
    padding: 16px;
    overflow-x: hidden;
    overflow-y: auto;
  }

  .history-detail-panel {
    display: block;
    min-width: 0;
    padding: 0;
    overflow: visible;
  }

  .detail-analysis-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 10px;
    padding: 14px;
  }

  .detail-analysis-title {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .detail-analysis-title h2 {
    font-size: 19px;
  }

  .detail-analysis-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }

  .detail-analysis-metrics span {
    min-height: 42px;
    padding: 7px 9px;
  }

  .detail-analysis-metrics b {
    font-size: 14px;
  }

  .detail-analysis-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    justify-content: stretch;
  }

  .detail-analysis-actions button {
    width: 100%;
    min-width: 0;
    height: 38px;
    padding: 0 10px;
  }

  .detail-topbar {
    padding: 10px 12px;
    overflow: hidden;
  }

  .detail-workspace-tabs {
    max-width: 100%;
    padding-bottom: 4px;
  }

  .detail-workspace-tabs button {
    min-width: max-content;
  }

  .detail-topbar :deep(.history-phase-tabs) {
    height: auto;
    min-height: 34px;
    max-height: none;
    padding-bottom: 6px;
  }

  .detail-topbar :deep(.history-phase-tabs button:not(.phase-step)) {
    height: 28px;
    padding: 0 11px;
  }

  .detail-content {
    flex: none;
    padding: 12px;
    gap: 12px;
    overflow: visible;
  }

  .battle-log-shell :deep(.history-games-panel) {
    max-height: 292px;
    padding: 0;
    border-right: none;
    border-bottom: 1px solid var(--log-border);
  }

  .battle-log-shell :deep(.history-games-list) {
    max-height: 186px;
  }
}

@media (max-width: 820px) {
  .detail-side-column {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .battle-log-page {
    right: 10px;
    left: 10px;
    padding-bottom: 10px;
  }

  .battle-log-shell {
    padding: 12px;
  }

  .detail-analysis-bar {
    gap: 8px;
    padding: 12px;
  }

  .detail-analysis-title {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-analysis-title span {
    justify-self: start;
  }

  .detail-analysis-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px;
  }

  .detail-workspace-tabs button {
    height: 30px;
    padding: 0 10px;
  }

  .history-detail-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .history-page-detail :deep(.night-two-col) {
    grid-template-columns: 1fr;
  }

  .history-page-detail :deep(.night-right) {
    border-left: none;
    border-top: 1px solid var(--log-border);
  }

  .detail-content,
  .detail-side-column {
    grid-template-columns: 1fr;
  }

  .detail-main-column > .history-page-detail {
    padding: 12px;
    border-radius: 8px;
  }

  .history-raw-log header {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .history-raw-log em {
    width: 100%;
    margin-left: 0;
  }

  .battle-log-shell :deep(.history-games-panel) {
    max-height: 274px;
  }

  .battle-log-shell :deep(.history-games-list) {
    max-height: 154px;
  }

  .battle-log-shell :deep(.history-game-item) {
    margin-inline: 4px;
  }

  .battle-log-shell :deep(.history-game-title) {
    grid-template-columns: minmax(0, 1fr);
    gap: 3px;
  }

  .detail-actions {
    width: 100%;
  }

  .detail-actions button {
    flex: 1;
  }

  .role-assignment-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

/* Warm tactile logbook skin, adapted to the current information layout. */
.battle-log-page {
  --log-card-bg: linear-gradient(145deg, rgba(255, 249, 230, 0.9), rgba(232, 202, 145, 0.56));
  --log-card-bg-soft: linear-gradient(145deg, rgba(255, 252, 239, 0.72), rgba(224, 191, 132, 0.34));
  --log-card-border: rgba(104, 56, 22, 0.25);
  --log-card-highlight: rgba(255, 250, 224, 0.82);
  --log-card-shadow: 0 5px 13px rgba(74, 38, 15, 0.1);
  --log-card-shadow-active: 0 8px 18px rgba(74, 38, 15, 0.16);
}

.detail-topbar,
.detail-content,
.detail-main-column > .history-page-detail,
.history-side-card {
  border-color: var(--log-card-border);
  background: var(--log-card-bg-soft);
  box-shadow: var(--log-card-shadow), inset 0 1px 0 var(--log-card-highlight);
}

.detail-topbar {
  padding: 12px 16px 13px;
}

.detail-workspace-tabs button,
.detail-actions button,
.document-empty button,
.history-assess-empty-body button,
.battle-log-shell :deep(.history-load-more),
.battle-log-shell :deep(.history-game-replay) {
  border-color: rgba(104, 56, 22, 0.3);
  color: #4a250f;
  background: linear-gradient(180deg, rgba(255, 248, 218, 0.94), rgba(219, 177, 105, 0.72));
  box-shadow: 0 3px 7px rgba(74, 38, 15, 0.14), inset 0 1px 0 rgba(255, 253, 235, 0.9), inset 0 -1px 0 rgba(104, 56, 22, 0.12);
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, filter 0.16s ease;
}

.detail-workspace-tabs button:hover,
.detail-actions button:hover:not(:disabled),
.document-empty button:hover,
.history-assess-empty-body button:hover:not(:disabled),
.battle-log-shell :deep(.history-load-more:hover:not(:disabled)),
.battle-log-shell :deep(.history-game-replay:hover) {
  border-color: rgba(104, 56, 22, 0.48);
  color: #321606;
  background: linear-gradient(180deg, rgba(255, 252, 231, 1), rgba(231, 190, 116, 0.84));
  box-shadow: 0 5px 12px rgba(74, 38, 15, 0.2), inset 0 1px 0 #fff9df;
  filter: saturate(1.08);
  transform: translateY(-1px);
}

.detail-workspace-tabs button:active,
.detail-actions button:active:not(:disabled),
.battle-log-shell :deep(.history-game-replay:active) {
  box-shadow: inset 0 2px 5px rgba(74, 38, 15, 0.22);
  transform: translateY(1px);
}

.detail-workspace-tabs button.active {
  border-color: #5a3319;
  color: #fff4d2;
  background: linear-gradient(180deg, #81522b, #4a260f);
  box-shadow: 0 4px 10px rgba(58, 27, 9, 0.25), inset 0 1px 0 rgba(255, 226, 164, 0.32);
}

.battle-log-shell :deep(.history-source-tabs button) {
  border-color: rgba(104, 56, 22, 0.25);
  color: #4a250f;
  background: linear-gradient(180deg, rgba(255, 249, 226, 0.82), rgba(223, 185, 119, 0.5));
  box-shadow: 0 2px 6px rgba(74, 38, 15, 0.08), inset 0 1px 0 rgba(255, 252, 235, 0.88);
}

.battle-log-shell :deep(.history-source-tabs button:hover) {
  border-color: rgba(104, 56, 22, 0.42);
  background: linear-gradient(180deg, rgba(255, 252, 235, 0.96), rgba(231, 190, 117, 0.62));
  transform: translateY(-1px);
}

.battle-log-shell :deep(.history-source-tabs button.active) {
  border-color: rgba(90, 51, 25, 0.62);
  background: linear-gradient(180deg, rgba(244, 211, 145, 0.92), rgba(191, 132, 67, 0.66));
  box-shadow: 0 4px 10px rgba(74, 38, 15, 0.14), inset 0 1px 0 rgba(255, 248, 216, 0.9), inset 3px 0 0 #70401e;
}

.battle-log-shell :deep(.history-game-item) {
  border-color: rgba(104, 56, 22, 0.14);
  background: var(--log-card-bg-soft);
  box-shadow: inset 0 1px 0 rgba(255, 251, 231, 0.64);
}

.battle-log-shell :deep(.history-game-item:hover) {
  border-color: rgba(104, 56, 22, 0.32);
  background: var(--log-card-bg);
  box-shadow: var(--log-card-shadow);
  transform: translateY(-1px);
}

.battle-log-shell :deep(.history-game-item.active) {
  border-color: rgba(90, 51, 25, 0.4);
  border-left-color: #70401e;
  background: linear-gradient(145deg, rgba(255, 240, 195, 0.94), rgba(210, 161, 87, 0.58));
  box-shadow: var(--log-card-shadow-active), inset 0 1px 0 rgba(255, 250, 224, 0.86);
}

.battle-log-shell :deep(.history-game-meta small),
.battle-log-shell :deep(.history-mode-tag),
.battle-log-shell :deep(.history-source-tag),
.detail-workspace-tabs small {
  border-color: rgba(104, 56, 22, 0.18);
  background: rgba(255, 246, 218, 0.54);
  box-shadow: inset 0 1px 0 rgba(255, 253, 237, 0.68);
}

.history-page-detail :deep(.night-mini-card),
.history-page-detail :deep(.speech-card),
.history-page-detail :deep(.vote-result-card),
.history-page-detail :deep(.last-word-card),
.history-page-detail :deep(.history-log-row),
.history-page-detail :deep(.history-decision-row),
.history-side-card :deep(.history-seat-ledger article) {
  border-color: rgba(104, 56, 22, 0.2);
  background: var(--log-card-bg-soft);
  box-shadow: 0 3px 9px rgba(74, 38, 15, 0.07), inset 0 1px 0 rgba(255, 252, 235, 0.72);
}

.history-page-detail :deep(.night-mini-card:hover),
.history-page-detail :deep(.speech-card:hover),
.history-page-detail :deep(.vote-result-card:hover),
.history-side-card :deep(.history-seat-ledger article:hover) {
  border-color: rgba(104, 56, 22, 0.38);
  background: var(--log-card-bg);
  box-shadow: var(--log-card-shadow);
}

.history-page-detail :deep(.night-mini-card.sel),
.history-side-card :deep(.history-seat-ledger article.selected) {
  border-color: rgba(90, 51, 25, 0.54);
  background: linear-gradient(145deg, rgba(255, 239, 193, 0.96), rgba(205, 151, 80, 0.62));
  box-shadow: var(--log-card-shadow-active), inset 3px 0 0 #70401e;
}

/* ── Review report parchment styling ── */
.history-page-detail :deep(.archive-review-panel) {
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.archive-review-panel > h3) {
  display: none;
}

.history-page-detail :deep(.archive-review-panel h4) {
  margin: 0;
  padding: 8px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
}

.history-page-detail :deep(.review-summary-strip) {
  display: none;
}

.history-page-detail :deep(.archive-review-panel > div:has(.review-tp-card)),
.history-page-detail :deep(.archive-review-panel > div:has(.review-cf-card)),
.history-page-detail :deep(.review-timeline) {
  display: none;
}

.history-page-detail :deep(.review-score-section) {
  margin: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.review-score-panel-head) {
  padding: 8px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
  background: transparent;
}

.history-page-detail :deep(.review-score-panel-head small) {
  display: none;
}

.history-page-detail :deep(.review-score-panel-head b) {
  display: none;
}

.history-page-detail :deep(.review-score-grid) {
  background: transparent;
  gap: 0;
}

.history-page-detail :deep(.review-score-card) {
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.review-score-card:hover) {
  background: rgba(255, 244, 207, 0.2);
}

.history-page-detail :deep(.review-tp-card) {
  margin: 0;
  padding: 8px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
}

.history-page-detail :deep(.review-tp-card:hover) {
  background: rgba(255, 244, 207, 0.2);
}

.history-page-detail :deep(.review-day-badge) {
  border: 0;
  border-radius: 4px;
  background: rgba(93, 48, 17, 0.08);
  color: var(--log-accent);
}

.history-page-detail :deep(.review-cf-card) {
  margin: 0;
  padding: 8px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
}

.history-page-detail :deep(.review-tl-item) {
  padding: 6px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
}

.history-page-detail :deep(.review-tl-badge) {
  border-radius: 4px;
  background: rgba(93, 48, 17, 0.08);
}

/* ── Archive panel parchment styling ── */
.history-page-detail :deep(.archive-review-panel) {
  gap: 0;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.archive-merged-strip) {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 10px 14px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 6px;
  background: #FAE9BA;
  box-shadow: inset 0 1px 0 rgba(255, 244, 205, 0.66);
}

.history-page-detail :deep(.archive-merged-item) {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.history-page-detail :deep(.archive-merged-item small) {
  color: rgba(74, 37, 15, 0.56);
  font-size: 12px;
  font-weight: 800;
}

.history-page-detail :deep(.archive-merged-item b) {
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}

.history-page-detail :deep(.archive-merged-item b.archive-kpi-error) {
  color: #c0392b;
}

.history-page-detail :deep(.archive-review-panel h4) {
  margin: 0;
  padding: 8px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
}

.history-page-detail :deep(.archive-section) {
  gap: 0;
}

.history-page-detail :deep(.archive-highlight-list) {
  gap: 0;
  margin: 0;
  padding: 0;
}

.history-page-detail :deep(.archive-highlight-list li) {
  padding: 8px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
  color: var(--log-text);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.48;
}

.history-page-detail :deep(.archive-source-list) {
  gap: 0;
}

.history-page-detail :deep(.archive-source-row) {
  padding: 6px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.08);
}

.history-page-detail :deep(.archive-source-label) {
  border-radius: 4px;
  background: rgba(93, 48, 17, 0.08);
}

.history-page-detail :deep(.archive-source-track) {
  border-radius: 999px;
  background: rgba(93, 48, 17, 0.06);
}

.history-page-detail :deep(.archive-decision-list) {
  gap: 0;
}

.history-page-detail :deep(.archive-decision-card) {
  padding: 8px 0;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.1);
  border-radius: 0;
  background: transparent;
}

.history-page-detail :deep(.archive-decision-card:hover) {
  background: rgba(255, 244, 207, 0.2);
}

.history-page-detail :deep(.archive-decision-card header small) {
  border-radius: 4px;
  background: rgba(93, 48, 17, 0.08);
}

.history-page-detail :deep(.archive-extra-fields) {
  margin: 0;
  padding-top: 10px;
  border-top: 1px solid rgba(93, 48, 17, 0.15);
}

.history-page-detail :deep(.archive-extra-fields summary) {
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 900;
}

.history-page-detail :deep(.archive-extra-fields div) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.history-page-detail :deep(.archive-extra-item) {
  padding: 4px 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.history-page-detail :deep(.archive-extra-item small) {
  color: rgba(74, 37, 15, 0.56);
}

.history-page-detail :deep(.archive-review-panel pre) {
  margin: 0;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 6px;
  background: rgba(255, 248, 225, 0.3);
}

/* Quiet wood-board layout: broad surfaces, separators, very few framed controls. */
.parchment-logbook {
  background:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    #f2dfae;
}

.battle-log-shell :deep(.history-games-panel) {
  padding-right: 20px;
  border-right-color: rgba(93, 48, 17, 0.22);
  border-radius: 0;
}

.battle-log-shell :deep(.history-games-panel header) {
  align-items: flex-start;
  min-height: 34px;
  padding: 0;
  border-bottom-color: rgba(93, 48, 17, 0.2);
}

.battle-log-shell :deep(.history-games-panel header span) {
  font-size: 22px;
  font-weight: 950;
}

.battle-log-shell :deep(.history-source-tabs) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 10px 0;
  border-bottom-color: rgba(93, 48, 17, 0.16);
}

.battle-log-shell :deep(.history-source-tabs button),
.battle-log-shell :deep(.history-source-tabs button:hover),
.battle-log-shell :deep(.history-source-tabs button.active) {
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  height: 31px;
  padding: 0 8px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  transform: none;
}

.battle-log-shell :deep(.history-source-tabs button:hover) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.battle-log-shell :deep(.history-source-tabs button.active) {
  color: #3a1b08;
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.battle-log-shell :deep(.history-source-tabs button small) {
  min-width: auto;
  height: auto;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: inherit;
  background: transparent;
  box-shadow: none;
}

.battle-log-shell :deep(.history-source-tabs button.active small) {
  border: 0;
  border-radius: 0;
  color: inherit;
  background: transparent;
  box-shadow: none;
}

.battle-log-shell :deep(.history-source-tabs button span) {
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-notice) {
  display: flex;
  align-items: center;
  min-height: 32px;
  margin: 0 0 8px;
  padding: 7px 9px;
  border: 1px solid rgba(93, 48, 17, 0.2);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.54);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.72);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.35;
}

.battle-log-shell :deep(.history-notice span) {
  min-width: 0;
  overflow-wrap: anywhere;
}

.battle-log-shell :deep(.history-notice.success) {
  border-color: rgba(46, 116, 61, 0.24);
  color: #2f6b3d;
  background: rgba(215, 232, 194, 0.62);
}

.battle-log-shell :deep(.history-notice.warning) {
  border-color: rgba(151, 95, 18, 0.28);
  color: #76510e;
  background: rgba(248, 223, 157, 0.58);
}

.battle-log-shell :deep(.history-notice.error) {
  border-color: rgba(154, 45, 36, 0.3);
  color: #993026;
  background: rgba(248, 205, 181, 0.6);
}

.battle-log-shell :deep(.history-games-list) {
  padding: 0;
}

.battle-log-shell :deep(.history-game-item),
.battle-log-shell :deep(.history-game-item:hover),
.battle-log-shell :deep(.history-game-item.active) {
  position: relative;
  grid-template-columns: minmax(0, 1fr) auto;
  min-height: 76px;
  margin: 0;
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  transform: none;
}

.battle-log-shell :deep(.history-game-item:hover) {
  background: rgba(255, 245, 211, 0.2);
}

.battle-log-shell :deep(.history-game-item.active) {
  background: linear-gradient(90deg, rgba(255, 240, 194, 0.32), transparent);
  box-shadow: none;
}

.battle-log-shell :deep(.history-game-item.active::before) {
  position: absolute;
  inset: 9px auto 9px 0;
  width: 3px;
  border-radius: 2px;
  background: #70401e;
  content: '';
}

.battle-log-shell :deep(.history-game-title) {
  display: grid;
  justify-items: start;
  gap: 7px;
}

.battle-log-shell :deep(.history-game-title b) {
  font-size: 17px;
  line-height: 1.1;
}

.battle-log-shell :deep(.history-game-support) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.battle-log-shell :deep(.history-game-support time) {
  color: rgba(74, 37, 15, 0.56);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.battle-log-shell :deep(.history-mode-tag),
.battle-log-shell :deep(.history-source-tag) {
  height: 21px;
  padding: 0 7px;
  border: 0;
  border-radius: 4px;
  box-shadow: none;
}

.battle-log-shell :deep(.history-game-actions) {
  display: flex;
  align-items: center;
  gap: 6px;
}

.battle-log-shell :deep(.history-game-delete),
.battle-log-shell :deep(.history-game-delete:hover) {
  display: inline-grid;
  width: 27px;
  height: 29px;
  place-items: center;
  padding: 0;
  border: 0;
  border-bottom: 1px solid rgba(145, 45, 35, 0.34);
  border-radius: 6px;
  color: #b6362d;
  background: rgba(255, 224, 199, 0.54);
  box-shadow: inset 0 1px 0 rgba(255, 247, 230, 0.75);
  transform: none;
}

.battle-log-shell :deep(.history-game-delete svg) {
  width: 14px;
  height: 14px;
  fill: currentColor;
}

.battle-log-shell :deep(.history-game-delete:hover) {
  color: #98251f;
  background: rgba(255, 211, 185, 0.86);
}

.battle-log-shell :deep(.history-game-delete:disabled),
.battle-log-shell :deep(.history-game-delete.protected) {
  border-bottom-color: rgba(91, 47, 18, 0.16);
  color: rgba(91, 47, 18, 0.46);
  background: rgba(91, 47, 18, 0.08);
  cursor: not-allowed;
  opacity: 1;
}

.battle-log-shell :deep(.history-game-delete:disabled:hover),
.battle-log-shell :deep(.history-game-delete.protected:hover) {
  color: rgba(91, 47, 18, 0.46);
  background: rgba(91, 47, 18, 0.08);
}

.battle-log-shell :deep(.history-game-replay),
.battle-log-shell :deep(.history-game-replay:hover) {
  width: 46px;
  height: 29px;
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.35);
  border-radius: 6px;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.74);
  font-size: 12px;
  transform: none;
}

.battle-log-shell :deep(.history-game-replay:hover) {
  background: rgba(255, 245, 214, 0.88);
}

.history-detail-panel {
  padding-left: 20px;
}

.detail-topbar,
.detail-content,
.detail-main-column > .history-page-detail,
.history-side-card {
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.detail-topbar {
  padding: 0;
  border-bottom: 0;
}

.detail-content {
  gap: 22px;
  padding: 8px 0 0;
}

.detail-workspace-tabs {
  gap: 28px;
}

.detail-workspace-tabs button,
.detail-workspace-tabs button:hover,
.detail-workspace-tabs button.active {
  align-items: flex-start;
  min-height: 34px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: rgba(74, 37, 15, 0.72);
  background: transparent;
  box-shadow: none;
  transform: none;
}

.detail-workspace-tabs button span {
  font-size: 22px;
  font-weight: 950;
  line-height: 1;
}

.detail-workspace-tabs button.active {
  color: #321606;
  box-shadow: inset 0 -3px 0 #70401e;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs) {
  align-items: center;
  gap: 0;
  height: 70px;
  min-height: 70px;
  max-height: 70px;
  padding: 11px 10px 11px 0;
  border: 0;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step) {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  isolation: isolate;
  width: 86px;
  min-width: 86px;
  height: 48px;
  margin: 0 -1px 0 0;
  padding: 0 12px;
  border: 0;
  border-radius: 0;
  color: #fff8e8;
  background: #758b73;
  clip-path: none;
  filter: saturate(0.82);
  overflow: visible;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(1)) { z-index: 30; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(2)) { z-index: 29; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(3)) { z-index: 28; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(4)) { z-index: 27; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(5)) { z-index: 26; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(6)) { z-index: 25; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(7)) { z-index: 24; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(8)) { z-index: 23; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(9)) { z-index: 22; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(10)) { z-index: 21; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(11)) { z-index: 20; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(12)) { z-index: 19; }
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(n + 13)) { z-index: 18; }

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:first-child) {
  padding-left: 10px;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step::before) {
  position: absolute;
  z-index: 2;
  top: 50%;
  right: -10px;
  left: auto;
  display: block;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: inherit;
  transform: translateY(-50%);
  content: '';
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step::after) {
  display: none;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-dot) {
  position: absolute;
  z-index: 2;
  display: block;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 50%;
  background: inherit;
  box-shadow: none;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(odd) .phase-dot) {
  top: -9px;
  bottom: auto;
  left: calc(50% - 9px);
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:nth-child(even) .phase-dot) {
  top: auto;
  bottom: -9px;
  left: calc(50% - 9px);
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.active .phase-dot) {
  border: 0;
  background: inherit;
  box-shadow: none;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-night) {
  background: #344d63;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-sheriff),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-sheriff_vote),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-sheriff_result) {
  background: #705f81;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-speech) {
  background: #c45d74;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-vote),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-exile_vote),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-pk_vote) {
  background: #d77548;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-ended),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-result),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.phase-finished) {
  background: #d49a32;
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step:hover) {
  color: #fffdf3;
  filter: brightness(1.06) saturate(0.92);
}

.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.active) {
  z-index: 40;
  color: #fffdf3;
  filter: brightness(1.12) saturate(1.08) drop-shadow(0 2px 3px rgba(74, 37, 15, 0.32));
}

.history-detail-panel .detail-topbar :deep(.phase-copy) {
  z-index: 4;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
  padding: 0;
  text-align: center;
}

.history-detail-panel .detail-topbar :deep(.phase-copy small),
.history-detail-panel .detail-topbar :deep(.phase-copy b),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.active .phase-copy small),
.history-detail-panel .detail-topbar :deep(.history-phase-tabs .phase-step.active .phase-copy b) {
  color: inherit;
  text-shadow: 0 1px 1px rgba(45, 24, 9, 0.35);
}

.history-detail-panel .detail-topbar :deep(.phase-copy small) {
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

.history-detail-panel .detail-topbar :deep(.phase-copy b) {
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

.history-side-card {
  border-left: 1px solid rgba(93, 48, 17, 0.18);
}

.history-side-card--seats,
.history-page-detail :deep(.night-mini-card),
.history-page-detail :deep(.speech-card),
.history-page-detail :deep(.vote-result-card),
.history-page-detail :deep(.last-word-card),
.history-page-detail :deep(.history-log-row),
.history-page-detail :deep(.history-decision-row),
.history-side-card :deep(.history-seat-ledger article) {
  border: 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.night-mini-card:hover),
.history-page-detail :deep(.speech-card:hover),
.history-page-detail :deep(.vote-result-card:hover),
.history-side-card :deep(.history-seat-ledger article:hover) {
  border-color: rgba(93, 48, 17, 0.22);
  background: rgba(255, 244, 207, 0.2);
  box-shadow: none;
}

.history-page-detail :deep(.night-mini-card.sel),
.history-side-card :deep(.history-seat-ledger article.selected) {
  border-color: rgba(93, 48, 17, 0.22);
  background: linear-gradient(90deg, rgba(255, 237, 188, 0.38), transparent);
  box-shadow: inset 3px 0 0 #70401e;
}

/* Player seats use the same compact wood-button language as history filters. */
.history-side-card :deep(.history-seat-ledger article),
.history-side-card :deep(.history-seat-ledger article:hover) {
  min-height: 31px;
  padding: 5px 7px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.history-side-card :deep(.history-seat-ledger article:hover) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.history-side-card :deep(.history-seat-ledger article.selected) {
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.history-side-card :deep(.history-seat-ledger article.dead) {
  border-color: rgba(166, 65, 53, 0.42);
  background: rgba(244, 210, 177, 0.62);
}

.history-side-card :deep(.history-seat-ledger article.sheriff) {
  border-color: rgba(168, 120, 35, 0.48);
  background: rgba(248, 223, 157, 0.72);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article),
.battle-log-shell :deep(.history-side-card .history-seat-ledger article:hover) {
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article:hover) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.selected) {
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.dead) {
  border-color: rgba(166, 65, 53, 0.42);
  background: rgba(244, 210, 177, 0.62);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.sheriff) {
  border-color: rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  background: rgba(255, 239, 194, 0.58);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.selected),
.battle-log-shell :deep(.history-side-card .history-seat-ledger article.dead) {
  border-color: rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.dead::after) {
  display: block;
  left: 50%;
  top: 50%;
  width: calc(100% - 12px);
  height: 2px;
  background: rgba(190, 45, 36, 0.68);
  transform: translate(-50%, -50%);
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article.dead img) {
  opacity: 1;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger article) {
  grid-template-columns: 16px max-content max-content;
  column-gap: 3px;
  padding-right: 5px;
  padding-left: 3px;
}

.battle-log-shell :deep(.history-side-card .history-seat-ledger .sheriff-badge-inline) {
  top: 7px;
  right: 3px;
}

.history-assess-empty {
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-assess-empty .history-side-card-header {
  min-height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
}

.history-assess-empty-body {
  min-height: 286px;
  padding: 18px 18px 22px;
  background: transparent;
}

.history-assess-empty-body strong {
  color: #3b1c09;
  font-size: 15px;
  font-weight: 950;
}

.history-assess-empty-body p {
  color: rgba(74, 37, 15, 0.64);
  font-size: 12px;
  font-weight: 800;
}

.history-assess-empty-body button,
.history-assess-empty-body button:hover:not(:disabled) {
  height: 32px;
  padding: 0 13px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 12px;
  font-weight: 900;
  transform: none;
  filter: none;
}

.history-assess-empty-body button:hover:not(:disabled) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.history-assess-empty-body button:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.history-page-detail :deep(.history-raw-log.setup-init-log) {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-rail) {
  position: static;
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-rail::before),
.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-rail::after) {
  display: none;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-rail img) {
  width: 34px;
  height: 34px;
  object-fit: contain;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-card) {
  min-height: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-card p) {
  margin: 0;
  color: #3b210f;
  font-size: 13px;
  line-height: 1.4;
}

.history-page-detail :deep(.history-raw-log.setup-init-log .timeline-card p b) {
  color: #6f3b1c;
}

.history-page-detail :deep(.history-raw-log.judge-message-log) {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-rail) {
  position: static;
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
}

.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-rail::before),
.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-rail::after) {
  display: none;
}

.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-rail img) {
  width: 34px;
  height: 34px;
  object-fit: contain;
}

.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-card),
.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-card:hover) {
  min-height: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.history-raw-log.judge-message-log .timeline-card p) {
  margin: 0;
  color: #3b210f;
  font-size: 13px;
  line-height: 1.45;
}

/* Compact phase header: only phase identity and a horizontal log counter. */
.phase-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  gap: 16px;
  padding: 10px 14px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 6px;
  background: #FAE9BA;
  box-shadow: inset 0 1px 0 rgba(255, 244, 205, 0.66);
}

.phase-overview-copy {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.phase-overview-copy small {
  order: 2;
  color: rgba(74, 37, 15, 0.64);
  font-size: 13px;
}

.phase-overview-copy h3 {
  order: 1;
  font-size: 18px;
}

.phase-overview-log {
  display: flex;
  align-items: center;
  gap: 4px;
  color: rgba(74, 37, 15, 0.66);
  font-size: 13px;
  font-weight: 850;
}

.phase-overview-log b {
  color: #3b1c09;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

/* Decision cards share the history-filter wood button language. */
.history-page-detail :deep(.night-action-grid) {
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 8px;
}

.history-page-detail :deep(.history-night-section) {
  padding-right: 0;
  padding-left: 0;
}

.history-page-detail :deep(.night-left) {
  padding-left: 0;
}

.history-page-detail :deep(.night-mini-card),
.history-page-detail :deep(.night-mini-card:hover),
.history-page-detail :deep(.night-mini-card.sel) {
  min-height: 76px;
  padding: 12px 14px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 7px;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  transform: none;
}

.history-page-detail :deep(.night-mini-card:hover) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.88);
}

.history-page-detail :deep(.night-mini-card.sel) {
  border-color: rgba(93, 48, 17, 0.45);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.history-page-detail :deep(.nmc-header) {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 9px;
}

.history-page-detail :deep(.nmc-role-icon) {
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  object-fit: contain;
}

.history-page-detail :deep(.nmc-confidence) {
  margin-left: auto;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 900;
  white-space: nowrap;
}

.history-page-detail :deep(.nmc-confidence.low) {
  color: #a92d25;
  background: rgba(205, 75, 60, 0.14);
}

.history-page-detail :deep(.nmc-confidence.medium) {
  color: #91630f;
  background: rgba(211, 158, 45, 0.18);
}

.history-page-detail :deep(.nmc-confidence.high) {
  color: #28743b;
  background: rgba(70, 150, 83, 0.16);
}

/* Compact ranking as clean horizontal bar chart. */
.history-side-card--assess :deep(.ma-rank-list) {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.history-side-card--assess :deep(.ma-rank-row) {
  display: grid;
  grid-template-columns: 20px 58px minmax(0, 1fr) 28px;
  grid-template-areas: "avatar player bar score";
  align-items: center;
  gap: 7px;
  width: 100%;
  min-height: 32px;
  padding: 2px 3px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-side-card--assess :deep(.ma-rank-index) {
  display: none;
}

.history-side-card--assess :deep(.ma-rank-avatar) {
  grid-area: avatar;
}

.history-side-card--assess :deep(.ma-rank-player) {
  grid-area: player;
  display: grid;
  gap: 0;
}

.history-side-card--assess :deep(.ma-rank-score) {
  grid-area: score;
}

.history-side-card--assess :deep(.ma-rank-bar) {
  grid-area: bar;
  width: 100%;
  height: 13px;
  margin: 0;
  border-radius: 4px;
  background: rgba(134, 92, 43, 0.12);
  overflow: hidden;
}

.history-side-card--assess :deep(.ma-rank-bar i) {
  height: 100%;
  border-radius: 4px;
}

.history-side-card--assess :deep(.ma-rank-bar i.role-seer) { background: #4698de; }
.history-side-card--assess :deep(.ma-rank-bar i.role-witch) { background: #9a57bd; }
.history-side-card--assess :deep(.ma-rank-bar i.role-hunter) { background: #e64b3e; }
.history-side-card--assess :deep(.ma-rank-bar i.role-guard) { background: #35c86d; }
.history-side-card--assess :deep(.ma-rank-bar i.role-white-wolf) { background: #ef7f1a; }
.history-side-card--assess :deep(.ma-rank-bar i.role-wolf) { background: #c83b30; }
.history-side-card--assess :deep(.ma-rank-bar i.role-villager) { background: #819299; }

.history-side-card--assess :deep(.ma-rank-row:hover),
.history-side-card--assess :deep(.ma-rank-row.active) {
  border: 0;
  background: transparent;
  box-shadow: none;
}

/* Review score cards: readable identity header and highlighted total score. */
.history-page-detail :deep(.review-score-grid) {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 0;
  background: transparent;
}

.history-page-detail :deep(.review-score-panel-head) {
  display: flex;
  padding: 0 0 8px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.15);
}

.history-page-detail :deep(.review-score-card) {
  min-height: 270px;
  padding: 12px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 8px;
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.history-page-detail :deep(.review-score-card:hover) {
  border-color: rgba(93, 48, 17, 0.32);
  background: rgba(255, 245, 214, 0.82);
}

.history-page-detail :deep(.review-score-card header) {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
}

.history-page-detail :deep(.review-role-icon) {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

.history-page-detail :deep(.review-player-identity) {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.history-page-detail :deep(.review-role) {
  overflow: hidden;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: #3b1c09;
  background: transparent;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-page-detail :deep(.review-seat) {
  color: rgba(74, 37, 15, 0.56);
  font-size: 11px;
  font-weight: 850;
  white-space: nowrap;
}

.history-page-detail :deep(.review-overall-score) {
  display: grid;
  grid-template-columns: auto auto;
  align-items: baseline;
  gap: 5px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: #7f2430;
  background: transparent;
  box-shadow: none;
}

.history-page-detail :deep(.review-overall-score small) {
  font-size: 14px;
  font-weight: 950;
}

.history-page-detail :deep(.review-overall-score b) {
  color: inherit;
  font-size: 14px;
  font-weight: 950;
  line-height: 1;
}

.history-page-detail :deep(.review-score-metrics span) {
  border: 1px solid rgba(93, 48, 17, 0.1);
  background: rgba(255, 248, 220, 0.45);
}

/* Review/archive pages scroll through the main column without a blocking footer gap. */
.history-detail-panel {
  padding-bottom: 0;
}

.detail-content.workspace-review,
.detail-content.workspace-archive {
  padding-top: 0;
  padding-bottom: 0;
}

.detail-topbar.workspace-review,
.detail-topbar.workspace-archive {
  grid-template-areas:
    "workspace"
    "context";
  grid-template-rows: auto auto;
  min-height: 0;
  row-gap: 8px;
}

.detail-topbar.workspace-review .detail-workspace-tabs,
.detail-topbar.workspace-archive .detail-workspace-tabs {
  align-items: flex-start;
}

.detail-topbar.workspace-review .detail-workspace-tabs button,
.detail-topbar.workspace-archive .detail-workspace-tabs button {
  min-height: 30px;
}

.detail-topbar.workspace-review + .detail-content,
.detail-topbar.workspace-archive + .detail-content {
  padding-top: 0;
  margin-top: 0;
}

.detail-content.workspace-review .history-page-detail,
.detail-content.workspace-archive .history-page-detail {
  padding-top: 0;
}

.history-page-detail :deep(.review-score-section) {
  margin-top: 0;
}

.history-page-detail :deep(.review-score-panel-head) {
  min-height: 28px;
  padding: 0 0 6px;
}

/* Keep nested vote-flow charts on their own visual rules inside the review report. */
.history-page-detail :deep(.archive-review-panel .vote-flow-analysis h4),
.history-page-detail :deep(.archive-review-panel .vote-round-heatmap h4) {
  margin: 0;
  padding: 0;
  border: 0;
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
}

.history-page-detail :deep(.archive-review-panel .vote-flow-analysis header),
.history-page-detail :deep(.archive-review-panel .vote-round-heatmap header) {
  min-height: 0;
  padding: 0;
  border: 0;
}

.history-page-detail :deep(.archive-review-panel .vote-heatmap-head span) {
  padding: 0 4px;
}

.detail-content.workspace-review .detail-main-column,
.detail-content.workspace-archive .detail-main-column {
  overflow-x: hidden;
  overflow-y: auto;
  padding-bottom: 0;
  scrollbar-gutter: stable;
}

.detail-content.workspace-review .history-document-panel,
.detail-content.workspace-archive .history-document-panel {
  height: auto;
  max-height: none;
  overflow: visible;
  padding: 0;
}

/* Phase review workbench */
.history-page-detail .phase-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
  gap: 14px;
  align-items: stretch;
  padding: 14px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 0;
  background: rgba(250, 233, 186, 0.9);
  box-shadow: inset 0 1px 0 rgba(255, 244, 205, 0.72);
}

.history-page-detail .phase-overview-copy {
  display: grid;
  align-content: center;
  gap: 6px;
  min-width: 0;
}

.history-page-detail .phase-overview-copy h3 {
  overflow: hidden;
  margin: 0;
  color: #3b1c09;
  font-size: 18px;
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-page-detail .phase-overview-copy p {
  margin: 0;
  color: rgba(74, 37, 15, 0.72);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.phase-focus-clear {
  justify-self: start;
  height: 28px;
  padding: 0 10px;
  border: 1px solid rgba(93, 48, 17, 0.22);
  border-radius: 0;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.74);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.phase-overview-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 0;
  background: rgba(93, 48, 17, 0.12);
}

.phase-overview-stats span {
  display: grid;
  align-content: center;
  gap: 5px;
  min-width: 0;
  min-height: 54px;
  padding: 8px 9px;
  border: 0;
  border-radius: 0;
  background: rgba(255, 252, 245, 0.62);
}

.phase-overview-stats small {
  overflow: hidden;
  color: rgba(74, 37, 15, 0.58);
  font-size: 10px;
  font-weight: 950;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-overview-stats b {
  color: #3b1c09;
  font-size: 17px;
  font-weight: 950;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.phase-evidence-panel {
  display: grid;
  gap: 8px;
  padding: 10px 14px 12px;
  border-top: 1px solid rgba(93, 48, 17, 0.14);
  background: rgba(255, 252, 245, 0.34);
}

.phase-evidence-panel.is-expanded {
  gap: 10px;
}

.phase-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.phase-section-head h4 {
  margin: 0;
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
}

.phase-section-head span {
  overflow: hidden;
  color: rgba(74, 37, 15, 0.62);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-evidence-head {
  align-items: stretch;
}

.phase-evidence-toggle {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
  min-height: 38px;
  padding: 7px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.52);
  box-shadow: inset 0 1px 0 rgba(255, 252, 245, 0.54);
  text-align: left;
  cursor: pointer;
}

.phase-evidence-toggle:hover {
  border-color: rgba(127, 36, 48, 0.24);
  background: rgba(255, 239, 194, 0.7);
}

.phase-evidence-heading {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.phase-section-head .phase-evidence-toggle span,
.phase-section-head .phase-evidence-toggle small {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}

.phase-evidence-title {
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
  line-height: 1.15;
}

.phase-evidence-heading small {
  color: rgba(74, 37, 15, 0.6);
  font-size: 11px;
  font-weight: 900;
  line-height: 1.2;
}

.phase-evidence-meta {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  color: rgba(74, 37, 15, 0.66);
  font-size: 12px;
  font-weight: 900;
}

.phase-evidence-meta span {
  max-width: 180px;
  overflow: hidden !important;
  color: inherit;
  font-size: inherit;
  font-weight: inherit;
  line-height: 1.2;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}

.phase-evidence-meta i {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-right: 2px solid rgba(59, 28, 9, 0.7);
  border-bottom: 2px solid rgba(59, 28, 9, 0.7);
  transform: rotate(45deg) translateY(-1px);
  transition: transform 0.16s ease;
}

.phase-evidence-toggle[aria-expanded='true'] .phase-evidence-meta i {
  transform: rotate(225deg) translateY(-1px);
}

.phase-evidence-brief {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.1);
  border-top: 0;
  color: rgba(59, 28, 9, 0.74);
  background: rgba(255, 252, 245, 0.42);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.phase-evidence-brief span {
  overflow-wrap: anywhere;
}

.phase-evidence-body {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.phase-vote-layout,
.phase-night-matrix,
.phase-speech-timeline,
.phase-generic-evidence {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.phase-vote-rank {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.phase-vote-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.72fr) minmax(0, 1fr) 46px;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 42px;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 239, 194, 0.46);
}

.phase-vote-row[data-tone="lead"] {
  border-color: rgba(127, 36, 48, 0.26);
  background: rgba(255, 228, 180, 0.64);
}

.phase-vote-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.phase-vote-main b,
.phase-matrix-row b,
.phase-speech-id b {
  color: #3b1c09;
  font-size: 13px;
  font-weight: 950;
}

.phase-vote-main span,
.phase-matrix-row span,
.phase-speech-id small {
  overflow: hidden;
  color: rgba(74, 37, 15, 0.62);
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-vote-track {
  overflow: hidden;
  height: 10px;
  border-radius: 0;
  background: rgba(93, 48, 17, 0.1);
}

.phase-vote-track i {
  display: block;
  height: 100%;
  min-width: 4px;
  background: linear-gradient(90deg, #7f2430, #d49a32);
}

.phase-vote-row strong,
.phase-matrix-row strong {
  color: #7f2430;
  font-size: 12px;
  font-weight: 950;
  text-align: right;
  white-space: nowrap;
}

.phase-alert-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.phase-alert-list span {
  padding: 5px 8px;
  border: 1px solid rgba(126, 77, 21, 0.18);
  border-radius: 0;
  color: #7e4d15;
  background: rgba(217, 164, 65, 0.12);
  font-size: 12px;
  font-weight: 850;
}

.phase-alert-list span[data-tone="info"] {
  color: #2e6d73;
  background: rgba(46, 109, 115, 0.1);
}

.phase-matrix-head,
.phase-matrix-row {
  display: grid;
  grid-template-columns: 74px 86px 74px minmax(0, 1fr) 46px;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.phase-matrix-head {
  min-height: 28px;
  padding: 0 10px;
  color: rgba(74, 37, 15, 0.56);
  font-size: 10px;
  font-weight: 950;
}

.phase-matrix-row {
  min-height: 42px;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 239, 194, 0.46);
}

.phase-matrix-row p,
.phase-speech-row p {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: rgba(59, 28, 9, 0.82);
  font-size: 12px;
  font-weight: 750;
  line-height: 1.45;
}

.phase-speech-row {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr) minmax(110px, auto);
  gap: 10px;
  align-items: start;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 239, 194, 0.46);
}

.phase-speech-id {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.phase-speech-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}

.phase-speech-tags span,
.phase-speech-tags em {
  padding: 3px 6px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 0;
  color: #70401e;
  background: rgba(255, 252, 245, 0.54);
  font-size: 10px;
  font-style: normal;
  font-weight: 900;
  line-height: 1.1;
  white-space: nowrap;
}

.phase-generic-evidence {
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
}

.phase-generic-evidence span {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  background: rgba(255, 239, 194, 0.46);
}

.phase-generic-evidence small {
  color: rgba(74, 37, 15, 0.56);
  font-size: 10px;
  font-weight: 950;
}

.phase-generic-evidence b {
  color: #3b1c09;
  font-size: 16px;
  font-weight: 950;
}

.phase-empty-state {
  padding: 14px;
  border: 1px dashed rgba(93, 48, 17, 0.22);
  color: rgba(74, 37, 15, 0.62);
  background: rgba(255, 252, 245, 0.4);
  font-size: 13px;
  font-weight: 850;
  text-align: center;
}

.phase-decision-panel {
  display: grid;
  gap: 10px;
  padding: 12px 14px 14px;
  border-top: 1px solid rgba(93, 48, 17, 0.14);
  background: rgba(255, 248, 232, 0.5);
}

.phase-decision-panel :deep(.history-night-section) {
  display: grid;
  gap: 10px;
  padding: 0;
  border-top: 0;
  background: transparent;
}

.phase-decision-panel :deep(.night-result-bar) {
  margin: 0;
  border-radius: 0;
  background: rgba(255, 239, 194, 0.56);
}

.phase-decision-panel :deep(.night-two-col) {
  height: auto;
  min-height: 280px;
  max-height: min(560px, calc(100vh - 330px));
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.36);
}

.phase-decision-panel :deep(.night-left) {
  padding: 10px 8px 10px 10px;
  border-right: 1px solid rgba(93, 48, 17, 0.12);
}

.phase-decision-panel :deep(.night-action-grid) {
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 8px;
}

.phase-decision-panel :deep(.night-mini-card),
.phase-decision-panel :deep(.night-mini-card:hover),
.phase-decision-panel :deep(.night-mini-card.sel) {
  border-radius: 0;
}

.phase-decision-panel :deep(.night-right) {
  min-width: 0;
  border-left: 0;
  background: rgba(255, 252, 245, 0.42);
}

.phase-decision-panel :deep(.sheriff-bar-chart) {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.42);
}

.phase-decision-panel :deep(.history-lastwords-section) {
  padding: 0;
  border-top: 0;
}

.phase-decision-panel :deep(.last-word-card) {
  border-radius: 0;
  background: rgba(255, 239, 194, 0.46);
}

.phase-detail-empty {
  margin: 0;
}

.history-page-detail details.history-raw-section {
  display: grid;
  margin-top: 0;
  border-top: 1px solid rgba(93, 48, 17, 0.14);
}

.history-page-detail details.history-raw-section > summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 14px;
  color: #3b1c09;
  background: rgba(255, 239, 194, 0.36);
  font-size: 13px;
  font-weight: 950;
  cursor: pointer;
}

.history-page-detail details.history-raw-section > summary b {
  margin-left: auto;
  color: #7f2430;
  font-size: 12px;
  font-weight: 950;
}

.phase-load-more-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 46px;
  padding: 8px 14px;
  border-top: 1px solid rgba(93, 48, 17, 0.14);
  background: rgba(255, 239, 194, 0.36);
}

.phase-load-more-strip span {
  min-width: 0;
  overflow: hidden;
  color: rgba(74, 37, 15, 0.68);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.phase-load-more-strip button {
  flex: 0 0 auto;
  height: 30px;
  padding: 0 12px;
  border: 1px solid rgba(93, 48, 17, 0.22);
  border-radius: 0;
  color: #3b1c09;
  background: rgba(255, 252, 245, 0.58);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.phase-load-more-strip button:hover:not(:disabled) {
  border-color: rgba(127, 36, 48, 0.28);
  background: rgba(255, 245, 214, 0.82);
}

.phase-load-more-strip button:disabled {
  cursor: default;
  opacity: 0.55;
}

.raw-log-filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 14px 0;
}

.raw-log-filter-tabs button {
  height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 0;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.58);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.raw-log-filter-tabs button.active {
  color: #3b1c09;
  background: rgba(224, 184, 111, 0.66);
}

.raw-log-filter-tabs small {
  margin-left: 5px;
  color: inherit;
  font-size: 10px;
}

@media (max-width: 920px) {
  .history-page-detail .phase-overview,
  .phase-speech-row,
  .phase-matrix-head,
  .phase-matrix-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .phase-overview-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .phase-evidence-toggle {
    grid-template-columns: minmax(0, 1fr);
    gap: 5px;
  }

  .phase-evidence-meta {
    justify-content: space-between;
    width: 100%;
  }

  .phase-evidence-meta span {
    max-width: none;
  }

  .phase-vote-row {
    grid-template-columns: minmax(0, 1fr) 46px;
  }

  .phase-vote-track {
    grid-column: 1 / -1;
  }

  .phase-speech-tags {
    justify-content: flex-start;
  }

  .phase-decision-panel :deep(.night-two-col) {
    grid-template-columns: minmax(0, 1fr);
    max-height: none;
  }

  .phase-decision-panel :deep(.night-left) {
    border-right: 0;
    border-bottom: 1px solid rgba(93, 48, 17, 0.12);
  }
}
</style>
