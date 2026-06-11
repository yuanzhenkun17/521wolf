<script setup lang="ts">
import { computed, ref, type PropType } from 'vue'
import { displayRoleLabel } from './history/historyDisplay.ts'

type PlayerId = string | number

interface AssessmentPlayer {
  id: PlayerId
  seat?: PlayerId
  role?: unknown
  role_hint?: string
}

interface AssessmentScore {
  player: AssessmentPlayer
  score?: number
  speech?: number
  vote?: number
  skill?: number
  logic?: number
  team?: number
  role_score?: number
  [key: string]: unknown
}

interface AssessmentDimension {
  key: string
  label: string
}

type RoleIconImage = (player: AssessmentPlayer) => string

const props = defineProps({
  scores: { type: Array as PropType<AssessmentScore[]>, default: () => [] },
  dimension: { type: String, default: 'speech' },
  roleIconImage: Function as PropType<RoleIconImage>,
  compact: Boolean,
  selectedPlayerId: [String, Number, null]
})

const emit = defineEmits(['update:dimension', 'select-player'])

const dimensions: AssessmentDimension[] = [
  { key: 'speech', label: '发言' },
  { key: 'vote', label: '投票' },
  { key: 'skill', label: '技能' },
  { key: 'logic', label: '逻辑' },
  { key: 'team', label: '团队' },
  { key: 'role_score', label: '综合' }
]
const availableDimensions = computed(() =>
  dimensions.filter((dimension) =>
    dimension.key === 'role_score' || props.scores.some((item) => item?.[dimension.key] != null)
  )
)

const hasExtendedDimensions = computed(() =>
  props.scores.some((item) => item.logic != null || item.team != null || item.role_score != null)
)

const viewMode = ref('bar')
const radarPlayerIndex = ref(0)
const activeViewMode = computed(() => viewMode.value)

function roleImage(player: AssessmentPlayer) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function roleText(player: AssessmentPlayer | undefined) {
  return displayRoleLabel(player?.role_hint || player?.role || '')
}

function clampScore(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function overallScore(item: AssessmentScore) {
  return clampScore(item?.role_score ?? item?.score ?? 0)
}

function rankBarClass(item: AssessmentScore) {
  const role = roleText(item?.player)
  if (role.includes('预言')) return 'seer'
  if (role.includes('女巫')) return 'witch'
  if (role.includes('猎人')) return 'hunter'
  if (role.includes('守卫')) return 'guard'
  if (role.includes('白狼')) return 'white-wolf'
  if (role.includes('狼人')) return 'wolf'
  return 'villager'
}

function metricScore(item: AssessmentScore | null, key: string) {
  return clampScore(item?.[key] ?? 0)
}

const compactRanking = computed(() =>
  [...props.scores]
    .sort((a, b) => overallScore(b) - overallScore(a) || Number(a.player?.seat || 0) - Number(b.player?.seat || 0))
)

const compactSelectedRank = computed(() => {
  if (!radarPlayer.value) return null
  const index = compactRanking.value.findIndex((item) => item.player?.id === radarPlayer.value?.player?.id)
  return index >= 0 ? index + 1 : null
})

const compactRankRows = computed(() => {
  const topRows = compactRanking.value.slice(0, 4)
  if (!radarPlayer.value) return topRows
  const selectedId = radarPlayer.value.player?.id
  if (topRows.some((item) => item.player?.id === selectedId)) return topRows
  return [...topRows.slice(0, 3), radarPlayer.value]
})

function compactRankNumber(item: AssessmentScore) {
  const index = compactRanking.value.findIndex((ranked) => ranked.player?.id === item?.player?.id)
  return index >= 0 ? index + 1 : null
}

function selectPlayer(item: AssessmentScore) {
  if (item?.player) emit('select-player', item.player)
}

function isActiveTab(key: string | number) {
  if (activeViewMode.value === 'radar') {
    return radarPlayerIndex.value === Number(key)
  }
  return props.dimension === key
}

function handleTabClick(key: string | number) {
  if (activeViewMode.value === 'radar') {
    radarPlayerIndex.value = Number(key)
  } else {
    emit('update:dimension', key)
  }
}

// --- Radar chart geometry ---
const radarDimensions = computed(() => {
  const base = [
    { key: 'speech', label: '发言' },
    { key: 'vote', label: '投票' },
    { key: 'skill', label: '技能' },
    { key: 'logic', label: '逻辑' },
    { key: 'team', label: '团队' }
  ]
  return base.filter((dimension) =>
    props.scores.some((item) => item?.[dimension.key] != null)
  )
})

const radarPlayer = computed(() => {
  if (props.compact && props.selectedPlayerId != null) {
    const selected = props.scores.find((item) => item.player?.id === props.selectedPlayerId)
    if (selected) return selected
  }
  const idx = Math.min(radarPlayerIndex.value, props.scores.length - 1)
  return props.scores[idx] || null
})

function radarPoint(index: number, value: unknown, total: number, cx: number, cy: number, radius: number) {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2
  const score = clampScore(value)
  const r = (Math.max(0, Math.min(score, 100)) / 100) * radius
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
}

function polygonPoints(values: unknown[], total: number, cx: number, cy: number, radius: number) {
  return values
    .map((v, i) => {
      const p = radarPoint(i, v, total, cx, cy, radius)
      return `${p.x},${p.y}`
    })
    .join(' ')
}

function gridPolygonPoints(level: number, total: number, cx: number, cy: number, radius: number) {
  return Array.from({ length: total })
    .map((_, i) => {
      const p = radarPoint(i, level * 100, total, cx, cy, radius)
      return `${p.x},${p.y}`
    })
    .join(' ')
}

function radarLabelAnchor(index: number, total: number) {
  if (total <= 1) return 'middle'
  const x = Math.cos((Math.PI * 2 * index) / total - Math.PI / 2)
  if (x > 0.15) return 'start'
  if (x < -0.15) return 'end'
  return 'middle'
}

function radarLabelDy(index: number, total: number) {
  const y = Math.sin((Math.PI * 2 * index) / total - Math.PI / 2)
  if (y < -0.5) return '-0.5em'
  if (y > 0.5) return '1.2em'
  return '0.35em'
}

function radarScoreForDim(key: string) {
  if (!radarPlayer.value) return 0
  return radarPlayer.value[key] ?? 0
}
</script>

<template>
  <section v-if="scores.length" class="multi-assess-module" :class="{ 'is-compact': props.compact }">
    <header v-if="!props.compact" class="multi-assess-header">
      <span>多维测评</span>
    </header>
    <div v-if="props.compact" class="multi-assess-body ma-compact-body">
      <section class="ma-compact-section ma-compact-ranking" aria-label="综合排行">
        <header class="ma-compact-section-title">
          <span>综合排行</span>
          <small>4 位</small>
        </header>
        <div class="ma-rank-list">
          <button
            v-for="(item, index) in compactRankRows"
            :key="'rank-' + item.player?.id"
            type="button"
            :class="['ma-rank-row', { active: item.player?.id === radarPlayer?.player?.id }]"
            @click="selectPlayer(item)"
          >
            <img :src="roleImage(item.player)" :alt="roleText(item.player)" class="ma-rank-avatar" />
            <span class="ma-rank-player">
              <b>{{ item.player?.seat }}号</b>
              <small>{{ roleText(item.player) }}</small>
            </span>
            <span class="ma-rank-score">{{ overallScore(item) }}</span>
            <span class="ma-rank-bar" aria-hidden="true">
              <i :class="'role-' + rankBarClass(item)" :style="{ width: overallScore(item) + '%' }"></i>
            </span>
          </button>
        </div>
      </section>

      <section v-if="radarPlayer && radarDimensions.length" class="ma-compact-section ma-compact-profile" aria-label="玩家画像">
        <header class="ma-profile-head">
          <img :src="roleImage(radarPlayer.player)" :alt="roleText(radarPlayer.player)" class="ma-profile-avatar" />
          <span class="ma-profile-meta">
            <b>{{ radarPlayer.player?.seat }}号玩家</b>
            <small>{{ roleText(radarPlayer.player) }}</small>
          </span>
          <span v-if="compactSelectedRank" class="ma-profile-rank">第 {{ compactSelectedRank }} 名</span>
        </header>

        <svg
          :viewBox="'0 0 300 300'"
          class="ma-radar-svg ma-radar-svg--compact"
          xmlns="http://www.w3.org/2000/svg"
        >
          <polygon
            v-for="level in [0.3, 0.6, 1.0]"
            :key="'compact-grid-' + level"
            :points="gridPolygonPoints(level, radarDimensions.length, 150, 150, 92)"
            fill="none"
            stroke="rgba(91, 47, 18, 0.18)"
            stroke-width="1"
          />
          <line
            v-for="(dim, i) in radarDimensions"
            :key="'compact-axis-' + dim.key"
            x1="150"
            y1="150"
            :x2="radarPoint(i, 100, radarDimensions.length, 150, 150, 92).x"
            :y2="radarPoint(i, 100, radarDimensions.length, 150, 150, 92).y"
            stroke="rgba(91, 47, 18, 0.12)"
            stroke-width="1"
          />
          <polygon
            :points="polygonPoints(radarDimensions.map(d => metricScore(radarPlayer, d.key)), radarDimensions.length, 150, 150, 92)"
            fill="rgba(242, 202, 80, 0.24)"
            stroke="#d4af37"
            stroke-width="2"
            stroke-linejoin="round"
          />
          <circle
            v-for="(dim, i) in radarDimensions"
            :key="'compact-dot-' + dim.key"
            :cx="radarPoint(i, metricScore(radarPlayer, dim.key), radarDimensions.length, 150, 150, 92).x"
            :cy="radarPoint(i, metricScore(radarPlayer, dim.key), radarDimensions.length, 150, 150, 92).y"
            r="3.5"
            fill="#d4af37"
          />
          <text
            v-for="(dim, i) in radarDimensions"
            :key="'compact-label-' + dim.key"
            :x="radarPoint(i, 100, radarDimensions.length, 150, 150, 116).x"
            :y="radarPoint(i, 100, radarDimensions.length, 150, 150, 116).y"
            :text-anchor="radarLabelAnchor(i, radarDimensions.length)"
            :dy="radarLabelDy(i, radarDimensions.length)"
            class="ma-radar-label"
          >{{ dim.label }}</text>
        </svg>

        <div class="ma-compact-metrics">
          <span v-for="dim in radarDimensions" :key="'compact-metric-' + dim.key">
            <small>{{ dim.label }}</small>
            <b>{{ metricScore(radarPlayer, dim.key) }}</b>
          </span>
        </div>
      </section>
    </div>

    <div v-else class="multi-assess-body">
      <!-- Bar chart tabs (dimension switching) -->
      <nav v-if="activeViewMode === 'bar'" class="ma-tabs">
        <button
          v-for="dim in availableDimensions"
          :key="dim.key"
          :class="['ma-tab', { active: dimension === dim.key }]"
          @click="emit('update:dimension', dim.key)"
        >
          {{ dim.label }}
        </button>
      </nav>
      <!-- Radar chart tabs (player switching) -->
      <nav v-if="activeViewMode === 'radar' && !props.compact" class="ma-tabs ma-tabs-players">
        <button
          v-for="(item, idx) in scores"
          :key="'radar-tab-' + item.player.id"
          :class="['ma-tab', { active: radarPlayerIndex === idx }]"
          @click="handleTabClick(idx)"
        >
          {{ item.player.seat }}号
        </button>
      </nav>

      <!-- Bar chart view -->
      <div v-if="activeViewMode === 'bar'" class="ma-chart-area ma-chart-horizontal">
        <div v-for="item in scores" :key="'assess-' + item.player.id" class="ma-bar-row">
          <div class="ma-bar-label">
            <img :src="roleImage(item.player)" :alt="item.player.role_hint" />
            <span>{{ item.player.seat }}号</span>
          </div>
          <div class="ma-bar-track-h">
            <div class="ma-bar-fill-h" :class="['ma-dim-' + dimension]" :style="{ width: item.score + '%' }"></div>
          </div>
          <span class="ma-score-num" :class="{ 'ma-zero': item.score === 0 }">{{ item.score }}</span>
        </div>
      </div>

      <div v-if="activeViewMode === 'radar' && radarPlayer && radarDimensions.length && !props.compact" class="ma-radar-area">
        <div class="ma-radar-header">
          <img :src="roleImage(radarPlayer.player)" :alt="radarPlayer.player.role_hint" class="ma-radar-avatar" />
          <span class="ma-radar-name">{{ radarPlayer.player.seat }}号玩家</span>
          <small v-if="radarPlayer.player.role_hint" class="ma-radar-role">{{ radarPlayer.player.role_hint }}</small>
        </div>
        <svg
          :viewBox="'0 0 300 300'"
          class="ma-radar-svg"
          xmlns="http://www.w3.org/2000/svg"
        >
          <!-- Background grid: 3 levels -->
          <polygon
            v-for="level in [0.3, 0.6, 1.0]"
            :key="'grid-' + level"
            :points="gridPolygonPoints(level, radarDimensions.length, 150, 150, 100)"
            fill="none"
            stroke="rgba(91, 47, 18, 0.18)"
            stroke-width="1"
          />
          <!-- Axis lines from center to vertices -->
          <line
            v-for="(dim, i) in radarDimensions"
            :key="'axis-' + dim.key"
            x1="150"
            y1="150"
            :x2="radarPoint(i, 100, radarDimensions.length, 150, 150, 100).x"
            :y2="radarPoint(i, 100, radarDimensions.length, 150, 150, 100).y"
            stroke="rgba(91, 47, 18, 0.12)"
            stroke-width="1"
          />
          <!-- Score polygon -->
          <polygon
            :points="polygonPoints(radarDimensions.map(d => radarPlayer[d.key] ?? 0), radarDimensions.length, 150, 150, 100)"
            fill="rgba(242, 202, 80, 0.22)"
            stroke="#d4af37"
            stroke-width="2"
            stroke-linejoin="round"
          />
          <!-- Score dots at vertices -->
          <circle
            v-for="(dim, i) in radarDimensions"
            :key="'dot-' + dim.key"
            :cx="radarPoint(i, radarPlayer[dim.key] ?? 0, radarDimensions.length, 150, 150, 100).x"
            :cy="radarPoint(i, radarPlayer[dim.key] ?? 0, radarDimensions.length, 150, 150, 100).y"
            r="3.5"
            fill="#d4af37"
          />
          <!-- Dimension labels -->
          <text
            v-for="(dim, i) in radarDimensions"
            :key="'label-' + dim.key"
            :x="radarPoint(i, 100, radarDimensions.length, 150, 150, 120).x"
            :y="radarPoint(i, 100, radarDimensions.length, 150, 150, 120).y"
            :text-anchor="radarLabelAnchor(i, radarDimensions.length)"
            :dy="radarLabelDy(i, radarDimensions.length)"
            class="ma-radar-label"
          >{{ dim.label }}</text>
          <!-- Score value labels -->
          <text
            v-for="(dim, i) in radarDimensions"
            :key="'score-label-' + dim.key"
            :x="radarPoint(i, radarPlayer[dim.key] ?? 0, radarDimensions.length, 150, 150, 100).x"
            :y="radarPoint(i, radarPlayer[dim.key] ?? 0, radarDimensions.length, 150, 150, 100).y - 8"
            text-anchor="middle"
            class="ma-radar-score"
          >{{ radarPlayer[dim.key] ?? 0 }}</text>
        </svg>
        <!-- Score summary strip below radar -->
        <div class="ma-radar-scores">
          <span v-for="dim in radarDimensions" :key="'summary-' + dim.key" class="ma-radar-score-item">
            <small>{{ dim.label }}</small>
            <b>{{ radarScoreForDim(dim.key) }}</b>
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
