<script setup>
import { computed } from 'vue'
import {
  displayDayLabel,
  displayPhaseLabel,
  displayRoleLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from './historyDisplay.js'

const props = defineProps({
  report: { type: Object, default: null },
  game: { type: Object, default: () => ({}) },
  formatJson: Function
})

const reviewData = computed(() => {
  const raw = props.report
  if (!raw || raw.error) return null
  return raw.data || raw
})
const reviewGameSummary = computed(() => reviewData.value?.game_summary || null)
const reviewPlayerScores = computed(() => {
  const raw = reviewData.value?.player_evaluations || reviewData.value?.player_scores || []
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object') {
    return Object.entries(raw).map(([seat, score]) => ({
      player_seat: score?.player_seat ?? score?.player_id ?? score?.seat ?? seat,
      ...(score || {})
    }))
  }
  return []
})
const reviewTurningPoints = computed(() => reviewData.value?.turning_points || [])
const reviewCounterfactuals = computed(() => reviewData.value?.counterfactuals || [])
const reviewTimeline = computed(() => reviewData.value?.timeline || [])
const scoreDimensions = [
  { key: 'speech', label: '发言', fields: ['speech_score', 'speech', 'speech_quality'] },
  { key: 'vote', label: '投票', fields: ['vote_score', 'vote', 'vote_accuracy'] },
  { key: 'skill', label: '技能', fields: ['skill_score', 'skill', 'skill_accuracy'] },
  { key: 'information', label: '信息', fields: ['information_score', 'information', 'logic_score', 'logic'] },
  { key: 'cooperation', label: '协作', fields: ['team_score', 'team', 'team_contribution', 'cooperation_score', 'cooperation'] }
]
const overallScoreField = { fields: ['role_score', 'overall_score', 'overall', 'total_score'] }
const reviewScoreCards = computed(() =>
  reviewPlayerScores.value.map((score, index) => ({
    key: score.player_seat ?? score.player_id ?? score.seat ?? index,
    seat: playerSeat(score),
    role: roleLabel(score.role || score.role_hint),
    score,
    dimensions: scoreDimensions.map((dim) => ({
      ...dim,
      value: scorePercent(scoreValue(score, dim))
    })),
    overall: scorePercent(scoreValue(score, overallScoreField))
  }))
)

function impactClass(impact) {
  if (!impact) return ''
  const lower = String(impact).toLowerCase()
  if (lower === 'high' || lower === 'critical') return 'impact-high'
  if (lower === 'medium') return 'impact-medium'
  if (lower === 'low') return 'impact-low'
  return ''
}

function impactLabel(impact) {
  if (!impact) return '一般'
  const lower = String(impact).toLowerCase()
  if (lower === 'high' || lower === 'critical') return '高'
  if (lower === 'medium') return '中'
  if (lower === 'low') return '低'
  return impact
}

function phaseLabel(phase) {
  return displayPhaseLabel(phase)
}

function winnerLabel(winner) {
  return displayWinnerLabel(winner)
}

function dayLabel(day) {
  return displayDayLabel(day)
}

function confidencePercent(value) {
  if (value == null) return 50
  const num = Number(value)
  if (!Number.isFinite(num)) return 50
  return Math.round(Math.max(0, Math.min(num, 1)) * 100)
}

function scorePercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return 0
  if (num <= 1) return Math.round(Math.max(0, Math.min(num * 100, 100)))
  if (num <= 10) return Math.round(Math.max(0, Math.min(num * 10, 100)))
  return Math.round(Math.max(0, Math.min(num, 100)))
}

function playerSeat(score) {
  return score.player_seat ?? score.player_id ?? score.seat ?? '—'
}

function roleLabel(role) {
  return displayRoleLabel(role)
}

function scoreValue(score, dim) {
  for (const field of dim.fields) {
    if (score[field] != null) return score[field]
  }
  return 0
}

function formatReviewText(value) {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') {
    return formatReviewText(value.description || value.summary || value.event || value.message || JSON.stringify(value))
  }
  return normalizeHistoryDisplayText(value) || '—'
}

function radarPoint(index, value, total, cx = 80, cy = 80, radius = 46) {
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2
  const safe = Math.max(0, Math.min(Number(value) || 0, 100))
  const r = (safe / 100) * radius
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
}

function radarPolygon(values, cx = 80, cy = 80, radius = 46) {
  const total = values.length
  return values.map((value, index) => {
    const p = radarPoint(index, value, total, cx, cy, radius)
    return `${p.x},${p.y}`
  }).join(' ')
}

function radarGrid(level, total, cx = 80, cy = 80, radius = 46) {
  return Array.from({ length: total }).map((_, index) => {
    const p = radarPoint(index, level * 100, total, cx, cy, radius)
    return `${p.x},${p.y}`
  }).join(' ')
}

function radarLabelAnchor(index, total) {
  const x = Math.cos((Math.PI * 2 * index) / total - Math.PI / 2)
  if (x > 0.2) return 'start'
  if (x < -0.2) return 'end'
  return 'middle'
}

function radarLabelDy(index, total) {
  const y = Math.sin((Math.PI * 2 * index) / total - Math.PI / 2)
  if (y < -0.5) return '-0.45em'
  if (y > 0.5) return '1.05em'
  return '0.35em'
}

function jsonText(value) {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <section class="archive-review-panel">
    <h3>复盘报告</h3>
    <template v-if="reviewData">
      <div v-if="reviewGameSummary" class="review-summary-strip">
        <span class="review-summary-item review-winner">
          <small>胜方</small><b>{{ winnerLabel(reviewGameSummary.winner || game.winner) }}</b>
        </span>
        <span class="review-summary-item">
          <small>天数</small><b>{{ reviewGameSummary.total_days ?? game.day ?? '—' }}</b>
        </span>
        <span class="review-summary-item">
          <small>事件</small><b>{{ reviewGameSummary.event_count ?? game.events?.length ?? 0 }}</b>
        </span>
        <span class="review-summary-item">
          <small>决策</small><b>{{ reviewGameSummary.decision_count ?? game.decisions?.length ?? 0 }}</b>
        </span>
      </div>

      <div v-else-if="reviewData.review_status" class="empty-log">
        {{ formatReviewText(reviewData.summary || reviewData.review_status) }}
      </div>

      <section v-if="reviewScoreCards.length" class="review-score-section">
        <header class="review-score-panel-head">
          <div>
            <small>评分预览</small>
            <h4>玩家评分</h4>
          </div>
          <b>{{ reviewScoreCards.length }} 人</b>
        </header>
        <div class="review-score-grid">
          <article v-for="card in reviewScoreCards" :key="'review-score-' + card.key" class="review-score-card">
            <header>
              <span class="review-seat">{{ card.seat }}号</span>
              <span class="review-role">{{ card.role }}</span>
              <b>{{ card.overall }}%</b>
            </header>
            <svg class="review-radar-svg" viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg">
              <polygon
                v-for="level in [0.35, 0.7, 1]"
                :key="'review-grid-' + card.key + '-' + level"
                :points="radarGrid(level, card.dimensions.length)"
                class="review-radar-grid"
              />
              <line
                v-for="(dim, index) in card.dimensions"
                :key="'review-axis-' + card.key + '-' + dim.key"
                x1="80"
                y1="80"
                :x2="radarPoint(index, 100, card.dimensions.length).x"
                :y2="radarPoint(index, 100, card.dimensions.length).y"
                class="review-radar-axis"
              />
              <polygon
                :points="radarPolygon(card.dimensions.map((dim) => dim.value))"
                class="review-radar-fill"
              />
              <circle
                v-for="(dim, index) in card.dimensions"
                :key="'review-dot-' + card.key + '-' + dim.key"
                :cx="radarPoint(index, dim.value, card.dimensions.length).x"
                :cy="radarPoint(index, dim.value, card.dimensions.length).y"
                r="2.5"
                class="review-radar-dot"
              />
              <text
                v-for="(dim, index) in card.dimensions"
                :key="'review-label-' + card.key + '-' + dim.key"
                :x="radarPoint(index, 100, card.dimensions.length, 80, 80, 61).x"
                :y="radarPoint(index, 100, card.dimensions.length, 80, 80, 61).y"
                :text-anchor="radarLabelAnchor(index, card.dimensions.length)"
                :dy="radarLabelDy(index, card.dimensions.length)"
                class="review-radar-label"
              >{{ dim.label }}</text>
            </svg>
            <div class="review-score-metrics">
              <span v-for="dim in card.dimensions" :key="'review-metric-' + card.key + '-' + dim.key">
                <small>{{ dim.label }}</small><b>{{ dim.value }}</b>
              </span>
            </div>
          </article>
        </div>
      </section>

      <div v-if="reviewTurningPoints.length">
        <h4>关键转折</h4>
        <article v-for="(item, index) in reviewTurningPoints" :key="'tp-' + index" class="review-tp-card">
          <div class="review-tp-badges">
            <span class="review-day-badge">{{ dayLabel(item.day ?? item.turn) }}</span>
            <span v-if="item.phase" class="review-phase-badge">{{ phaseLabel(item.phase) }}</span>
            <span class="review-impact-badge" :class="impactClass(item.impact)">
              {{ impactLabel(item.impact) }}
            </span>
          </div>
          <p class="review-tp-desc">{{ formatReviewText(item.description || item.summary || item.event || item) }}</p>
        </article>
      </div>

      <div v-if="reviewCounterfactuals.length">
        <h4>反事实</h4>
        <article v-for="(item, index) in reviewCounterfactuals" :key="'cf-' + index" class="review-cf-card">
          <p class="review-cf-whatif"><strong>如果：</strong>{{ formatReviewText(item.what_if || item.scenario || item.action) }}</p>
          <p class="review-cf-outcome"><strong>可能结果：</strong>{{ formatReviewText(item.outcome || item.expected_outcome || item.summary) }}</p>
          <div class="review-cf-confidence">
            <span>置信度</span>
            <div class="review-confidence-track">
              <div class="review-confidence-fill" :style="{ width: confidencePercent(item.confidence) + '%' }"></div>
            </div>
            <b>{{ confidencePercent(item.confidence) }}%</b>
          </div>
        </article>
      </div>

      <div v-if="reviewTimeline.length" class="review-timeline">
        <h4>时间线</h4>
        <div v-for="(item, index) in reviewTimeline" :key="'tl-' + index" class="review-tl-item">
          <span class="review-tl-badge">{{ dayLabel(item.day) }} · {{ phaseLabel(item.phase) }}</span>
          <span class="review-tl-event">{{ formatReviewText(item.description || item.event_type || item.message) }}</span>
        </div>
      </div>
    </template>
    <pre v-if="!reviewData">{{ jsonText(report) }}</pre>
  </section>
</template>

<style scoped>
.archive-review-panel {
  margin-top: 12px;
  border: 1px solid var(--log-border);
  padding: 16px;
  background: var(--log-surface);
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.06);
}

.archive-review-panel h3 {
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--log-border);
  color: var(--log-text);
  font-size: 15px;
  font-weight: 900;
}

.archive-review-panel h4 {
  margin: 14px 0 8px;
  color: var(--log-text);
  font-size: 13px;
  font-weight: 800;
}

.archive-review-panel h4:first-child {
  margin-top: 0;
}

.archive-review-panel pre {
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
  line-height: 1.5;
}

.empty-log {
  padding: 40px 20px;
  text-align: center;
  color: var(--log-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.review-summary-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--log-border);
}

.review-summary-item {
  display: grid;
  gap: 3px;
  min-width: 72px;
  padding: 8px 12px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.6);
  transition: border-color 0.15s ease;
}

.review-summary-item:hover {
  border-color: rgba(139, 94, 52, 0.25);
}

.review-summary-item.review-winner {
  border-color: rgba(212, 175, 55, 0.4);
  background: rgba(255, 226, 157, 0.3);
}

.review-summary-item small {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  line-height: 1;
}

.review-summary-item b {
  color: var(--log-text);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.15;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-score-section {
  display: grid;
  grid-template-rows: auto auto;
  gap: 0;
  margin-top: 12px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: var(--log-surface);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  overflow: hidden;
}

.review-score-panel-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--log-border);
  background: rgba(255, 252, 245, 0.42);
}

.review-score-panel-head div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.review-score-panel-head small {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.review-score-panel-head h4 {
  margin: 0;
  color: var(--log-text);
  font-size: 15px;
  font-weight: 800;
}

.review-score-panel-head b {
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.review-score-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  min-width: 0;
  background: rgba(139, 94, 52, 0.11);
}

.review-score-card {
  position: relative;
  display: grid;
  grid-template-rows: auto 166px auto;
  gap: 8px;
  min-width: 0;
  min-height: 272px;
  padding: 12px 10px 13px;
  background: rgba(255, 252, 245, 0.36);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28);
}

.review-score-card header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.review-seat {
  display: inline-grid;
  min-width: 34px;
  height: 24px;
  place-items: center;
  border-radius: 999px;
  background: var(--log-accent-strong);
  color: #fff7dc;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.review-role {
  min-width: 0;
  overflow: hidden;
  padding: 3px 8px;
  border: 1px solid var(--log-border);
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--log-accent);
  font-size: 11px;
  font-weight: 850;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-score-card header b {
  color: var(--log-accent-strong);
  font-size: 14px;
  font-weight: 950;
  line-height: 1;
}

.review-radar-svg {
  width: min(100%, 142px);
  aspect-ratio: 1;
  justify-self: center;
  align-self: start;
  margin-top: 16px;
  overflow: visible;
  transform: none;
}

.review-radar-grid {
  fill: none;
  stroke: rgba(91, 47, 18, 0.16);
  stroke-width: 1;
}

.review-radar-axis {
  stroke: rgba(91, 47, 18, 0.12);
  stroke-width: 1;
}

.review-radar-fill {
  fill: rgba(212, 175, 55, 0.26);
  stroke: #a56a22;
  stroke-linejoin: round;
  stroke-width: 2;
}

.review-radar-dot {
  fill: #8b5e34;
  stroke: #fff7dc;
  stroke-width: 1.2;
}

.review-radar-label {
  fill: var(--log-accent-strong);
  font-family: inherit;
  font-size: 10px;
  font-weight: 900;
}

.review-score-metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 4px;
  min-width: 0;
}

.review-score-metrics span {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 4px 3px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.055);
  text-align: center;
}

.review-score-metrics small {
  color: var(--log-text-secondary);
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
}

.review-score-metrics b {
  color: var(--log-text);
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

.review-tp-card {
  padding: 10px 12px;
  margin-bottom: 6px;
  border-left: 3px solid rgba(212, 175, 55, 0.5);
  background: var(--log-surface);
  border-radius: 6px;
  transition: background 0.15s ease;
}

.review-tp-card:hover {
  background: rgba(255, 252, 245, 0.85);
}

.review-tp-badges {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.review-day-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--log-active-bg);
  color: var(--log-accent);
  font-size: 11px;
  font-weight: 800;
}

.review-phase-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(139, 94, 52, 0.06);
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 700;
}

.review-impact-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 800;
}

.review-impact-badge.impact-high {
  background: rgba(192, 57, 43, 0.1);
  color: #c0392b;
}

.review-impact-badge.impact-medium {
  background: rgba(243, 156, 18, 0.1);
  color: #d4880f;
}

.review-impact-badge.impact-low {
  background: rgba(39, 174, 96, 0.1);
  color: #27ae60;
}

.review-tp-desc {
  margin: 0;
  color: var(--log-text);
  font-size: 13px;
  line-height: 1.5;
}

.review-cf-card {
  padding: 10px 12px;
  margin-bottom: 6px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: var(--log-surface);
  transition: border-color 0.15s ease;
}

.review-cf-card:hover {
  border-color: rgba(139, 94, 52, 0.25);
}

.review-cf-whatif,
.review-cf-outcome {
  margin: 0 0 4px;
  color: var(--log-text);
  font-size: 13px;
  line-height: 1.5;
}

.review-cf-whatif strong,
.review-cf-outcome strong {
  color: var(--log-accent);
  font-weight: 800;
}

.review-cf-confidence {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.review-cf-confidence > span {
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.review-confidence-track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: rgba(139, 94, 52, 0.08);
  overflow: hidden;
}

.review-confidence-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #d4af37, #f2ca50);
  transition: width 0.4s cubic-bezier(0.22, 0.61, 0.36, 1);
}

.review-cf-confidence b {
  min-width: 32px;
  color: var(--log-accent);
  font-size: 11px;
  font-weight: 900;
  text-align: right;
}

.review-timeline {
  margin-bottom: 8px;
}

.review-tl-item {
  display: grid;
  grid-template-columns: minmax(82px, auto) minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  padding: 5px 0;
  border-bottom: 1px solid rgba(139, 94, 52, 0.06);
}

.review-tl-badge {
  min-width: 80px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--log-active-bg);
  color: var(--log-accent);
  font-size: 10px;
  font-weight: 800;
  text-align: center;
}

.review-tl-event {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--log-text);
  font-size: 13px;
  line-height: 1.45;
}

@media (max-width: 1280px) {
  .review-score-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .review-score-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .archive-review-panel {
    padding: 12px;
    border-radius: 8px;
  }

  .review-summary-strip {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .review-score-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .review-score-card {
    min-height: 232px;
    padding: 9px;
  }

  .review-radar-label {
    font-size: 9px;
  }

  .review-cf-confidence {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
  }
}

@media (max-width: 420px) {
  .review-score-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .review-score-card {
    min-height: 232px;
  }

  .review-tl-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .review-tl-badge {
    justify-self: start;
  }
}
</style>
