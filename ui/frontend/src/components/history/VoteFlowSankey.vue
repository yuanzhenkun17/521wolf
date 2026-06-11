<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch, type PropType } from 'vue'
import * as echarts from 'echarts/core'
import { HeatmapChart, SankeyChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'

echarts.use([SankeyChart, HeatmapChart, CanvasRenderer, GridComponent, TooltipComponent, VisualMapComponent])

type SeatId = string | number
type HeatmapScore = number | '-'
type HeatmapDataPoint = [number, number, HeatmapScore]

interface DecisionLike {
  action?: unknown
  action_type?: unknown
  actor_id?: unknown
  candidates?: unknown
  confidence?: unknown
  day?: unknown
  message?: unknown
  phase?: unknown
  player_id?: unknown
  private_reasoning?: unknown
  public_summary?: unknown
  reason?: unknown
  selected_target?: unknown
  target_id?: unknown
}

interface PlayerLike {
  id?: unknown
}

interface FilterItem {
  key: string
  label: string
}

interface PhaseRound {
  key: string
  label: string
}

interface HeatmapCell {
  key: string
  rows: DecisionLike[]
  score: HeatmapScore
  empty: boolean
}

interface HeatmapRow {
  playerId: string
  cells: HeatmapCell[]
}

interface SankeyNode {
  name: string
  label: { position: 'left' | 'right' }
  itemStyle: { color: string }
}

interface SankeyAccumulatedLink {
  source: string
  target: string
  value: number
  sourceId: string
  targetId: string
  actions: Set<string>
}

interface SankeyRow {
  sourceId: SeatId
  targetId: SeatId
  action: string
}

interface ChartFormatterParam {
  data?: unknown
  dataType?: string
  name?: unknown
  value?: unknown
}

function formatterParam(params: ChartFormatterParam | ChartFormatterParam[]): ChartFormatterParam {
  return Array.isArray(params) ? (params[0] || {}) : params
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function firstPresent(...values: unknown[]) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== '') return value
  }
  return undefined
}

function nestedRecord(decision: DecisionLike, key: string) {
  const value = (decision as Record<string, unknown>)?.[key]
  return isRecord(value) ? value : {}
}

const props = defineProps({
  decisions: { type: Array as PropType<DecisionLike[]>, default: () => [] },
  players: { type: Array as PropType<PlayerLike[]>, default: () => [] }
})

const chartEl = ref<HTMLElement | null>(null)
const heatmapEl = ref<HTMLElement | null>(null)
const activeKey = ref('all')
let chart: ReturnType<typeof echarts.init> | null = null
let heatmapChart: ReturnType<typeof echarts.init> | null = null
let resizeObserver: ResizeObserver | null = null
let heatmapResizeObserver: ResizeObserver | null = null

const VOTE_ACTIONS = new Set(['sheriff_vote', 'exile_vote', 'pk_vote', 'vote'])
const NIGHT_ACTIONS = new Set(['kill', 'werewolf_kill', 'guard', 'guard_protect', 'inspect', 'seer_check', 'poison', 'witch_act', 'antidote', 'shoot', 'hunter_shoot'])
const SPEECH_ACTIONS = new Set(['speech_order', 'speak', 'speech', 'sheriff_speak', 'last_word'])
const SHERIFF_ACTIONS = new Set(['sheriff_speak', 'sheriff_run', 'sheriff_elect', 'sheriff_withdraw', 'sheriff_vote'])
const END_ACTIONS = new Set(['game_over', 'result', 'finished', 'end', 'ended'])
const INFO_KEYWORDS = ['查验', '验了', '查杀', '金水', '银水', '好人', '狼人', '预言家', '女巫', '守卫', 'checked', 'seer', 'inspect', 'wolf']
const NODE_COLORS = [
  '#3dc5e7',
  '#8bc77b',
  '#feda66',
  '#6d62e4',
  '#5AAEF4',
  '#fb7f10',
  '#9580ff',
  '#2aa12d',
  '#ef6a8a',
  '#48b6a5',
  '#d88a38',
  '#7b91d1'
]

function actionType(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  return String(firstPresent(
    decision?.action,
    decision?.action_type,
    (decision as Record<string, unknown>)?.type,
    (decision as Record<string, unknown>)?.event_type,
    payload.action,
    payload.action_type,
    metadata.action
  ) || '')
}

function voteAction(decision: DecisionLike) {
  return actionType(decision)
}

function voteDay(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  const day = Number(firstPresent(
    decision?.day,
    (decision as Record<string, unknown>)?.round,
    payload.day,
    payload.round,
    metadata.day
  ))
  return Number.isFinite(day) && day > 0 ? day : 1
}

function voterId(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  return firstPresent(
    decision?.actor_id,
    (decision as Record<string, unknown>)?.actor,
    decision?.player_id,
    (decision as Record<string, unknown>)?.playerId,
    (decision as Record<string, unknown>)?.player_seat,
    (decision as Record<string, unknown>)?.seat,
    payload.actor_id,
    payload.player_id,
    metadata.actor_id
  )
}

function targetId(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  const choice = nestedRecord(decision, 'choice')
  return firstPresent(
    decision?.target_id,
    (decision as Record<string, unknown>)?.target,
    (decision as Record<string, unknown>)?.targetId,
    (decision as Record<string, unknown>)?.target_seat,
    decision?.selected_target,
    (decision as Record<string, unknown>)?.selectedTarget,
    payload.target_id,
    payload.selected_target,
    metadata.target_id,
    choice.target,
    choice.target_id
  )
}

const votes = computed(() =>
  props.decisions.filter((decision) =>
    VOTE_ACTIONS.has(voteAction(decision)) && voterId(decision) != null && targetId(decision) != null
  )
)

const behaviorDecisions = computed(() =>
  props.decisions.filter((decision) => actorId(decision) != null && phaseKeyForDecision(decision))
)

const filters = computed(() => {
  const items: FilterItem[] = [{ key: 'all', label: '全部' }]
  if (votes.value.some((vote) => voteAction(vote) === 'sheriff_vote')) {
    items.push({ key: 'sheriff', label: '警长竞选' })
  }
  const exileDays = [...new Set(
    votes.value
      .filter((vote) => ['exile_vote', 'vote'].includes(voteAction(vote)))
      .map(voteDay)
  )].sort((a, b) => a - b)
  exileDays.forEach((day) => items.push({ key: `exile-${day}`, label: `第${day}天放逐` }))
  if (votes.value.some((vote) => voteAction(vote) === 'pk_vote')) {
    items.push({ key: 'pk', label: 'PK投票' })
  }
  return items
})

const selectedVotes = computed(() => {
  if (activeKey.value === 'all') return votes.value
  if (activeKey.value === 'sheriff') return votes.value.filter((vote) => voteAction(vote) === 'sheriff_vote')
  if (activeKey.value === 'pk') return votes.value.filter((vote) => voteAction(vote) === 'pk_vote')
  if (activeKey.value.startsWith('exile-')) {
    const day = Number(activeKey.value.slice('exile-'.length))
    return votes.value.filter((vote) => ['exile_vote', 'vote'].includes(voteAction(vote)) && voteDay(vote) === day)
  }
  return votes.value
})

const voteRounds = computed(() => filters.value.filter((item) => item.key !== 'all'))

const actionFlowRows = computed(() =>
  behaviorDecisions.value.filter((decision) =>
    !VOTE_ACTIONS.has(actionType(decision)) && actorId(decision) != null && targetId(decision) != null
  )
)

const sankeyRows = computed<SankeyRow[]>(() => {
  if (selectedVotes.value.length) {
    return selectedVotes.value.map((decision) => ({
      sourceId: voterId(decision) as SeatId,
      targetId: targetId(decision) as SeatId,
      action: actionType(decision)
    }))
  }
  return actionFlowRows.value.map((decision) => ({
    sourceId: actorId(decision) as SeatId,
    targetId: targetId(decision) as SeatId,
    action: actionType(decision)
  }))
})

const hasSankeyFlow = computed(() => sankeyRows.value.length > 0)

const sankeyTitle = computed(() => votes.value.length ? '投票流向分析' : '行动流向分析')

const sankeyUnit = computed(() => votes.value.length ? '票' : '次')

const heatmapPlayers = computed(() => {
  const ids = new Set(props.players.map((player) => player?.id).filter((id) => id != null).map(String))
  behaviorDecisions.value.forEach((decision) => ids.add(String(actorId(decision))))
  votes.value.forEach((vote) => ids.add(String(voterId(vote))))
  return [...ids].sort((a, b) => Number(a) - Number(b))
})

function roundVotes(roundKey: string) {
  if (roundKey === 'sheriff') return votes.value.filter((vote) => voteAction(vote) === 'sheriff_vote')
  if (roundKey === 'pk') return votes.value.filter((vote) => voteAction(vote) === 'pk_vote')
  if (roundKey.startsWith('exile-')) {
    const day = Number(roundKey.slice('exile-'.length))
    return votes.value.filter((vote) => ['exile_vote', 'vote'].includes(voteAction(vote)) && voteDay(vote) === day)
  }
  return votes.value
}

const heatmapRows = computed<HeatmapRow[]>(() =>
  heatmapPlayers.value.map((playerId) => ({
    playerId,
    cells: phaseRounds.value.map((round) => {
      const rows = behaviorDecisions.value.filter((decision) =>
        String(actorId(decision)) === playerId && phaseKeyForDecision(decision) === round.key
      )
      const score = phaseScore(rows, round.key)
      return {
        key: `${playerId}-${round.key}`,
        rows,
        score,
        empty: !rows.length
      }
    })
  }))
)

const heatmapData = computed<HeatmapDataPoint[]>(() =>
  heatmapRows.value.flatMap((row, yIndex) =>
    row.cells.map((cell, xIndex): HeatmapDataPoint => [
      xIndex,
      yIndex,
      cell.empty ? '-' : cell.score
    ])
  )
)

function heatmapCellRows(xIndex: number, yIndex: number) {
  return heatmapRows.value[yIndex]?.cells?.[xIndex]?.rows || []
}

const heatmapValueRange = computed(() => {
  const scores = heatmapData.value
    .map((item) => Number(item[2]))
    .filter((value) => Number.isFinite(value))
  if (!scores.length) return { min: 0, max: 100 }
  return { min: 0, max: 100 }
})

const heatmapHeight = computed(() =>
  Math.max(190, Math.min(420, 82 + heatmapPlayers.value.length * 26))
)
const heatmapWidth = computed(() =>
  Math.max(760, phaseRounds.value.length * 132)
)

function seatLabel(id: unknown) {
  return `${id}号`
}

function actorId(decision: DecisionLike) {
  return voterId(decision)
}

function decisionText(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  return [
    decision?.public_summary,
    (decision as Record<string, unknown>)?.summary,
    (decision as Record<string, unknown>)?.public_text,
    decision?.private_reasoning,
    decision?.reason,
    decision?.message,
    payload.public_summary,
    payload.message,
    payload.reason,
    metadata.reason
  ].filter(Boolean).map(String).join(' ')
}

function confidenceScore(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  const value = Number(firstPresent(decision?.confidence, payload.confidence, metadata.confidence))
  if (!Number.isFinite(value)) return 70
  if (value <= 1) return Math.round(value * 100)
  return Math.max(0, Math.min(Math.round(value), 100))
}

function candidatesCount(decision: DecisionLike) {
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  const candidates = firstPresent(decision?.candidates, payload.candidates, metadata.candidates)
  return Array.isArray(candidates) ? candidates.length : 0
}

function phaseKeyForDecision(decision: DecisionLike) {
  const action = actionType(decision)
  const payload = nestedRecord(decision, 'payload')
  const metadata = nestedRecord(decision, 'metadata')
  const phase = String(firstPresent(
    decision?.phase,
    (decision as Record<string, unknown>)?.stage,
    (decision as Record<string, unknown>)?.round_phase,
    payload.phase,
    metadata.phase
  ) || '').toLowerCase()
  const day = voteDay(decision)
  if (phase === 'setup' || action.includes('setup') || action.includes('role_assign')) return 'setup'
  if (END_ACTIONS.has(action) || ['result', 'finished', 'ended', 'end'].includes(phase)) return 'end'
  if (SHERIFF_ACTIONS.has(action) || ['sheriff', 'sheriff_election', 'sheriff_vote', 'sheriff_result'].includes(phase)) return 'sheriff'
  if (NIGHT_ACTIONS.has(action) || phase === 'night') return `night-${day}`
  if (SPEECH_ACTIONS.has(action) || ['speech', 'day_speech', 'pk_speak'].includes(phase)) return `speech-${day}`
  if (VOTE_ACTIONS.has(action) || ['vote', 'exile_vote', 'pk_vote'].includes(phase)) return `vote-${day}`
  return ''
}

const phaseRounds = computed<PhaseRound[]>(() => {
  const days = new Set([1])
  behaviorDecisions.value.forEach((decision) => {
    const day = voteDay(decision)
    if (day > 0) days.add(day)
  })
  const sortedDays = [...days].sort((a, b) => a - b)
  const rounds: PhaseRound[] = []
  sortedDays.forEach((day) => {
    rounds.push({ key: `night-${day}`, label: `第${day}夜` })
    if (day === 1) rounds.push({ key: 'sheriff', label: '警长竞选' })
    rounds.push({ key: `speech-${day}`, label: `第${day}天发言` })
    rounds.push({ key: `vote-${day}`, label: `第${day}天投票` })
  })
  return rounds
})

const voteConsensusByPhase = computed(() => {
  const map = new Map<string, string>()
  for (const round of phaseRounds.value) {
    if (!round.key.startsWith('vote-') && round.key !== 'sheriff') continue
    const rows = behaviorDecisions.value.filter((decision) => {
      const action = actionType(decision)
      return phaseKeyForDecision(decision) === round.key && VOTE_ACTIONS.has(action) && targetId(decision) != null
    })
    const tally = new Map<string, number>()
    rows.forEach((decision) => {
      const target = String(targetId(decision))
      tally.set(target, (tally.get(target) || 0) + 1)
    })
    const consensus = [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    if (consensus) map.set(round.key, consensus)
  }
  return map
})

function phaseScore(rows: DecisionLike[], phaseKey: string): HeatmapScore {
  if (!rows.length) return '-'
  const textLength = rows.reduce((sum, row) => sum + decisionText(row).length, 0)
  const avgConfidence = rows.reduce((sum, row) => sum + confidenceScore(row), 0) / rows.length
  const withTarget = rows.filter((row) => targetId(row) != null).length
  const candidateCount = rows.reduce((sum, row) => sum + candidatesCount(row), 0)
  let score = 18
  score += Math.min(rows.length * 12, 28)
  score += Math.round(avgConfidence * 0.24)
  score += Math.min(Math.floor(textLength / 18), 18)
  score += Math.min(withTarget * 5, 12)
  score += Math.min(candidateCount, 8)

  if (phaseKey.startsWith('speech-') || phaseKey === 'sheriff') {
    const text = rows.map(decisionText).join(' ').toLowerCase()
    const infoHits = INFO_KEYWORDS.filter((keyword) => text.includes(keyword.toLowerCase())).length
    score += Math.min(infoHits * 4, 16)
  }

  if (phaseKey.startsWith('vote-') || phaseKey === 'sheriff') {
    const consensus = voteConsensusByPhase.value.get(phaseKey)
    rows.forEach((row) => {
      if (!VOTE_ACTIONS.has(actionType(row))) return
      score += consensus && String(targetId(row)) === consensus ? 14 : 5
    })
  }

  if (phaseKey.startsWith('night-')) {
    rows.forEach((row) => {
      const action = actionType(row)
      if (['seer_check', 'inspect', 'hunter_shoot', 'shoot', 'poison'].includes(action)) score += 12
      else if (['guard', 'guard_protect', 'antidote', 'witch_act'].includes(action)) score += 9
      else if (['kill', 'werewolf_kill'].includes(action)) score += 8
      else score += 5
    })
  }

  if (phaseKey === 'setup' || phaseKey === 'end') score = Math.min(score, 82)
  return Math.max(0, Math.min(100, Math.round(score)))
}

function seatColor(id: unknown) {
  const index = Math.max(Number(id) - 1, 0)
  return NODE_COLORS[index % NODE_COLORS.length]
}

function sankeyData() {
  const sources = new Set<string>()
  const targets = new Set<string>()
  const links = new Map<string, SankeyAccumulatedLink>()

  sankeyRows.value.forEach((row) => {
    const sourceId = String(row.sourceId)
    const targetIdValue = String(row.targetId)
    const source = `source:${sourceId}`
    const target = `target:${targetIdValue}`
    sources.add(sourceId)
    targets.add(targetIdValue)
    const key = `${source}|${target}`
    const existing = links.get(key)
    if (existing) {
      existing.value += 1
      if (row.action) existing.actions.add(row.action)
    } else {
      links.set(key, {
        source,
        target,
        value: 1,
        sourceId,
        targetId: targetIdValue,
        actions: new Set([row.action].filter(Boolean))
      })
    }
  })

  const sortSeats = (a: string, b: string) => Number(a) - Number(b)
  return {
    data: [
      ...[...sources].sort(sortSeats).map((id) => ({
        name: `source:${id}`,
        label: { position: 'right' },
        itemStyle: { color: seatColor(id) }
      })),
      ...[...targets].sort(sortSeats).map((id) => ({
        name: `target:${id}`,
        label: { position: 'left' },
        itemStyle: { color: seatColor(id) }
      }))
    ],
    links: [...links.values()].map((link) => ({
      source: link.source,
      target: link.target,
      value: link.value,
      actions: [...link.actions],
      lineStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: seatColor(link.sourceId) },
          { offset: 1, color: seatColor(link.targetId) }
        ])
      }
    }))
  }
}

function renderChart() {
  if (!(chartEl.value instanceof HTMLElement)) return
  if (!chart) chart = echarts.init(chartEl.value)
  const { data, links } = sankeyData()
  chart.setOption({
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove',
      formatter(params: ChartFormatterParam | ChartFormatterParam[]) {
        const item = formatterParam(params)
        if (item.dataType === 'edge' && isRecord(item.data)) {
          const source = String(item.data.source).split(':')[1]
          const target = String(item.data.target).split(':')[1]
          const actions = Array.isArray(item.data.actions) && item.data.actions.length
            ? `<br/>行为：${item.data.actions.join('、')}`
            : ''
          return `${seatLabel(source)} → ${seatLabel(target)}：${item.data.value}${sankeyUnit.value}${actions}`
        }
        return seatLabel(String(item.name).split(':')[1])
      }
    },
    series: [{
      type: 'sankey',
      left: 4,
      right: 8,
      top: 22,
      bottom: 16,
      nodeWidth: 18,
      nodeGap: 18,
      layoutIterations: 64,
      data,
      links,
      label: {
        color: 'rgba(59, 28, 9, 0.78)',
        fontSize: 12,
        fontWeight: 700,
        formatter: ({ name }: { name: unknown }) => seatLabel(String(name).split(':')[1])
      },
      itemStyle: {
        borderWidth: 0,
        borderColor: '#fff'
      },
      lineStyle: {
        color: 'source',
        opacity: 0.48,
        curveness: 0.5
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { opacity: 0.65 }
      }
    }]
  }, true)
}

function renderHeatmap() {
  if (!(heatmapEl.value instanceof HTMLElement)) return
  if (!heatmapChart) heatmapChart = echarts.init(heatmapEl.value)
  const rounds = phaseRounds.value.map((round) => round.label)
  const players = heatmapPlayers.value.map(seatLabel)
  const range = heatmapValueRange.value
  heatmapChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter(params: ChartFormatterParam | ChartFormatterParam[]) {
        const item = formatterParam(params)
        const value = Array.isArray(item.value) ? item.value : []
        const xIndex = Number(value[0])
        const yIndex = Number(value[1])
        const round = rounds[xIndex] || ''
        const player = players[yIndex] || ''
        const rows = heatmapCellRows(xIndex, yIndex)
        if (!rows.length) return `${player} · ${round}<br/>暂无行为记录`
        const score = Number(value[2])
        const actions = rows.map((row) => actionType(row)).filter(Boolean)
        return [
          `${player} · ${round}`,
          `评分：${Number.isFinite(score) ? score : '-'}`,
          `行为：${actions.join('、') || '未知'}`
        ].join('<br/>')
      }
    },
    grid: {
      left: 54,
      right: 78,
      top: 26,
      bottom: rounds.length > 8 ? 58 : 34,
      containLabel: false
    },
    xAxis: {
      type: 'category',
      data: rounds,
      axisTick: { show: true },
      axisLine: { show: true, lineStyle: { color: 'rgba(59, 28, 9, 0.56)' } },
      axisLabel: {
        color: 'rgba(59, 28, 9, 0.76)',
        fontSize: 11,
        fontWeight: 800,
        margin: 12,
        rotate: rounds.length > 8 ? 24 : 0
      },
      splitArea: { show: false }
    },
    yAxis: {
      type: 'category',
      data: players,
      axisTick: { show: false },
      axisLine: { show: true, lineStyle: { color: 'rgba(59, 28, 9, 0.56)' } },
      axisLabel: {
        color: 'rgba(59, 28, 9, 0.78)',
        fontSize: 11,
        fontWeight: 900
      },
      splitArea: { show: false },
      splitLine: {
        show: false
      }
    },
    visualMap: {
      min: range.min,
      max: range.max,
      dimension: 2,
      calculable: true,
      orient: 'vertical',
      right: 4,
      top: 'middle',
      itemHeight: 118,
      itemWidth: 12,
      text: ['高分', '低分'],
      textStyle: {
        color: 'rgba(59, 28, 9, 0.62)',
        fontSize: 10,
        fontWeight: 800
      },
      inRange: {
        color: ['#2aa12d', '#feda66', '#c83b30']
      },
      outOfRange: {
        color: ['rgba(255, 248, 220, 0.38)']
      }
    },
    series: [{
      name: '阶段评分',
      type: 'heatmap',
      data: heatmapData.value,
      encode: {
        x: 0,
        y: 1,
        value: 2
      },
      label: {
        show: false
      },
      itemStyle: {
        borderWidth: 0
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowColor: 'rgba(59, 28, 9, 0.34)'
        }
      }
    }]
  }, true)
}

function syncChartElement(element: HTMLElement | null) {
  resizeObserver?.disconnect()
  resizeObserver = null

  if (!(element instanceof HTMLElement)) {
    chart?.dispose()
    chart = null
    return
  }

  renderChart()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(element)
}

function syncHeatmapElement(element: HTMLElement | null) {
  heatmapResizeObserver?.disconnect()
  heatmapResizeObserver = null

  if (!(element instanceof HTMLElement)) {
    heatmapChart?.dispose()
    heatmapChart = null
    return
  }

  renderHeatmap()
  heatmapResizeObserver = new ResizeObserver(() => heatmapChart?.resize())
  heatmapResizeObserver.observe(element)
}

watch(filters, (items) => {
  if (!items.some((item) => item.key === activeKey.value)) activeKey.value = 'all'
})
watch([sankeyRows, activeKey], () => nextTick(renderChart), { deep: true })
watch([heatmapData, phaseRounds, heatmapPlayers], () => nextTick(renderHeatmap), { deep: true })
watch(chartEl, syncChartElement, { flush: 'post' })
watch(heatmapEl, syncHeatmapElement, { flush: 'post' })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  heatmapResizeObserver?.disconnect()
  chart?.dispose()
  heatmapChart?.dispose()
  chart = null
  heatmapChart = null
})
</script>

<template>
  <section v-if="hasSankeyFlow" class="vote-flow-analysis" aria-label="玩家行动流向图">
    <header>
      <h4>{{ sankeyTitle }}</h4>
    </header>
    <div class="vote-chart-body">
      <nav v-if="votes.length" aria-label="投票轮次筛选">
        <button
          v-for="item in filters"
          :key="item.key"
          type="button"
          :class="{ active: activeKey === item.key }"
          @click="activeKey = item.key"
        >
          {{ item.label }}
        </button>
      </nav>
      <div ref="chartEl" class="vote-flow-chart" role="img" :aria-label="`${sankeyTitle}桑基图`"></div>
    </div>
  </section>

  <section
    v-if="heatmapRows.length"
    class="vote-round-heatmap"
    aria-label="玩家回合投票热力图"
  >
    <header>
      <h4>玩家 × 回合热力图</h4>
    </header>
    <div class="vote-chart-body">
      <div ref="heatmapEl" class="vote-heatmap-chart" :style="{ height: heatmapHeight + 'px', minWidth: heatmapWidth + 'px' }" role="img" aria-label="玩家回合投票热力图"></div>
    </div>
  </section>
</template>

<style scoped>
.vote-flow-analysis,
.vote-round-heatmap {
  display: grid;
  grid-template-rows: auto auto;
  gap: 0;
  margin-top: 12px;
  border: 1px solid var(--log-border, rgba(93, 48, 17, 0.18));
  border-radius: 0;
  background: var(--log-surface, rgba(255, 252, 245, 0.42));
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  overflow: hidden;
}

.vote-flow-analysis header,
.vote-round-heatmap header {
  display: flex;
  align-items: end;
  justify-content: flex-start;
  gap: 12px;
  min-height: 0;
  padding: 8px 0 6px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.12);
  background: transparent;
}

.vote-flow-analysis h4,
.vote-round-heatmap h4 {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 15px;
  color: #3b1c09;
  font-weight: 950;
}

.vote-chart-body {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px 10px 14px;
  background: rgba(255, 252, 245, 0.32);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-color: rgba(139, 94, 52, 0.62) rgba(255, 239, 194, 0.52);
  scrollbar-width: thin;
}

.vote-round-heatmap .vote-chart-body {
  padding-bottom: 18px;
}

.vote-chart-body::-webkit-scrollbar {
  height: 12px;
}

.vote-chart-body::-webkit-scrollbar-track {
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 999px;
  background: rgba(255, 239, 194, 0.52);
}

.vote-chart-body::-webkit-scrollbar-thumb {
  border: 2px solid rgba(255, 239, 194, 0.78);
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(139, 94, 52, 0.72), rgba(93, 48, 17, 0.72));
}

.vote-chart-body::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(90deg, rgba(139, 94, 52, 0.9), rgba(93, 48, 17, 0.9));
}

.vote-flow-analysis nav {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 2px;
}

.vote-flow-analysis button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 98px;
  height: 31px;
  padding: 0 14px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  font-size: 12px;
  font-weight: 950;
  line-height: 1;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, color 0.16s ease;
}

.vote-flow-analysis button:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: #3b1c09;
  background: rgba(255, 245, 214, 0.88);
}

.vote-flow-analysis button.active {
  border-color: rgba(93, 48, 17, 0.45);
  color: #3a1b08;
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.vote-flow-chart {
  width: 100%;
  height: 340px;
  min-height: 300px;
  margin: 0;
}

.vote-heatmap-chart {
  width: 100%;
  min-height: 190px;
  margin-top: -2px;
}
</style>
