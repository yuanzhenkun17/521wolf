<script setup lang="ts">
// @ts-nocheck
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { HeatmapChart, SankeyChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'

echarts.use([SankeyChart, HeatmapChart, CanvasRenderer, GridComponent, TooltipComponent, VisualMapComponent])

const props = defineProps({
  decisions: { type: Array, default: () => [] },
  players: { type: Array, default: () => [] }
})

const chartEl = ref(null)
const heatmapEl = ref(null)
const activeKey = ref('all')
let chart = null
let heatmapChart = null
let resizeObserver = null
let heatmapResizeObserver = null

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

function actionType(decision) {
  return String(decision?.action || decision?.action_type || '')
}

function voteAction(decision) {
  return actionType(decision)
}

function voteDay(decision) {
  const day = Number(decision?.day)
  return Number.isFinite(day) && day > 0 ? day : 1
}

function voterId(decision) {
  return decision?.actor_id ?? decision?.player_id
}

function targetId(decision) {
  return decision?.target_id ?? decision?.selected_target
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
  const items = [{ key: 'all', label: '全部' }]
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

const heatmapPlayers = computed(() => {
  const ids = new Set(props.players.map((player) => player?.id).filter((id) => id != null).map(String))
  behaviorDecisions.value.forEach((decision) => ids.add(String(actorId(decision))))
  votes.value.forEach((vote) => ids.add(String(voterId(vote))))
  return [...ids].sort((a, b) => Number(a) - Number(b))
})

function roundVotes(roundKey) {
  if (roundKey === 'sheriff') return votes.value.filter((vote) => voteAction(vote) === 'sheriff_vote')
  if (roundKey === 'pk') return votes.value.filter((vote) => voteAction(vote) === 'pk_vote')
  if (roundKey.startsWith('exile-')) {
    const day = Number(roundKey.slice('exile-'.length))
    return votes.value.filter((vote) => ['exile_vote', 'vote'].includes(voteAction(vote)) && voteDay(vote) === day)
  }
  return votes.value
}

const heatmapRows = computed(() =>
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

const heatmapData = computed(() =>
  heatmapRows.value.flatMap((row, yIndex) =>
    row.cells.map((cell, xIndex) => [
      xIndex,
      yIndex,
      cell.empty ? '-' : cell.score
    ])
  )
)

function heatmapCellRows(xIndex, yIndex) {
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

const hasFlowAnalysis = computed(() => votes.value.length > 0 || (behaviorDecisions.value.length > 0 && heatmapRows.value.length > 0))

function seatLabel(id) {
  return `${id}号`
}

function actorId(decision) {
  return decision?.actor_id ?? decision?.player_id
}

function decisionText(decision) {
  return [
    decision?.public_summary,
    decision?.private_reasoning,
    decision?.reason,
    decision?.message
  ].filter(Boolean).join(' ')
}

function confidenceScore(decision) {
  const value = Number(decision?.confidence)
  if (!Number.isFinite(value)) return 70
  if (value <= 1) return Math.round(value * 100)
  return Math.max(0, Math.min(Math.round(value), 100))
}

function phaseKeyForDecision(decision) {
  const action = actionType(decision)
  const phase = String(decision?.phase || '').toLowerCase()
  const day = voteDay(decision)
  if (phase === 'setup' || action.includes('setup') || action.includes('role_assign')) return 'setup'
  if (END_ACTIONS.has(action) || ['result', 'finished', 'ended', 'end'].includes(phase)) return 'end'
  if (SHERIFF_ACTIONS.has(action) || ['sheriff', 'sheriff_vote', 'sheriff_result'].includes(phase)) return 'sheriff'
  if (NIGHT_ACTIONS.has(action) || phase === 'night') return `night-${day}`
  if (SPEECH_ACTIONS.has(action) || phase === 'speech') return `speech-${day}`
  if (VOTE_ACTIONS.has(action) || phase === 'vote') return `vote-${day}`
  return ''
}

const phaseRounds = computed(() => {
  const days = new Set([1])
  behaviorDecisions.value.forEach((decision) => {
    const day = voteDay(decision)
    if (day > 0) days.add(day)
  })
  const sortedDays = [...days].sort((a, b) => a - b)
  const rounds = [{ key: 'setup', label: '开局准备' }]
  sortedDays.forEach((day) => {
    rounds.push({ key: `night-${day}`, label: `第${day}夜` })
    if (day === 1) rounds.push({ key: 'sheriff', label: '警长竞选' })
    rounds.push({ key: `speech-${day}`, label: `第${day}天发言` })
    rounds.push({ key: `vote-${day}`, label: `第${day}天投票` })
  })
  rounds.push({ key: 'end', label: '终局' })
  return rounds
})

const voteConsensusByPhase = computed(() => {
  const map = new Map()
  for (const round of phaseRounds.value) {
    if (!round.key.startsWith('vote-') && round.key !== 'sheriff') continue
    const rows = behaviorDecisions.value.filter((decision) => {
      const action = actionType(decision)
      return phaseKeyForDecision(decision) === round.key && VOTE_ACTIONS.has(action) && targetId(decision) != null
    })
    const tally = new Map()
    rows.forEach((decision) => {
      const target = String(targetId(decision))
      tally.set(target, (tally.get(target) || 0) + 1)
    })
    const consensus = [...tally.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    if (consensus) map.set(round.key, consensus)
  }
  return map
})

function phaseScore(rows, phaseKey) {
  if (!rows.length) return '-'
  const textLength = rows.reduce((sum, row) => sum + decisionText(row).length, 0)
  const avgConfidence = rows.reduce((sum, row) => sum + confidenceScore(row), 0) / rows.length
  const withTarget = rows.filter((row) => targetId(row) != null).length
  const candidateCount = rows.reduce((sum, row) => sum + (Array.isArray(row?.candidates) ? row.candidates.length : 0), 0)
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

function seatColor(id) {
  const index = Math.max(Number(id) - 1, 0)
  return NODE_COLORS[index % NODE_COLORS.length]
}

function sankeyData() {
  const sources = new Set()
  const targets = new Set()
  const links = new Map()

  selectedVotes.value.forEach((vote) => {
    const sourceId = String(voterId(vote))
    const targetIdValue = String(targetId(vote))
    const source = `source:${sourceId}`
    const target = `target:${targetIdValue}`
    sources.add(sourceId)
    targets.add(targetIdValue)
    const key = `${source}|${target}`
    const existing = links.get(key)
    if (existing) existing.value += 1
    else links.set(key, {
      source,
      target,
      value: 1,
      sourceId,
      targetId: targetIdValue
    })
  })

  const sortSeats = (a, b) => Number(a) - Number(b)
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
  if (!(chartEl.value instanceof Element)) return
  if (!chart) chart = echarts.init(chartEl.value)
  const { data, links } = sankeyData()
  chart.setOption({
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove',
      formatter(params) {
        if (params.dataType === 'edge') {
          const source = String(params.data.source).split(':')[1]
          const target = String(params.data.target).split(':')[1]
          return `${seatLabel(source)} → ${seatLabel(target)}：${params.data.value}票`
        }
        return seatLabel(String(params.name).split(':')[1])
      }
    },
    series: [{
      type: 'sankey',
      left: 26,
      right: 26,
      top: 18,
      bottom: 16,
      nodeWidth: 14,
      nodeGap: 14,
      layoutIterations: 32,
      data,
      links,
      label: {
        color: 'rgba(59, 28, 9, 0.78)',
        fontSize: 12,
        fontWeight: 700,
        formatter: ({ name }) => seatLabel(String(name).split(':')[1])
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
  if (!(heatmapEl.value instanceof Element)) return
  if (!heatmapChart) heatmapChart = echarts.init(heatmapEl.value)
  const rounds = phaseRounds.value.map((round) => round.label)
  const players = heatmapPlayers.value.map(seatLabel)
  const range = heatmapValueRange.value
  heatmapChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter(params) {
        const value = params.value || []
        const round = rounds[value[0]] || ''
        const player = players[value[1]] || ''
        const rows = heatmapCellRows(value[0], value[1])
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

function syncChartElement(element) {
  resizeObserver?.disconnect()
  resizeObserver = null

  if (!(element instanceof Element)) {
    chart?.dispose()
    chart = null
    return
  }

  renderChart()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(element)
}

function syncHeatmapElement(element) {
  heatmapResizeObserver?.disconnect()
  heatmapResizeObserver = null

  if (!(element instanceof Element)) {
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
watch([selectedVotes, activeKey], () => nextTick(renderChart), { deep: true })
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
  <section v-if="hasFlowAnalysis" class="vote-flow-analysis">
    <template v-if="votes.length">
      <header>
        <h4>投票流向分析</h4>
        <b>{{ selectedVotes.length }} 票</b>
      </header>
      <nav aria-label="投票轮次筛选">
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
      <div ref="chartEl" class="vote-flow-chart" role="img" aria-label="投票流向桑基图"></div>
    </template>

    <section
      v-if="heatmapRows.length"
      class="vote-round-heatmap"
      :class="{ standalone: !votes.length }"
      aria-label="玩家回合投票热力图"
    >
      <header>
        <h4>玩家 × 回合热力图</h4>
      </header>
      <div ref="heatmapEl" class="vote-heatmap-chart" :style="{ height: heatmapHeight + 'px' }" role="img" aria-label="玩家回合投票热力图"></div>
    </section>
  </section>
</template>

<style scoped>
.vote-flow-analysis {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 12px 14px 10px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 8px;
  background: rgba(255, 239, 194, 0.42);
}

.vote-flow-analysis header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 12px;
  min-height: 0;
}

.vote-flow-analysis h4 {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 15px;
}

.vote-flow-analysis header b {
  color: #7f2430;
  font-size: 12px;
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
  height: 270px;
  min-height: 230px;
  margin: 0;
}

.vote-round-heatmap {
  display: grid;
  gap: 8px;
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid rgba(93, 48, 17, 0.14);
}

.vote-round-heatmap.standalone {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}

.vote-round-heatmap header {
  display: flex;
  align-items: baseline;
  justify-content: flex-start;
}

.vote-round-heatmap h4 {
  margin: 0;
  color: #3b1c09;
  font-size: 14px;
  font-weight: 950;
}

.vote-heatmap-chart {
  width: 100%;
  min-height: 190px;
  margin-top: -2px;
}
</style>
