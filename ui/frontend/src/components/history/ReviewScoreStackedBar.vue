<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'

const props = defineProps({
  cards: { type: Array, default: () => [] }
})

const DIMENSION_COLORS = {
  speech: '#b8731c',
  vote: '#2f7780',
  skill: '#2f8a5f',
  information: '#d79b2f',
  cooperation: '#a93a32'
}
const FALLBACK_COLORS = ['#5f8f9b', '#8d6fa8', '#777f46', '#9a6044', '#6f7da2']
const UNKNOWN_ROLE_ICON = '/role-icons/optimized/未知.webp'

const rows = computed(() => props.cards
  .map(normalizeRow)
  .sort((a, b) => {
    const scoreDelta = b.overall - a.overall
    if (scoreDelta) return scoreDelta
    return seatNumber(a.seat) - seatNumber(b.seat)
  })
  .map((row, index) => ({ ...row, rank: index + 1 }))
)

const dimensionDescriptors = computed(() => {
  const known = new Map()
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

function normalizeRow(card = {}, index = 0) {
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
    role: card.role || '未知',
    avatar: roleIconPath(card.role || ''),
    overall,
    dimensions: enrichedDimensions
  }
}

function roleIconPath(role) {
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

function dimensionColor(key, index) {
  return DIMENSION_COLORS[key] || FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

function clampScore(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return 0
  return Math.max(0, Math.min(num, 100))
}

function seatNumber(seat) {
  const num = Number(String(seat).replace(/[^\d.-]/g, ''))
  return Number.isFinite(num) ? num : 999
}

function seatLabel(seat) {
  const text = String(seat ?? '—')
  if (text === '—' || text.endsWith('号')) return text
  return `${text}号`
}

function scoreLabel(value) {
  const rounded = Math.round(clampScore(value) * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function segmentTitle(row, dimension) {
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
        <span class="rsb-rank">{{ row.rank }}</span>

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
          <small>综合</small>
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
  padding: 12px 14px 14px;
  background: rgba(255, 252, 245, 0.32);
}

.rsb-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  min-width: 0;
  padding: 0 0 9px 88px;
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
  grid-template-columns: 30px 154px minmax(160px, 1fr) 58px;
  align-items: center;
  gap: 12px;
  min-width: 0;
  min-height: 50px;
  padding: 7px 0;
  border-bottom: 1px solid rgba(93, 48, 17, 0.09);
}

.rsb-row:last-child {
  border-bottom: 0;
}

.rsb-rank {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid rgba(93, 48, 17, 0.2);
  background: rgba(255, 239, 194, 0.48);
  color: rgba(59, 28, 9, 0.76);
  font-size: 12px;
  font-weight: 950;
  line-height: 1;
}

.rsb-player {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.rsb-avatar {
  width: 38px;
  height: 38px;
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
  height: 22px;
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
  justify-items: end;
  gap: 3px;
  min-width: 0;
}

.rsb-total small {
  color: rgba(59, 28, 9, 0.46);
  font-size: 10px;
  font-weight: 850;
  line-height: 1;
}

.rsb-total b {
  color: #7f2430;
  font-size: 15px;
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
    grid-template-columns: 30px minmax(0, 1fr) 54px;
    gap: 8px;
    min-height: 76px;
  }

  .rsb-track-cell {
    grid-column: 2 / -1;
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
