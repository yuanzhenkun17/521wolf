<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import EvidenceContextBar from '../components/history/EvidenceContextBar.vue'
import EvidenceLink from '../components/history/EvidenceLink.vue'
import {
  displaySourceLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.js'
import { buildHashLink } from '../components/history/evidenceLinks.js'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../composables/apiErrorDisplay.js'

const GameArchivePanel = defineAsyncComponent(() => import('../components/history/GameArchivePanel.vue'))
const ReviewReportPanel = defineAsyncComponent(() => import('../components/history/ReviewReportPanel.vue'))

const props = defineProps({
  returnToMatchAvailable: Boolean,
  gameHistory: { type: Array, default: () => [] },
  selectedHistoryGameId: [String, Number, null],
  selectedHistoryGame: Object,
  historyLoading: Boolean,
  historyPagination: { type: Object, default: () => ({}) },
  historyLoadingMore: Boolean,
  historySourceFilter: { type: String, default: 'all' },
  historyStatusFilter: { type: String, default: 'all' },
  historyHasMore: Boolean,
  historyCurrentPage: { type: Number, default: 1 },
  historyTotalPages: { type: Number, default: 1 },
  historyFacets: { type: Object, default: () => ({}) },
  historyNotice: { type: Object, default: () => ({}) },
  archiveByGameId: { type: Object, default: () => ({}) },
  reviewByGameId: { type: Object, default: () => ({}) },
  flowDataByGameId: { type: Object, default: () => ({}) },
  flowLoadingByGameId: { type: Object, default: () => ({}) },
  archiveLoading: Boolean,
  reviewLoading: Boolean,
  selectedHistoryPageKey: { type: String, default: '' },
  detailTab: { type: String, default: 'archive' },
  loadMoreHistory: Function,
  goHistoryPage: Function,
  setHistorySourceFilter: Function,
  setHistoryStatusFilter: Function,
  loadArchive: Function,
  loadReview: Function,
  loadFlowData: Function,
  formatJson: Function
})

const EVIDENCE_PAGE_SIZE = 12
const evidenceSearch = ref('')
const sourceFilterOptions = [
  { key: 'all', label: '全部来源' },
  { key: 'normal', label: '普通对局' },
  { key: 'benchmark', label: 'Benchmark' },
  { key: 'evolution', label: 'Evolution' }
]

const statusLabels = {
  all: '全部状态',
  completed: '已完成',
  running: '运行中',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
  timeout: '超时',
  unknown: '未知'
}

const emit = defineEmits([
  'back-to-match',
  'select-history-game',
  'open-logs',
  'replay-game',
  'update:selectedHistoryPageKey',
  'update:detailTab'
])

const selectedGameId = computed(() =>
  String(props.selectedHistoryGame?.game_id || props.selectedHistoryGameId || '').trim()
)
const selectedArchive = computed(() => selectedGameId.value ? props.archiveByGameId[selectedGameId.value] || null : null)
const selectedReview = computed(() => selectedGameId.value ? props.reviewByGameId[selectedGameId.value] || null : null)
const selectedFlowData = computed(() => selectedGameId.value ? props.flowDataByGameId[selectedGameId.value] || null : null)
const selectedFlowLoading = computed(() => Boolean(selectedGameId.value && props.flowLoadingByGameId[selectedGameId.value]))
const detailInlineNotice = computed(() => inlineNoticeForDisplay(props.historyNotice))
const detailErrorNotice = computed(() => noticeErrorForPanel(props.historyNotice))
const archiveLoaded = computed(() => Boolean(selectedArchive.value && !selectedArchive.value.error))
const reviewLoaded = computed(() => Boolean(selectedReview.value && !selectedReview.value.error))
const archiveState = computed(() => evidenceAssetState({
  loading: props.archiveLoading,
  loaded: archiveLoaded.value,
  error: selectedArchive.value?.error
}))
const reviewState = computed(() => evidenceAssetState({
  loading: props.reviewLoading,
  loaded: reviewLoaded.value,
  error: selectedReview.value?.error
}))

const evidenceRows = computed(() =>
  props.gameHistory
    .map((game, index) => normalizeEvidenceRow(game, index))
    .filter((row) => row.game_id)
)

const normalizedEvidenceSearch = computed(() => normalizeSearchText(evidenceSearch.value))
const filteredEvidenceRows = computed(() => {
  const query = normalizedEvidenceSearch.value
  if (!query) return evidenceRows.value
  return evidenceRows.value.filter((row) => row.searchText.includes(query))
})
const paginatedEvidenceRows = computed(() =>
  filteredEvidenceRows.value.slice(0, EVIDENCE_PAGE_SIZE)
)
const selectedGameOutsideIndex = computed(() =>
  Boolean(selectedGameId.value && !evidenceRows.value.some((row) => row.game_id === selectedGameId.value))
)
const evidenceIndexCountLabel = computed(() => {
  if (props.historyLoading) return '读取中'
  const filtered = filteredEvidenceRows.value.length
  const pageRows = evidenceRows.value.length
  const total = Number(props.historyPagination?.total ?? pageRows) || 0
  if (normalizedEvidenceSearch.value) return `${filtered} / 当前页 ${pageRows}`
  return `${pageRows} / ${total || pageRows} 条`
})
const evidencePageSummary = computed(() => {
  const pagination = props.historyPagination || {}
  const total = Number(pagination.total ?? evidenceRows.value.length) || 0
  if (!total) return '暂无记录'
  const offset = Math.max(0, Number(pagination.offset || 0))
  const returned = Math.max(0, Number(pagination.returned ?? evidenceRows.value.length))
  return `${offset + 1}-${Math.min(total, offset + returned)} / ${total}`
})
const evidenceStatusOptions = computed(() => {
  const statusFacet = props.historyFacets?.status && typeof props.historyFacets.status === 'object'
    ? props.historyFacets.status
    : {}
  const entries = Object.entries(statusFacet)
    .filter(([key]) => key)
    .map(([key, count]) => ({
      key: String(key).toLowerCase(),
      label: statusLabel(key),
      count: Number(count) || 0
    }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  return [{ key: 'all', label: '全部状态', count: Number(props.historyPagination?.total || 0) || evidenceRows.value.length }, ...entries]
})

const evidenceSummary = computed(() => {
  const rows = evidenceRows.value
  const sourceCounts = rows.reduce((counts, row) => {
    counts[row.source] = (counts[row.source] || 0) + 1
    return counts
  }, {})
  return {
    total: rows.length,
    benchmark: sourceCounts.benchmark || 0,
    evolution: sourceCounts.evolution || 0,
    normal: sourceCounts.normal || 0
  }
})

const selectedEvidenceSource = computed(() => {
  const game = props.selectedHistoryGame || {}
  const source = game.evidence_source && typeof game.evidence_source === 'object' ? game.evidence_source : {}
  const sourceType = evidenceSourceType(game, source)
  return {
    ...source,
    history_game_id: game.game_id || source.history_game_id,
    game_id: game.game_id || source.game_id,
    seed: game.seed ?? source.seed,
    winner: game.winner ?? source.winner,
    source: sourceType,
    log_source: sourceType,
    source_run_id: source.source_run_id || game.source_run_id
  }
})

const selectedAssetRows = computed(() => [
  {
    key: 'archive',
    label: 'Archive',
    state: archiveState.value,
    value: archiveLoaded.value ? '已绑定对局档案' : assetFallbackText(selectedArchive.value, '等待读取档案')
  },
  {
    key: 'review',
    label: 'Review',
    state: reviewState.value,
    value: reviewLoaded.value ? '已绑定复盘报告' : assetFallbackText(selectedReview.value, '等待读取复盘')
  },
  {
    key: 'source',
    label: 'Source',
    state: { state: selectedEvidenceSource.value.source ? 'loaded' : 'missing', label: selectedEvidenceSource.value.source ? '已标记' : '缺失' },
    value: displaySourceLabel(selectedEvidenceSource.value.source || props.selectedHistoryGame?.log_source || 'normal')
  }
])

watch(selectedGameId, (gameId) => {
  if (!gameId) return
  if (!selectedArchive.value && !props.archiveLoading) props.loadArchive?.(gameId, { clearNotice: false })
  if (!selectedReview.value && !props.reviewLoading) props.loadReview?.(gameId, { clearNotice: false })
}, { immediate: true })

function evidenceAssetState({ loading = false, loaded = false, error = '' } = {}) {
  if (loading) return { state: 'loading', label: '读取中' }
  if (error) return { state: 'error', label: '错误' }
  if (loaded) return { state: 'loaded', label: '已载入' }
  return { state: 'missing', label: '缺失' }
}

function assetFallbackText(asset, fallback) {
  return asset?.error || fallback
}

function normalizeSearchText(value) {
  return String(value ?? '').trim().toLowerCase()
}

function statusLabel(status) {
  const key = String(status || '').trim().toLowerCase() || 'unknown'
  return statusLabels[key] || key
}

function evidenceSourceType(game, source = {}) {
  return String(
    game?.log_source ||
      source.log_source ||
      game?.source ||
      source.source ||
      game?.kind ||
      'normal'
  ).trim().toLowerCase() || 'normal'
}

function normalizeEvidenceRow(game, index) {
  const source = game?.evidence_source && typeof game.evidence_source === 'object' ? game.evidence_source : {}
  const gameId = String(game?.game_id || game?.id || '').trim()
  const sourceType = evidenceSourceType(game, source)
  const status = String(game?.status || 'unknown').trim().toLowerCase() || 'unknown'
  const title = normalizeHistoryDisplayText(game?.title || game?.log_name || gameId || `证据 ${index + 1}`)
  const winnerLabel = displayWinnerLabel(game?.winner || source.winner || '')
  const runId = source.source_run_id || source.run_id || game?.source_run_id || ''
  const proposalId = source.proposal_id || game?.proposal_id || ''
  const seed = game?.seed ?? source.seed ?? ''
  return {
    ...game,
    game_id: gameId,
    key: gameId || `evidence-${index}`,
    source: sourceType || 'normal',
    sourceLabel: displaySourceLabel(sourceType || 'normal'),
    title,
    status,
    statusLabel: statusLabel(status),
    winnerLabel,
    runId,
    proposalId,
    seed,
    href: buildHashLink('evidence', { game_id: gameId }),
    searchText: normalizeSearchText([
      gameId,
      title,
      sourceType,
      displaySourceLabel(sourceType),
      status,
      statusLabel(status),
      winnerLabel,
      runId,
      proposalId,
      seed
    ].filter(Boolean).join(' '))
  }
}

function selectEvidence(row) {
  if (!row?.game_id) return
  if (typeof window !== 'undefined') window.location.hash = row.href
  emit('select-history-game', row.game_id)
}

function openSelectedLogs() {
  if (!selectedGameId.value) return
  emit('open-logs', selectedGameId.value)
}

function replaySelected() {
  if (props.selectedHistoryGame) emit('replay-game', props.selectedHistoryGame)
}

function loadSelectedFlowData() {
  if (!selectedGameId.value) return null
  return props.loadFlowData?.(selectedGameId.value, { clearNotice: false })
}

function changeSourceFilter(event) {
  props.setHistorySourceFilter?.(event?.target?.value || 'all')
}

function changeStatusFilter(event) {
  props.setHistoryStatusFilter?.(event?.target?.value || 'all')
}

function goEvidencePage(page) {
  props.goHistoryPage?.(page, { resetSelection: false })
}

function loadMoreEvidenceRows() {
  props.loadMoreHistory?.()
}
</script>

<template>
  <section class="evidence-page" data-evidence-archive-page>
    <header class="evidence-page-header">
      <div>
        <span class="evidence-kicker">Evidence Archive</span>
        <h1>证据档案</h1>
      </div>
      <div class="evidence-header-actions">
        <button
          v-if="returnToMatchAvailable"
          type="button"
          class="evidence-ghost-action"
          @click="emit('back-to-match')"
        >
          返回对局
        </button>
        <button
          type="button"
          class="evidence-ghost-action"
          :disabled="!selectedGameId"
          @click="openSelectedLogs"
        >
          打开日志工作台
        </button>
      </div>
    </header>

    <ApiErrorPanel
      v-if="detailErrorNotice"
      class="evidence-error-panel"
      :error="detailErrorNotice"
      title="证据档案读取失败"
    />
    <div v-else-if="detailInlineNotice" class="evidence-inline-notice" :data-type="detailInlineNotice.type">
      {{ detailInlineNotice.message }}
    </div>

    <section class="evidence-summary-grid" aria-label="证据索引摘要">
      <div>
        <small>索引证据</small>
        <b>{{ evidenceSummary.total }}</b>
      </div>
      <div>
        <small>Benchmark</small>
        <b>{{ evidenceSummary.benchmark }}</b>
      </div>
      <div>
        <small>Evolution</small>
        <b>{{ evidenceSummary.evolution }}</b>
      </div>
      <div>
        <small>普通对局</small>
        <b>{{ evidenceSummary.normal }}</b>
      </div>
    </section>

    <div class="evidence-workbench">
      <aside class="evidence-index" aria-label="证据索引">
        <header>
          <strong>Evidence Index</strong>
          <span>{{ evidenceIndexCountLabel }}</span>
        </header>
        <section class="evidence-filter-bar" aria-label="证据筛选">
          <label>
            <span>全局搜索</span>
            <input
              v-model="evidenceSearch"
              type="search"
              placeholder="搜索 game / run / seed / 状态"
              aria-label="全局搜索证据"
            />
          </label>
          <label>
            <span>来源筛选</span>
            <select
              :value="historySourceFilter"
              data-filter="source"
              aria-label="来源筛选"
              @change="changeSourceFilter"
            >
              <option v-for="item in sourceFilterOptions" :key="item.key" :value="item.key">
                {{ item.label }}
              </option>
            </select>
          </label>
          <label>
            <span>状态筛选</span>
            <select
              :value="historyStatusFilter"
              data-filter="status"
              aria-label="状态筛选"
              @change="changeStatusFilter"
            >
              <option v-for="item in evidenceStatusOptions" :key="item.key" :value="item.key">
                {{ item.label }}{{ item.count ? ` (${item.count})` : '' }}
              </option>
            </select>
          </label>
        </section>
        <div
          v-if="selectedGameOutsideIndex"
          class="evidence-index-note"
          data-selected-outside-index
        >
          当前详情来自 URL 指定证据，不在本页索引范围内。
        </div>
        <div v-if="!evidenceRows.length" class="evidence-empty">
          <b>暂无证据局</b>
          <span>进入 History、Benchmark 或 Evolution 后会在这里看到可审计样本。</span>
        </div>
        <div v-else-if="!filteredEvidenceRows.length" class="evidence-empty">
          <b>当前筛选无结果</b>
          <span>调整搜索词、来源或状态后继续查看当前证据页。</span>
        </div>
        <a
          v-for="row in paginatedEvidenceRows"
          :key="row.key"
          class="evidence-index-row"
          :class="{ active: row.game_id === selectedGameId }"
          :href="row.href"
          :aria-current="row.game_id === selectedGameId ? 'page' : undefined"
          @click.prevent="selectEvidence(row)"
        >
          <span class="evidence-row-source" :data-source="row.source">{{ row.sourceLabel }}</span>
          <strong>{{ row.title }}</strong>
          <small>
            <span v-if="row.winnerLabel">胜方 {{ row.winnerLabel }}</span>
            <span>{{ row.statusLabel }}</span>
            <span v-if="row.seed">seed {{ row.seed }}</span>
            <span v-if="row.runId">run {{ row.runId }}</span>
          </small>
        </a>
        <footer class="evidence-pagination" aria-label="证据分页">
          <span>{{ evidencePageSummary }}</span>
          <div>
            <button
              type="button"
              class="evidence-ghost-action"
              :disabled="historyLoading || historyLoadingMore || historyCurrentPage <= 1"
              aria-label="上一页"
              @click="goEvidencePage(historyCurrentPage - 1)"
            >
              上一页
            </button>
            <small>第 {{ historyCurrentPage }} / {{ historyTotalPages }} 页</small>
            <button
              type="button"
              class="evidence-ghost-action"
              :disabled="historyLoading || historyLoadingMore || historyCurrentPage >= historyTotalPages"
              aria-label="下一页"
              @click="goEvidencePage(historyCurrentPage + 1)"
            >
              下一页
            </button>
          </div>
          <button
            type="button"
            class="evidence-primary-action"
            :disabled="historyLoading || historyLoadingMore || !historyHasMore"
            @click="loadMoreEvidenceRows"
          >
            {{ historyLoadingMore ? '加载中' : '加载更多' }}
          </button>
        </footer>
      </aside>

      <section class="evidence-detail" aria-label="证据详情">
        <div v-if="!selectedHistoryGame" class="evidence-empty evidence-empty--detail">
          <b>{{ historyLoading ? '正在读取证据档案' : '选择一条证据' }}</b>
          <span>Evidence Archive 只提供只读索引、来源跳转和审计上下文，不提供删除入口。</span>
        </div>

        <template v-else>
          <EvidenceContextBar
            class="evidence-context"
            :source="selectedHistoryGame"
            :game="selectedHistoryGame"
          />

          <section class="evidence-authority-strip" aria-label="证据资产状态">
            <div
              v-for="item in selectedAssetRows"
              :key="item.key"
              class="evidence-asset-cell"
              :data-state="item.state.state"
            >
              <small>{{ item.label }}</small>
              <b>{{ item.state.label }}</b>
              <span>{{ item.value }}</span>
            </div>
          </section>

          <section class="evidence-link-strip" aria-label="证据跳转">
            <EvidenceLink :target="selectedEvidenceSource" kind="game" label="Archive" />
            <EvidenceLink :target="selectedEvidenceSource" kind="run" label="Run" />
            <EvidenceLink :target="selectedEvidenceSource" kind="proposal" label="Proposal" />
            <EvidenceLink :target="selectedEvidenceSource" kind="gate" label="Gate" />
          </section>

          <div class="evidence-detail-actions">
            <button
              type="button"
              class="evidence-primary-action"
              :disabled="archiveLoading"
              @click="loadArchive?.(selectedGameId, { clearNotice: false })"
            >
              {{ archiveLoading ? '读取中' : '刷新 Archive' }}
            </button>
            <button
              type="button"
              class="evidence-primary-action"
              :disabled="reviewLoading"
              @click="loadReview?.(selectedGameId, { clearNotice: false })"
            >
              {{ reviewLoading ? '读取中' : '刷新 Review' }}
            </button>
            <button type="button" class="evidence-ghost-action" @click="replaySelected">
              回放
            </button>
          </div>

          <div class="evidence-panels">
            <section class="evidence-panel">
              <header>
                <strong>Archive</strong>
                <span :data-state="archiveState.state">{{ archiveState.label }}</span>
              </header>
              <GameArchivePanel
                v-if="selectedArchive"
                :archive="selectedArchive"
                :game="selectedHistoryGame"
                :format-json="formatJson"
              />
              <div v-else class="evidence-empty">
                <b>Archive 未载入</b>
                <span>刷新后展示决策来源、错误回退和智能体档案字段。</span>
              </div>
            </section>

            <section class="evidence-panel">
              <header>
                <strong>Review</strong>
                <span :data-state="reviewState.state">{{ reviewState.label }}</span>
              </header>
              <ReviewReportPanel
                v-if="selectedReview"
                :report="selectedReview"
                :game="selectedHistoryGame"
                :flow-data="selectedFlowData"
                :flow-loading="selectedFlowLoading"
                :load-flow-data="loadSelectedFlowData"
                :format-json="formatJson"
              />
              <div v-else class="evidence-empty">
                <b>Review 未载入</b>
                <span>刷新后展示复盘报告、judge 证据和投票/决策脉络。</span>
              </div>
            </section>
          </div>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.evidence-page {
  min-height: 100vh;
  padding: 96px clamp(14px, 2.6vw, 32px) 32px;
  color: #2a2118;
  background:
    linear-gradient(180deg, rgba(255, 252, 243, 0.96), rgba(243, 239, 227, 0.98)),
    #f8f3e7;
}

.evidence-page-header,
.evidence-workbench,
.evidence-summary-grid,
.evidence-detail {
  min-width: 0;
}

.evidence-page-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  max-width: 1480px;
  margin: 0 auto 16px;
}

.evidence-kicker {
  display: block;
  color: #6d7b5d;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.evidence-page h1 {
  margin: 2px 0 0;
  font-size: 28px;
  line-height: 1.1;
}

.evidence-header-actions,
.evidence-detail-actions,
.evidence-link-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.evidence-ghost-action,
.evidence-primary-action {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 850;
  cursor: pointer;
}

.evidence-ghost-action {
  border: 1px solid rgba(58, 42, 24, 0.16);
  color: #4c3a24;
  background: rgba(255, 252, 243, 0.74);
}

.evidence-primary-action {
  border: 1px solid rgba(92, 112, 76, 0.28);
  color: #263422;
  background: rgba(118, 164, 111, 0.18);
}

.evidence-ghost-action:disabled,
.evidence-primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.evidence-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  max-width: 1480px;
  margin: 0 auto 14px;
}

.evidence-summary-grid > div,
.evidence-asset-cell,
.evidence-index,
.evidence-detail,
.evidence-empty {
  border: 1px solid rgba(58, 42, 24, 0.12);
  border-radius: 8px;
  background: rgba(255, 252, 243, 0.74);
}

.evidence-summary-grid > div {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
}

.evidence-summary-grid small,
.evidence-asset-cell small {
  color: rgba(42, 33, 24, 0.58);
  font-size: 11px;
  font-weight: 850;
}

.evidence-summary-grid b,
.evidence-asset-cell b {
  color: #2e3e29;
  font-size: 18px;
  line-height: 1;
}

.evidence-workbench {
  display: grid;
  grid-template-columns: minmax(260px, 0.33fr) minmax(0, 1fr);
  gap: 12px;
  max-width: 1480px;
  margin: 0 auto;
}

.evidence-index {
  align-self: start;
  display: grid;
  gap: 8px;
  max-height: calc(100vh - 164px);
  overflow: auto;
  padding: 10px;
}

.evidence-index header,
.evidence-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.evidence-index header strong,
.evidence-panel > header strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-index header span,
.evidence-panel > header span {
  flex: 0 0 auto;
  color: rgba(42, 33, 24, 0.58);
  font-size: 12px;
  font-weight: 820;
}

.evidence-filter-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
}

.evidence-filter-bar label {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.evidence-filter-bar label span,
.evidence-pagination small,
.evidence-pagination > span,
.evidence-index-note {
  color: rgba(42, 33, 24, 0.58);
  font-size: 11px;
  font-weight: 850;
}

.evidence-filter-bar input,
.evidence-filter-bar select {
  width: 100%;
  min-width: 0;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(58, 42, 24, 0.16);
  border-radius: 7px;
  color: #2a2118;
  background: rgba(255, 255, 255, 0.68);
  font: inherit;
  font-size: 13px;
  font-weight: 760;
}

.evidence-index-note {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(190, 153, 69, 0.22);
  border-radius: 7px;
  color: #6a5428;
  background: rgba(190, 153, 69, 0.12);
}

.evidence-index-row {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(58, 42, 24, 0.1);
  border-radius: 7px;
  color: inherit;
  background: rgba(255, 255, 255, 0.52);
  text-decoration: none;
}

.evidence-index-row.active {
  border-color: rgba(92, 112, 76, 0.34);
  background: rgba(118, 164, 111, 0.14);
  box-shadow: inset 3px 0 0 rgba(92, 112, 76, 0.42);
}

.evidence-index-row strong,
.evidence-index-row small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-index-row strong {
  font-size: 13px;
}

.evidence-index-row small {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: rgba(42, 33, 24, 0.62);
  font-size: 11px;
  font-weight: 750;
}

.evidence-row-source {
  width: fit-content;
  max-width: 100%;
  overflow: hidden;
  padding: 2px 7px;
  border-radius: 999px;
  color: #314028;
  background: rgba(118, 164, 111, 0.17);
  font-size: 11px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-row-source[data-source="evolution"] {
  color: #315061;
  background: rgba(84, 148, 176, 0.16);
}

.evidence-row-source[data-source="benchmark"] {
  color: #5e4b21;
  background: rgba(190, 153, 69, 0.18);
}

.evidence-pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding-top: 8px;
  border-top: 1px solid rgba(58, 42, 24, 0.1);
}

.evidence-pagination > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
}

.evidence-detail {
  display: grid;
  gap: 12px;
  padding: 12px;
}

.evidence-context {
  margin: 0;
}

.evidence-authority-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.evidence-asset-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
}

.evidence-asset-cell span {
  min-width: 0;
  overflow: hidden;
  color: rgba(42, 33, 24, 0.66);
  font-size: 12px;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-asset-cell[data-state="error"] b {
  color: #8f342e;
}

.evidence-asset-cell[data-state="missing"] b {
  color: #80613a;
}

.evidence-link-strip {
  padding: 8px;
  border: 1px solid rgba(58, 42, 24, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.46);
}

.evidence-panels {
  display: grid;
  gap: 12px;
}

.evidence-panel {
  min-width: 0;
  overflow: hidden;
}

.evidence-panel > header {
  margin-bottom: 8px;
  padding: 0 2px;
}

.evidence-panel > header span[data-state="loaded"] {
  color: #3e6a38;
}

.evidence-panel > header span[data-state="error"] {
  color: #8f342e;
}

.evidence-empty {
  display: grid;
  gap: 5px;
  padding: 14px;
}

.evidence-empty b {
  color: #2a2118;
  font-size: 14px;
}

.evidence-empty span,
.evidence-inline-notice {
  color: rgba(42, 33, 24, 0.64);
  font-size: 13px;
  font-weight: 720;
}

.evidence-empty--detail {
  min-height: 280px;
  place-content: center;
  text-align: center;
}

.evidence-error-panel,
.evidence-inline-notice {
  max-width: 1480px;
  margin: 0 auto 12px;
}

.evidence-inline-notice {
  padding: 10px 12px;
  border: 1px solid rgba(58, 42, 24, 0.12);
  border-radius: 8px;
  background: rgba(255, 252, 243, 0.76);
}

@media (max-width: 1040px) {
  .evidence-workbench {
    grid-template-columns: 1fr;
  }

  .evidence-index {
    max-height: none;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  }

  .evidence-index header,
  .evidence-filter-bar,
  .evidence-index-note,
  .evidence-pagination,
  .evidence-empty {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .evidence-page {
    padding: calc(78px + env(safe-area-inset-top, 0px)) 10px calc(18px + env(safe-area-inset-bottom, 0px));
  }

  .evidence-page-header {
    align-items: stretch;
    flex-direction: column;
  }

  .evidence-summary-grid,
  .evidence-authority-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evidence-detail-actions > button,
  .evidence-header-actions > button {
    flex: 1 1 140px;
  }

  .evidence-pagination {
    align-items: stretch;
  }

  .evidence-pagination > div,
  .evidence-pagination > button {
    flex: 1 1 100%;
  }
}

@media (max-width: 460px) {
  .evidence-summary-grid,
  .evidence-authority-strip {
    grid-template-columns: 1fr;
  }

  .evidence-index {
    grid-template-columns: 1fr;
  }
}
</style>
