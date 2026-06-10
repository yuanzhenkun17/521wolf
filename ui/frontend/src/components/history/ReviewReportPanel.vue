<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { buildAssessmentScores } from '../../composables/assessmentScores.ts'
import JudgeEvidencePanel from './JudgeEvidencePanel.vue'
import {
  displayActionLabel,
  displayDayLabel,
  displayPhaseLabel,
  displayRoleLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from './historyDisplay.ts'

type LooseRecord = Record<string, any>

const VoteFlowSankey = defineAsyncComponent({
  loader: () => import('./VoteFlowSankey.vue'),
  delay: 120
})
const ReviewScoreStackedBar = defineAsyncComponent(() => import('./ReviewScoreStackedBar.vue'))

const props = defineProps({
  report: { type: Object, default: null },
  game: { type: Object, default: () => ({}) },
  flowData: { type: Object, default: null },
  flowLoading: Boolean,
  loadFlowData: Function,
  formatJson: Function
})

const reviewData = computed(() => {
  const raw = props.report
  if (!raw || raw.error) return null
  return raw.data || raw
})
const flowDataPayload = computed(() => {
  const raw = props.flowData
  if (!raw || raw.error) return null
  return raw.data || raw
})
const flowDataError = computed(() => props.flowData?.error || '')
const reviewFlowDecisions = computed(() => {
  const flowRows = decisionArray(flowDataPayload.value?.decisions)
  if (flowRows.length) return dedupeDecisions(flowRows)
  const candidates = [
    reviewData.value?.flow_data?.decisions,
    props.game?.decisions,
    reviewData.value?.decisions,
    reviewData.value?.archive?.decisions,
    reviewData.value?.game?.decisions,
    reviewData.value?.snapshot?.decisions
  ]
  return dedupeDecisions(candidates.flatMap(decisionArray))
})
const hasFlowChartData = computed(() => reviewFlowDecisions.value.length > 0)
const flowDecisionCount = computed(() => {
  const value = Number(
    flowDataPayload.value?.decision_count
    ?? reviewData.value?.game_summary?.decision_count
    ?? props.game?.decision_count
    ?? props.game?.decisions?.length
    ?? reviewFlowDecisions.value.length
  )
  return Number.isFinite(value) ? Math.max(0, value) : 0
})
const canShowFlowChartGate = computed(() =>
  hasFlowChartData.value
  || Boolean(props.flowLoading)
  || Boolean(flowDataError.value)
  || flowDecisionCount.value > 0
)
const showFlowCharts = computed(() => hasFlowChartData.value)
const flowChartRequestKey = computed(() => String(
  props.game?.game_id
  ?? flowDataPayload.value?.game_id
  ?? reviewData.value?.game_id
  ?? ''
))
const requestedFlowChartKey = ref('')
const flowChartStatusLabel = computed(() => {
  if (props.flowLoading) return '读取中'
  if (flowDataError.value) return '读取失败'
  if (hasFlowChartData.value) return `${reviewFlowDecisions.value.length} 条决策`
  if (flowDecisionCount.value > 0) return `${flowDecisionCount.value} 条决策`
  return '无可用决策'
})

async function requestFlowCharts({ force = false } = {}) {
  const key = flowChartRequestKey.value || '__current__'
  if (!force && requestedFlowChartKey.value === key) return null
  requestedFlowChartKey.value = key
  if (hasFlowChartData.value || props.flowLoading || !props.loadFlowData) return null
  return props.loadFlowData()
}

function retryFlowCharts() {
  return requestFlowCharts({ force: true })
}

watch(flowChartRequestKey, (key, previousKey) => {
  if (key !== previousKey) requestedFlowChartKey.value = ''
})

watch(
  [canShowFlowChartGate, hasFlowChartData, () => props.flowLoading, flowDataError, flowChartRequestKey],
  () => {
    if (!canShowFlowChartGate.value || hasFlowChartData.value || props.flowLoading || flowDataError.value) return
    void requestFlowCharts()
  },
  { immediate: true }
)

const hasReviewFallback = computed(() =>
  reviewScoreCards.value.length
  || canShowFlowChartGate.value
)
const hasReviewContent = computed(() => Boolean(reviewData.value) || hasReviewFallback.value)
const reviewGameSummary = computed(() => reviewData.value?.game_summary || null)
const reviewPlayerScores = computed(() => {
  const candidates = [
    reviewData.value?.player_evaluations,
    reviewData.value?.player_scores,
    reviewData.value?.agent_scores
  ]
  const raw = candidates.find((candidate) =>
    Array.isArray(candidate) ? candidate.length > 0 : candidate && typeof candidate === 'object' && Object.keys(candidate).length > 0
  )
  if (!raw) {
    return buildAssessmentScores(props.game).map((score) => ({
      player_seat: score.player?.seat ?? score.player?.id,
      role: score.player?.role ?? score.player?.role_hint,
      speech_score: score.speech / 100,
      vote_score: score.vote / 100,
      skill_score: score.skill / 100,
      logic_score: score.logic / 100,
      information_score: score.information / 100,
      team_score: score.team / 100,
      cooperation_score: score.cooperation / 100,
      role_score: score.role_score / 100,
      overall_score: score.role_score / 100
    }))
  }
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object') {
    return Object.entries(raw).map(([seat, score]) => {
      const record = score && typeof score === 'object' ? score as LooseRecord : {}
      return {
        player_seat: record.player_seat ?? record.player_id ?? record.seat ?? seat,
        ...record,
        ...(record.scores || {})
      }
    })
  }
  return []
})
const reviewScoreSource = computed(() => {
  if (!reviewScoreCards.value.length) return null
  return reviewData.value ? 'report' : 'local_estimate'
})
const reviewScoreSourceLabel = computed(() =>
  reviewScoreSource.value === 'local_estimate'
    ? '本地推算，仅供浏览'
    : '复盘报告评分'
)
const reviewScoreSourceClass = computed(() =>
  reviewScoreSource.value === 'local_estimate' ? 'local-estimate' : 'report'
)
const reviewTurningPoints = computed(() => reviewData.value?.turning_points || [])
const reviewCounterfactuals = computed(() => reviewData.value?.counterfactuals || [])
const reviewTimeline = computed(() => reviewData.value?.timeline || [])
const decisionJudgeData = computed(() => {
  const judge = reviewData.value?.decision_judge
  return judge && typeof judge === 'object' ? judge : null
})
const decisionJudgeSummary = computed(() => {
  const summary = decisionJudgeData.value?.summary
  return summary && typeof summary === 'object' ? summary : {}
})
const decisionJudgeMetrics = computed(() => {
  const metrics = decisionJudgeData.value?.metrics
  return metrics && typeof metrics === 'object' ? metrics : {}
})
const decisionJudgeJudgments = computed(() => {
  const rows = decisionJudgeData.value?.judgments
  return Array.isArray(rows) ? rows.filter((item) => item && typeof item === 'object') : []
})
const decisionJudgeCards = computed(() =>
  decisionJudgeJudgments.value.map((item, index) => ({
    key: `judge-item-${item.decision_id || item.id || index}`,
    item,
    evidence: buildJudgeEvidenceDetails(item)
  }))
)
const decisionJudgeLowestRows = computed(() => {
  const lowest = decisionJudgeSummary.value?.lowest_decisions
  if (Array.isArray(lowest) && lowest.length) return lowest.filter((item) => item && typeof item === 'object').slice(0, 3)
  return [...decisionJudgeJudgments.value]
    .sort((a, b) => Number(a.score ?? 99) - Number(b.score ?? 99))
    .slice(0, 3)
})
const showDecisionJudge = computed(() =>
  Boolean(decisionJudgeData.value && (
    decisionJudgeJudgments.value.length
    || decisionJudgeLowestRows.value.length
    || decisionJudgeData.value.status === 'failed'
    || decisionJudgeData.value.status === 'degraded'
  ))
)
const scoreDimensions = [
  { key: 'speech', label: '发言', fields: ['speech_score', 'speech', 'speech_quality'] },
  { key: 'vote', label: '投票', fields: ['vote_score', 'vote', 'vote_accuracy'] },
  { key: 'skill', label: '技能', fields: ['skill_score', 'skill', 'skill_accuracy'] },
  { key: 'information', label: '信息', fields: ['information_score', 'information', 'logic_score', 'logic'] },
  { key: 'cooperation', label: '协作', fields: ['team_score', 'team', 'team_contribution', 'cooperation_score', 'cooperation'] }
]
const overallScoreField = { fields: ['role_score', 'overall_score', 'overall', 'total_score'] }
const reviewScoreCards = computed(() =>
  reviewPlayerScores.value.map((score, index) => {
    const dimensions = scoreDimensions.map((dim) => ({
      ...dim,
      value: scorePercent(scoreValue(score, dim))
    }))
    const rawOverall = scoreValue(score, overallScoreField, null)
    const dimensionAverage = dimensions.length
      ? Math.round(dimensions.reduce((sum, dim) => sum + dim.value, 0) / dimensions.length)
      : 0
    return {
      key: score.player_seat ?? score.player_id ?? score.seat ?? index,
      seat: playerSeat(score),
      role: roleLabel(score.role || score.role_hint),
      score,
      dimensions,
      overall: rawOverall == null ? dimensionAverage : scorePercent(rawOverall)
    }
  })
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

function actionLabel(action) {
  return displayActionLabel(action)
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

function scoreText(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return `${Math.round(num * 10) / 10}`
}

function averageScoreText(value) {
  return scoreText(value)
}

function playerSeat(score) {
  return score.player_seat ?? score.player_id ?? score.seat ?? '—'
}

function roleLabel(role) {
  return displayRoleLabel(role)
}

function scoreValue(score, dim, fallback = 0) {
  for (const field of dim.fields) {
    if (score[field] != null) return score[field]
  }
  return fallback
}

function decisionArray(value) {
  if (!Array.isArray(value)) return []
  return value.filter((item) => item && typeof item === 'object')
}

function decisionKey(decision, index) {
  const stableId = decision.id || decision.decision_id
  if (stableId) return `id:${stableId}`
  return [
    'row',
    index,
    decision.index,
    decision.day,
    decision.phase,
    decision.action || decision.action_type || decision.type,
    decision.actor_id || decision.player_id,
    decision.target_id || decision.selected_target || decision.target_player_id,
    decision.public_summary || decision.public_text || decision.reason || decision.message
  ].map((part) => String(part ?? '')).join('|')
}

function dedupeDecisions(decisions) {
  const seen = new Set()
  const rows = []
  decisions.forEach((decision, index) => {
    const key = decisionKey(decision, index)
    if (seen.has(key)) return
    seen.add(key)
    rows.push(decision)
  })
  return rows
}

function formatReviewText(value) {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') {
    return formatReviewText(value.description || value.summary || value.event || value.message || JSON.stringify(value))
  }
  return normalizeHistoryDisplayText(value) || '—'
}

function qualityLabel(quality) {
  const key = String(quality || '').trim().toLowerCase()
  return {
    good: '优秀',
    ok: '可接受',
    bad: '需复盘',
    unknown: '证据不足'
  }[key] || formatReviewText(quality)
}

function qualityClass(quality) {
  const key = String(quality || '').trim().toLowerCase()
  if (key === 'good') return 'quality-good'
  if (key === 'ok') return 'quality-ok'
  if (key === 'bad') return 'quality-bad'
  if (key === 'unknown') return 'quality-unknown'
  return ''
}

function judgeStatusLabel(status) {
  const key = String(status || '').trim().toLowerCase()
  return {
    ok: '已完成',
    degraded: '部分完成',
    failed: '评审失败',
    skipped: '未启用'
  }[key] || formatReviewText(status)
}

function valueRows(value) {
  if (value == null || value === '') return []
  if (Array.isArray(value)) return value.flatMap(valueRows)
  if (typeof value === 'object') return Object.keys(value).length ? [value] : []
  const text = String(value).trim()
  return text ? [value] : []
}

function fieldRows(item, names) {
  if (!item || typeof item !== 'object') return []
  return uniqueRows(names.flatMap((name) => valueRows(item[name])))
}

function rowIdentity(value) {
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return Object.prototype.toString.call(value)
    }
  }
  return String(value)
}

function uniqueRows(rows) {
  const seen = new Set()
  return rows.filter((row) => {
    const key = rowIdentity(row)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function judgeDecisionId(item) {
  const id = item?.decision_id ?? item?.decisionId ?? item?.id
  return id == null ? '' : String(id)
}

function rowMatchesDecision(row, item) {
  const id = judgeDecisionId(item)
  if (!id) return false
  if (row && typeof row === 'object') {
    const rowId = row.decision_id ?? row.decisionId ?? row.id ?? row.target_id
    if (rowId != null && String(rowId) === id) return true
    return [
      row.message,
      row.reason,
      row.exception_message,
      row.detail,
      row.summary
    ].some((value) => value != null && String(value).includes(id))
  }
  return String(row).includes(id)
}

function decisionJudgeScopedRows(field, item) {
  const localRows = fieldRows(item, [field, field.slice(0, -1)])
  const reportRows = valueRows(decisionJudgeData.value?.[field])
    .filter((row) => rowMatchesDecision(row, item))
  return uniqueRows([...localRows, ...reportRows])
}

function diagnosticReason(row) {
  if (!row || typeof row !== 'object') return ''
  return String(row.reason || row.kind || row.message || '').trim()
}

function buildJudgeEvidenceDetails(item) {
  const diagnostics = decisionJudgeScopedRows('diagnostics', item)
  const degradedReasons = uniqueRows([
    ...fieldRows(item, ['degraded_reasons', 'degraded_reason', 'failure_reason', 'error']),
    ...decisionJudgeScopedRows('degraded_reasons', item),
    ...diagnostics.map(diagnosticReason).filter(Boolean)
  ])
  const details = {
    evidenceRefs: fieldRows(item, ['evidence_refs', 'evidence_ref']),
    counterfactuals: fieldRows(item, ['counterfactual', 'counterfactuals']),
    rubricMisses: fieldRows(item, ['rubric_misses', 'rubric_miss']),
    diagnostics,
    degradedReasons,
    warnings: decisionJudgeScopedRows('warnings', item),
    total: 0,
    hasAny: false
  }
  details.total = Object.values(details).reduce<number>((sum, rows) => (
    Array.isArray(rows) ? sum + rows.length : sum
  ), 0)
  details.hasAny = details.total > 0
  return details
}

function jsonText(value) {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <section class="archive-review-panel">
    <h3>复盘报告</h3>
    <template v-if="hasReviewContent">
      <div v-if="reviewGameSummary" class="review-summary-strip">
        <span class="review-summary-item review-winner">
          <small>胜方</small><b>{{ winnerLabel(reviewGameSummary.winner || game.winner) }}</b>
        </span>
        <span class="review-summary-item">
          <small>天数</small><b>{{ reviewGameSummary.total_days ?? game.day ?? '—' }}</b>
        </span>
        <span class="review-summary-item">
          <small>事件</small><b>{{ reviewGameSummary.event_count ?? game.event_count ?? game.logs?.length ?? game.events?.length ?? 0 }}</b>
        </span>
        <span class="review-summary-item">
          <small>决策</small><b>{{ reviewGameSummary.decision_count ?? game.decisions?.length ?? 0 }}</b>
        </span>
      </div>

      <div v-else-if="reviewData?.review_status && !reviewScoreCards.length" class="empty-log">
        {{ formatReviewText(reviewData.summary || reviewData.review_status) }}
      </div>

      <section v-if="reviewScoreCards.length" class="review-score-section">
        <header class="review-score-panel-head">
          <div>
            <h4>玩家得分</h4>
            <small :class="['review-score-source', reviewScoreSourceClass]">
              {{ reviewScoreSourceLabel }}
            </small>
          </div>
          <b>{{ reviewScoreCards.length }} 人</b>
        </header>
        <ReviewScoreStackedBar :cards="reviewScoreCards" />
      </section>

      <template v-if="canShowFlowChartGate">
        <VoteFlowSankey v-if="showFlowCharts" :decisions="reviewFlowDecisions" :players="game.players || []" />
        <section v-else class="review-flow-status">
          <header class="review-flow-status-head">
            <h4>流向图</h4>
            <button v-if="flowDataError" type="button" :disabled="flowLoading" @click="retryFlowCharts">
              重试
            </button>
            <small v-else>{{ flowChartStatusLabel }}</small>
          </header>
          <p v-if="flowDataError" class="review-flow-status-copy">
            {{ flowDataError }}
          </p>
          <p v-else-if="flowLoading" class="review-flow-status-copy">
            正在读取投票流向与回合热力图。
          </p>
          <p v-else class="review-flow-status-copy">
            暂无可生成的投票流向或回合热力图。
          </p>
        </section>
      </template>

      <section v-if="showDecisionJudge" class="review-judge-section">
        <header class="review-judge-head">
          <div>
            <small>LLM 决策复盘</small>
            <h4>关键决策评分</h4>
          </div>
          <b>{{ judgeStatusLabel(decisionJudgeData.status) }}</b>
        </header>

        <div class="review-judge-summary">
          <span>
            <small>平均分</small>
            <b>{{ averageScoreText(decisionJudgeSummary.average_score) }}</b>
          </span>
          <span>
            <small>已评审</small>
            <b>{{ decisionJudgeMetrics.judged ?? decisionJudgeSummary.judged ?? decisionJudgeJudgments.length }}</b>
          </span>
          <span>
            <small>候选决策</small>
            <b>{{ decisionJudgeMetrics.key_decisions ?? decisionJudgeData.selection?.key_decisions ?? '—' }}</b>
          </span>
          <span>
            <small>失败</small>
            <b>{{ decisionJudgeMetrics.failed ?? 0 }}</b>
          </span>
        </div>

        <div v-if="decisionJudgeLowestRows.length" class="review-judge-lowest">
          <h4>低分决策</h4>
          <article
            v-for="item in decisionJudgeLowestRows"
            :key="'judge-lowest-' + (item.decision_id || item.player_id || item.action_type)"
            class="review-judge-low-row"
          >
            <header>
              <span>{{ item.player_id ?? '—' }}号</span>
              <em>{{ roleLabel(item.role) }}</em>
              <strong>{{ actionLabel(item.action_type) }}</strong>
              <i :class="qualityClass(item.quality)">{{ qualityLabel(item.quality) }}</i>
              <b>{{ scoreText(item.score) }}</b>
            </header>
            <p>{{ formatReviewText(item.reason) }}</p>
            <p v-if="item.suggestion" class="review-judge-suggestion">{{ formatReviewText(item.suggestion) }}</p>
          </article>
        </div>

        <div v-if="decisionJudgeJudgments.length" class="review-judge-list">
          <article
            v-for="row in decisionJudgeCards"
            :key="row.key"
            class="review-judge-card"
          >
            <header>
              <div>
                <span>{{ row.item.player_id ?? '—' }}号</span>
                <em>{{ roleLabel(row.item.role) }}</em>
                <strong>{{ actionLabel(row.item.action_type) }}</strong>
              </div>
              <b :class="['review-judge-score', qualityClass(row.item.quality)]">
                {{ scoreText(row.item.score) }}
              </b>
            </header>
            <p>{{ formatReviewText(row.item.reason) }}</p>
            <p v-if="row.item.suggestion" class="review-judge-suggestion">{{ formatReviewText(row.item.suggestion) }}</p>
            <JudgeEvidencePanel :evidence="row.evidence" :row-key="row.key" :format-json="formatJson" />
          </article>
        </div>

        <div v-if="decisionJudgeData.warnings?.length" class="review-judge-warnings">
          <span v-for="warning in decisionJudgeData.warnings" :key="'judge-warning-' + warning">
            {{ formatReviewText(warning) }}
          </span>
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
    <pre v-if="!hasReviewContent">{{ jsonText(report) }}</pre>
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
  border-radius: 0;
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

.review-score-source {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  padding: 2px 6px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  line-height: 1.2;
}

.review-score-source.local-estimate {
  border-color: rgba(139, 100, 31, 0.34);
  background: rgba(255, 232, 170, 0.34);
  color: #8b641f;
}

.review-score-source.report {
  border-color: rgba(68, 124, 68, 0.28);
  background: rgba(214, 239, 214, 0.32);
  color: #3f713f;
}

.review-score-panel-head b {
  padding: 2px 8px;
  border-radius: 0;
  background: rgba(139, 94, 52, 0.08);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.review-flow-status {
  display: grid;
  gap: 9px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.42);
}

.review-flow-status-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.review-flow-status-head h4 {
  margin: 0;
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
}

.review-flow-status-head small {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.58);
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 900;
  line-height: 1;
  white-space: nowrap;
}

.review-flow-status-head button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 88px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid rgba(93, 48, 17, 0.22);
  border-radius: 6px;
  color: #3b1c09;
  background: rgba(255, 252, 245, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.46);
  font-size: 12px;
  font-weight: 900;
  line-height: 1;
  cursor: pointer;
}

.review-flow-status-head button:hover {
  border-color: rgba(93, 48, 17, 0.36);
  background: rgba(255, 252, 245, 0.92);
}

.review-flow-status-head button:disabled {
  color: var(--log-accent);
  background: rgba(139, 94, 52, 0.08);
  cursor: default;
}

.review-flow-status-copy {
  margin: 0;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
}

.review-judge-section {
  display: grid;
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 8px;
  background: rgba(255, 239, 194, 0.36);
}

.review-judge-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(93, 48, 17, 0.14);
}

.review-judge-head div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.review-judge-head small,
.review-judge-summary small {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 850;
  line-height: 1;
}

.review-judge-head h4 {
  margin: 0;
  color: var(--log-text);
  font-size: 14px;
  font-weight: 900;
}

.review-judge-head b {
  padding: 3px 8px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--log-accent);
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.review-judge-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
}

.review-judge-summary span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid rgba(93, 48, 17, 0.12);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.46);
}

.review-judge-summary b {
  overflow: hidden;
  color: var(--log-text);
  font-size: 16px;
  font-weight: 950;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-judge-lowest,
.review-judge-list,
.review-judge-warnings {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.review-judge-lowest h4 {
  margin: 2px 0 0;
}

.review-judge-low-row,
.review-judge-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(93, 48, 17, 0.14);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.5);
}

.review-judge-low-row {
  display: grid;
  gap: 7px;
}

.review-judge-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.review-judge-card {
  display: grid;
  align-content: start;
  gap: 8px;
}

.review-judge-low-row header,
.review-judge-card header,
.review-judge-card header div {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.review-judge-card header {
  justify-content: space-between;
}

.review-judge-low-row header span,
.review-judge-card header span {
  display: inline-grid;
  min-width: 34px;
  height: 23px;
  place-items: center;
  border-radius: 999px;
  background: #70401e;
  color: #fff7dc;
  font-size: 11px;
  font-weight: 950;
  white-space: nowrap;
}

.review-judge-low-row header em,
.review-judge-card header em,
.review-judge-low-row header strong,
.review-judge-card header strong,
.review-judge-low-row header i {
  min-width: 0;
  overflow: hidden;
  padding: 3px 7px;
  border-radius: 5px;
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-judge-low-row header em,
.review-judge-card header em {
  background: rgba(112, 64, 30, 0.08);
  color: #70401e;
}

.review-judge-low-row header strong,
.review-judge-card header strong {
  background: rgba(47, 115, 79, 0.1);
  color: #2f734f;
}

.review-judge-low-row header i,
.review-judge-score {
  background: var(--judge-quality-bg, rgba(139, 94, 52, 0.09));
  color: var(--judge-quality-color, var(--log-accent));
}

.review-judge-low-row header b,
.review-judge-score {
  display: inline-grid;
  min-width: 34px;
  height: 26px;
  place-items: center;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 950;
  line-height: 1;
}

.review-judge-low-row header b {
  margin-left: auto;
  color: #9c2f29;
  background: rgba(156, 47, 41, 0.09);
}

.quality-good {
  --judge-quality-color: #237a57;
  --judge-quality-bg: rgba(35, 122, 87, 0.12);
}

.quality-ok {
  --judge-quality-color: #7d6728;
  --judge-quality-bg: rgba(177, 152, 63, 0.16);
}

.quality-bad {
  --judge-quality-color: #a33d35;
  --judge-quality-bg: rgba(163, 61, 53, 0.12);
}

.quality-unknown {
  --judge-quality-color: #5f6f86;
  --judge-quality-bg: rgba(95, 111, 134, 0.12);
}

.review-judge-low-row p,
.review-judge-card p,
.review-judge-warnings span {
  margin: 0;
  color: var(--log-text);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.review-judge-suggestion {
  padding-top: 6px;
  border-top: 1px dashed rgba(93, 48, 17, 0.16);
  color: var(--log-text-secondary) !important;
}

.review-judge-warnings span {
  padding: 7px 9px;
  border: 1px solid rgba(163, 61, 53, 0.16);
  border-radius: 6px;
  background: rgba(163, 61, 53, 0.08);
  color: #8f342d;
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

@media (max-width: 720px) {
  .archive-review-panel {
    padding: 12px;
    border-radius: 8px;
  }

  .review-summary-strip {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .review-judge-summary,
  .review-judge-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .review-cf-confidence {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
  }
}

@media (max-width: 420px) {
  .review-judge-summary,
  .review-judge-list {
    grid-template-columns: minmax(0, 1fr);
  }

  .review-judge-card header,
  .review-judge-card header div {
    flex-wrap: wrap;
  }

  .review-tl-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .review-tl-badge {
    justify-self: start;
  }
}
</style>
