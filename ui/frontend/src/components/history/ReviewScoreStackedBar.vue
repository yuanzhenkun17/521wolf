<script setup lang="ts">
import { computed, type PropType } from 'vue'

const props = defineProps({
  cards: { type: Array as PropType<ScoreCard[]>, default: () => [] }
})

interface ScoreDimension {
  key?: unknown
  label?: unknown
  value?: unknown
}

interface ScoreCard {
  key?: unknown
  seat?: unknown
  role?: unknown
  overall?: unknown
  dimensions?: ScoreDimension[]
}

interface NormalizedDimension {
  key: string
  label: string
  value: number
  color: string
}

interface EnrichedDimension extends NormalizedDimension {
  contribution: number
  fillWidth: number
}

interface ScoreRow {
  key: unknown
  seat: unknown
  role: string
  avatar: string
  overall: number
  dimensions: EnrichedDimension[]
}

const DIMENSION_COLORS: Record<string, string> = {
  speech: '#b8731c',
  vote: '#2f7780',
  skill: '#2f8a5f',
  information: '#d79b2f',
  cooperation: '#a93a32'
}
const FALLBACK_COLORS = ['#5f8f9b', '#8d6fa8', '#777f46', '#9a6044', '#6f7da2']
const UNKNOWN_ROLE_ICON = '/role-icons/optimized/未知.webp'

const rows = computed<ScoreRow[]>(() => props.cards
  .map(normalizeRow)
  .sort((a, b) => {
    const scoreDelta = b.overall - a.overall
    if (scoreDelta) return scoreDelta
    return seatNumber(a.seat) - seatNumber(b.seat)
  })
)

const dimensionDescriptors = computed(() => {
  const known = new Map<string, Pick<NormalizedDimension, 'key' | 'label' | 'color'>>()
  rows.value.forEach((row) => {
    row.dimensions.forEach((dimension) => {
      if (known.has(dimension.key)) return
      known.set(dimension.key, {
        key: dimension.key,
        label: dimension.label,
        color: dimension.color
      })
    })
  })
  return [...known.values()]
})

function normalizeRow(card: ScoreCard = {}, index = 0): ScoreRow {
  const role = String(card.role || '未知')
  const dimensions = Array.isArray(card.dimensions) ? card.dimensions.map((dimension, dimIndex) => {
    const key = String(dimension?.key || `dimension-${dimIndex}`)
    return {
      key,
      label: String(dimension?.label || key),
      value: clampScore(dimension?.value),
      color: dimensionColor(key, dimIndex)
    }
  }) : []
  const dimensionSum = dimensions.reduce((sum, dimension) => sum + dimension.value, 0)
  const overall = clampScore(card.overall)
  const enrichedDimensions = dimensions.map((dimension) => {
    const contribution = dimensionSum > 0 ? (overall * dimension.value) / dimensionSum : 0
    return {
      ...dimension,
      contribution,
      fillWidth: overall > 0 ? (contribution / overall) * 100 : 0
    }
  })

  return {
    key: card.key ?? `${card.seat ?? 'player'}-${index}`,
    seat: card.seat ?? '—',
    role,
    avatar: roleIconPath(role),
    overall,
    dimensions: enrichedDimensions
  }
}

function roleIconPath(role: unknown): string {
  const text = String(role || '')
  if (text.includes('预言')) return '/role-icons/optimized/预言家.webp'
  if (text.includes('女巫')) return '/role-icons/optimized/女巫.webp'
  if (text.includes('猎人')) return '/role-icons/optimized/猎人.webp'
  if (text.includes('守卫')) return '/role-icons/optimized/守卫.webp'
  if (text.includes('白狼')) return '/role-icons/optimized/白狼王.webp'
  if (text.includes('狼人') || text.includes('狼王')) return '/role-icons/optimized/普通狼.webp'
  if (text.includes('平民') || text.includes('村民')) return '/role-icons/optimized/平民.webp'
  return UNKNOWN_ROLE_ICON
}

function dimensionColor(key: string, index: number): string {
  return DIMENSION_COLORS[key] || FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

function clampScore(value: unknown): number {
  const num = Number(value)
  if (!Number.isFinite(num)) return 0
  return Math.max(0, Math.min(num, 100))
}

function seatNumber(seat: unknown): number {
  const num = Number(String(seat).replace(/[^\d.-]/g, ''))
  return Number.isFinite(num) ? num : 999
}

function seatLabel(seat: unknown): string {
  const text = String(seat ?? '—')
  if (text === '—' || text.endsWith('号')) return text
  return `${text}号`
}

function scoreLabel(value: unknown): string {
  const rounded = Math.round(clampScore(value) * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function segmentTitle(row: ScoreRow, dimension: EnrichedDimension): string {
  return `${seatLabel(row.seat)} ${row.role} · ${dimension.label}: ${scoreLabel(dimension.value)}，贡献 ${scoreLabel(dimension.contribution)}`
}
</script>

<template>
  <section v-if="rows.length" class="rsb" aria-label="玩家综合得分排行榜">
    <header class="rsb-legend" aria-label="评分维度">
      <span v-for="dimension in dimensionDescriptors" :key="'legend-' + dimension.key">
        <i :style="{ background: dimension.color }"></i>
        {{ dimension.label }}
      </span>
    </header>

    <div class="rsb-list" role="list">
      <div v-for="row in rows" :key="'score-row-' + row.key" class="rsb-row" role="listitem">
        <span class="rsb-player">
          <img
            class="rsb-avatar"
            :src="row.avatar"
            :alt="row.role"
            width="38"
            height="38"
            style="width: 38px; height: 38px; object-fit: contain;"
          />
          <span class="rsb-player-copy">
            <b>{{ seatLabel(row.seat) }}</b>
            <small>{{ row.role }}</small>
          </span>
        </span>

        <span class="rsb-track-cell">
          <span
            class="rsb-track"
            role="progressbar"
            :aria-valuenow="Math.round(row.overall)"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-label="`${seatLabel(row.seat)} ${row.role} 综合分 ${scoreLabel(row.overall)}`"
          >
            <span class="rsb-fill" :style="{ width: row.overall + '%' }">
              <span
                v-for="dimension in row.dimensions"
                :key="'segment-' + row.key + '-' + dimension.key"
                class="rsb-segment"
                :title="segmentTitle(row, dimension)"
                :style="{
                  width: dimension.fillWidth + '%',
                  background: dimension.color
                }"
              ></span>
            </span>
          </span>
        </span>

        <span class="rsb-total">
          <b>{{ scoreLabel(row.overall) }}</b>
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rsb,
.rsb * {
  box-sizing: border-box;
}

.rsb {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px 10px 14px;
  background: rgba(255, 252, 245, 0.32);
}

.rsb-legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-start;
  gap: 8px 16px;
  min-width: 0;
  padding: 0 0 9px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.12);
}

.rsb-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: rgba(59, 28, 9, 0.64);
  font-size: 11px;
  font-weight: 850;
  line-height: 1;
  white-space: nowrap;
}

.rsb-legend i {
  width: 16px;
  height: 8px;
  flex: 0 0 auto;
}

.rsb-list {
  display: grid;
  gap: 0;
  min-width: 0;
  margin: 0;
  padding: 0;
}

.rsb-row {
  display: grid;
  grid-template-columns: 92px minmax(360px, 1fr) 34px;
  align-items: center;
  gap: 4px;
  min-width: 0;
  min-height: 50px;
  padding: 7px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.09);
}

.rsb-row:last-child {
  border-bottom: 0;
}

.rsb-player {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.rsb-avatar {
  width: 34px;
  height: 34px;
  object-fit: contain;
  border: 1px solid rgba(93, 48, 17, 0.2);
  background: rgba(255, 248, 220, 0.62);
}

.rsb-player-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.rsb-player-copy b,
.rsb-player-copy small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rsb-player-copy b {
  color: #3b1c09;
  font-size: 13px;
  font-weight: 950;
  line-height: 1;
}

.rsb-player-copy small {
  color: rgba(59, 28, 9, 0.58);
  font-size: 11px;
  font-weight: 850;
  line-height: 1;
}

.rsb-track-cell {
  min-width: 0;
}

.rsb-track {
  position: relative;
  display: block;
  width: 100%;
  height: 24px;
  background:
    repeating-linear-gradient(
      90deg,
      rgba(93, 48, 17, 0.07) 0,
      rgba(93, 48, 17, 0.07) 1px,
      transparent 1px,
      transparent 25%
    ),
    rgba(93, 48, 17, 0.055);
  box-shadow: inset 0 0 0 1px rgba(93, 48, 17, 0.12);
}

.rsb-fill {
  display: flex;
  height: 100%;
  min-width: 0;
}

.rsb-segment {
  position: relative;
  display: block;
  height: 100%;
  min-width: 0;
  box-shadow: inset -1px 0 0 rgba(255, 252, 245, 0.5);
}

.rsb-segment:hover {
  filter: brightness(1.08) saturate(1.05);
  z-index: 2;
}

.rsb-total {
  display: grid;
  justify-items: start;
  min-width: 0;
}

.rsb-total b {
  color: #7f2430;
  font-size: 16px;
  font-weight: 950;
  line-height: 1;
}

@media (max-width: 720px) {
  .rsb {
    padding: 10px 8px 12px;
  }

  .rsb-legend {
    padding-left: 0;
  }

  .rsb-row {
    grid-template-columns: minmax(0, 1fr) 42px;
    gap: 8px;
    min-height: 76px;
  }

  .rsb-track-cell {
    grid-column: 1 / -1;
  }

  .rsb-player {
    grid-template-columns: 34px minmax(0, 1fr);
  }

  .rsb-avatar {
    width: 34px;
    height: 34px;
  }
}
</style>
