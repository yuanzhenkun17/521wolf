<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  scores: { type: Array, default: () => [] },
  dimension: { type: String, default: 'speech' },
  roleIconImage: Function
})

const emit = defineEmits(['update:dimension'])

const dimensions = [
  { key: 'speech', label: '发言' },
  { key: 'vote', label: '投票' },
  { key: 'skill', label: '技能' },
  { key: 'logic', label: '逻辑' },
  { key: 'team', label: '团队' },
  { key: 'role_score', label: '综合' }
]

const hasExtendedDimensions = computed(() =>
  props.scores.some((item) => item.logic != null || item.team != null || item.role_score != null)
)

const viewMode = ref('bar')
const radarPlayerIndex = ref(0)

function roleImage(player) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function isActiveTab(key) {
  if (viewMode.value === 'radar') {
    return radarPlayerIndex.value === Number(key)
  }
  return props.dimension === key
}

function handleTabClick(key) {
  if (viewMode.value === 'radar') {
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
  return base
})

const radarPlayer = computed(() => {
  const idx = Math.min(radarPlayerIndex.value, props.scores.length - 1)
  return props.scores[idx] || null
})

function radarPoint(index, value, total, cx, cy, radius) {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2
  const r = (Math.max(0, Math.min(value, 100)) / 100) * radius
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
}

function polygonPoints(values, total, cx, cy, radius) {
  return values
    .map((v, i) => {
      const p = radarPoint(i, v, total, cx, cy, radius)
      return `${p.x},${p.y}`
    })
    .join(' ')
}

function gridPolygonPoints(level, total, cx, cy, radius) {
  return Array.from({ length: total })
    .map((_, i) => {
      const p = radarPoint(i, level * 100, total, cx, cy, radius)
      return `${p.x},${p.y}`
    })
    .join(' ')
}

function radarLabelAnchor(index, total) {
  if (total <= 1) return 'middle'
  const x = Math.cos((Math.PI * 2 * index) / total - Math.PI / 2)
  if (x > 0.15) return 'start'
  if (x < -0.15) return 'end'
  return 'middle'
}

function radarLabelDy(index, total) {
  const y = Math.sin((Math.PI * 2 * index) / total - Math.PI / 2)
  if (y < -0.5) return '-0.5em'
  if (y > 0.5) return '1.2em'
  return '0.35em'
}

function radarScoreForDim(key) {
  if (!radarPlayer.value) return 0
  return radarPlayer.value[key] ?? 0
}
</script>

<template>
  <section v-if="scores.length" class="multi-assess-module">
    <header class="multi-assess-header">
      <span>多维测评</span>
      <div v-if="hasExtendedDimensions" class="ma-view-toggle">
        <button
          type="button"
          :class="['ma-view-btn', { active: viewMode === 'bar' }]"
          @click="viewMode = 'bar'"
        >条形图</button>
        <button
          type="button"
          :class="['ma-view-btn', { active: viewMode === 'radar' }]"
          @click="viewMode = 'radar'"
        >雷达图</button>
      </div>
    </header>
    <div class="multi-assess-body">
      <!-- Bar chart tabs (dimension switching) -->
      <nav v-if="viewMode === 'bar'" class="ma-tabs">
        <button
          v-for="dim in dimensions"
          :key="dim.key"
          :class="['ma-tab', { active: dimension === dim.key }]"
          @click="emit('update:dimension', dim.key)"
        >
          {{ dim.label }}
        </button>
      </nav>
      <!-- Radar chart tabs (player switching) -->
      <nav v-if="viewMode === 'radar'" class="ma-tabs ma-tabs-players">
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
      <div v-if="viewMode === 'bar'" class="ma-chart-area">
        <div v-for="item in scores" :key="'assess-' + item.player.id" class="ma-bar-col">
          <span class="ma-score-num" :class="{ 'ma-zero': item.score === 0 }">{{ item.score }}</span>
          <div class="ma-bar-track">
            <div class="ma-bar-fill" :class="['ma-dim-' + dimension]" :style="{ height: item.score + '%' }"></div>
          </div>
          <div class="ma-player-foot">
            <img :src="roleImage(item.player)" :alt="item.player.role_hint" />
            <span>{{ item.player.seat }}号</span>
          </div>
        </div>
      </div>

      <!-- Radar chart view -->
      <div v-if="viewMode === 'radar' && radarPlayer" class="ma-radar-area">
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
