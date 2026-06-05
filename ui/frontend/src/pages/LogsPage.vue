<script setup>
import { computed, ref } from 'vue'
import HistoryGameList from '../components/HistoryGameList.vue'
import MultiAssess from '../components/MultiAssess.vue'
import NightSection from '../components/NightSection.vue'
import PhaseTabs from '../components/PhaseTabs.vue'
import ReplayControls from '../components/ReplayControls.vue'
import SeatLedger from '../components/SeatLedger.vue'
import SpeechSection from '../components/SpeechSection.vue'
import VoteSection from '../components/VoteSection.vue'

const props = defineProps({
  returnToMatchAvailable: Boolean,
  gameHistory: { type: Array, default: () => [] },
  selectedHistoryGameId: [String, Number, null],
  selectedHistoryGame: Object,
  historyLoading: Boolean,
  historyPages: { type: Array, default: () => [] },
  selectedHistoryPageKey: { type: String, default: '' },
  selectedHistoryPage: Object,
  historyLogs: { type: Array, default: () => [] },
  pageNightActions: { type: Array, default: () => [] },
  pageSpeechDecisions: { type: Array, default: () => [] },
  sheriffVotes: { type: Array, default: () => [] },
  voteDecisions: { type: Array, default: () => [] },
  currentVoteTally: { type: Array, default: () => [] },
  sheriffVoteTally: { type: Array, default: () => [] },
  pageLastWords: { type: Array, default: () => [] },
  nightResult: { type: String, default: '' },
  sheriffResult: Object,
  isReplayMode: Boolean,
  assessDimension: { type: String, default: 'speech' },
  playerAssessmentScores: { type: Array, default: () => [] },
  activeAssessScores: { type: Array, default: () => [] },
  selectedDecision: Object,
  detailTab: { type: String, default: 'summary' },
  roleIconImage: Function,
  historyPageTitle: Function,
  historyPhaseName: Function,
  historyLogSpeaker: Function,
  historyNormalizeText: Function,
  nightActionDetail: Function,
  playerAliveAtPage: { type: Object, default: () => ({}) },
  archiveByGameId: { type: Object, default: () => ({}) },
  reviewByGameId: { type: Object, default: () => ({}) },
  archiveLoading: Boolean,
  reviewLoading: Boolean,
  loadArchive: Function,
  loadReview: Function,
  formatJson: Function
})

const emit = defineEmits([
  'back-to-match',
  'select-history-game',
  'replay-game',
  'select-page',
  'update:selectedHistoryPageKey',
  'update:assessDimension',
  'update:selectedDecision',
  'update:detailTab',
  'return-to-history',
  'exit-replay'
])

const rawLogFilter = ref('')
const structuredRawPhases = new Set(['night', 'sheriff', 'sheriff_result', 'vote', 'sheriff_vote'])
const canShowRawLogs = computed(() =>
  props.historyLogs.length > 0
  && props.selectedHistoryPage
  && !structuredRawPhases.has(props.selectedHistoryPage.phase)
)
const filteredRawLogs = computed(() => {
  const query = rawLogFilter.value.trim().toLowerCase()
  if (!query) return props.historyLogs
  return props.historyLogs.filter((log) =>
    [
      log.sequence,
      log.event_type,
      log.type,
      log.source,
      log.phase,
      log.speaker,
      log.message
    ].some((value) => String(value || '').toLowerCase().includes(query))
  )
})
const visibleRawLogs = computed(() => filteredRawLogs.value.slice(0, 180))
const selectedReview = computed(() => props.reviewByGameId[props.selectedHistoryGame?.game_id] || null)
const selectedArchive = computed(() => props.archiveByGameId[props.selectedHistoryGame?.game_id] || null)
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
const historyConfigItems = computed(() => {
  const config = selectedGameConfig.value
  const roleSkillDirs = config.role_skill_dirs && typeof config.role_skill_dirs === 'object'
    ? config.role_skill_dirs
    : {}
  const roleOverrideCount = Object.values(roleSkillDirs).filter(Boolean).length
  return [
    { label: 'Seed', value: config.seed ?? '随机' },
    { label: '人数', value: config.player_count || props.selectedHistoryGame?.players?.length || 12 },
    { label: '最大天数', value: config.max_days || 20 },
    { label: '警长', value: config.enable_sheriff === false ? '关闭' : '开启' },
    { label: '技能目录', value: config.skill_dir || 'baseline' },
    { label: '角色覆盖', value: roleOverrideCount ? `${roleOverrideCount} 个` : '无' }
  ]
})
const reviewLoaded = computed(() => Boolean(selectedReview.value && !selectedReview.value.error))
const archiveLoaded = computed(() => Boolean(selectedArchive.value && !selectedArchive.value.error))

// Structured review data extraction
const reviewData = computed(() => {
  const raw = selectedReview.value
  if (!raw || raw.error) return null
  return raw.data || raw
})
const reviewGameSummary = computed(() => reviewData.value?.game_summary || null)
const reviewPlayerScores = computed(() =>
  reviewData.value?.player_evaluations || reviewData.value?.player_scores || []
)
const reviewTurningPoints = computed(() => reviewData.value?.turning_points || [])
const reviewCounterfactuals = computed(() =>
  reviewData.value?.counterfactuals || []
)
const reviewTimeline = computed(() => reviewData.value?.timeline || [])

// Structured archive data extraction
const archiveData = computed(() => {
  const raw = selectedArchive.value
  if (!raw || raw.error) return null
  return raw.data || raw
})
const archiveDecisionCount = computed(() => archiveData.value?.decision_count ?? archiveData.value?.total_decisions ?? 0)
const archiveErrorCount = computed(() => archiveData.value?.error_count ?? archiveData.value?.errors ?? 0)
const archiveFallbackCount = computed(() => archiveData.value?.fallback_count ?? archiveData.value?.fallbacks ?? 0)
const archiveDecisionSources = computed(() => {
  const sources = archiveData.value?.decision_sources
  if (!sources) return null
  if (typeof sources === 'object' && !Array.isArray(sources)) {
    return Object.entries(sources).map(([key, value]) => ({ source: key, count: value }))
  }
  if (Array.isArray(sources)) return sources
  return null
})
const archiveExtraFields = computed(() => {
  const data = archiveData.value
  if (!data || typeof data !== 'object') return []
  const knownKeys = new Set([
    'decision_count', 'total_decisions', 'error_count', 'errors',
    'fallback_count', 'fallbacks', 'decision_sources',
    'agent_name', 'name', 'data', 'error'
  ])
  return Object.entries(data)
    .filter(([key]) => !knownKeys.has(key))
    .map(([key, value]) => ({
      key,
      value: typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
    }))
    .slice(0, 12)
})

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
  if (!phase) return ''
  const map = { night: '夜晚', day: '白天', speech: '发言', vote: '投票', sheriff: '警长竞选' }
  return map[String(phase).toLowerCase()] || phase
}

function confidencePercent(value) {
  if (value == null) return 50
  const num = Number(value)
  if (!Number.isFinite(num)) return 50
  return Math.round(Math.max(0, Math.min(num, 1)) * 100)
}

const reviewButtonText = computed(() => {
  if (props.reviewLoading) return '读取中'
  if (reviewLoaded.value) return '复盘已载入'
  return selectedReview.value?.error ? '重试复盘' : '复盘报告'
})
const archiveButtonText = computed(() => {
  if (props.archiveLoading) return '读取中'
  if (archiveLoaded.value) return '档案已载入'
  return selectedArchive.value?.error ? '重试档案' : '智能体档案'
})

function phaseName(phase) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : (phase || '未知阶段')
}

function pageTitle(page) {
  return props.historyPageTitle ? props.historyPageTitle(page) : page.key
}

function logSpeaker(log) {
  return props.historyLogSpeaker ? props.historyLogSpeaker(log) : (log?.speaker || '系统')
}

function normalizeText(text) {
  return props.historyNormalizeText ? props.historyNormalizeText(text) : (text || '')
}

function jsonText(value) {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}

function updatePage(key) {
  emit('update:selectedHistoryPageKey', key)
  emit('select-page', key)
}

function updateDecision(decision) {
  emit('update:selectedDecision', decision)
}

function updateDetailTab(tab) {
  emit('update:detailTab', tab)
}

function loadSelectedReview() {
  props.loadReview?.(props.selectedHistoryGame?.game_id)
}

function loadSelectedArchive() {
  props.loadArchive?.(props.selectedHistoryGame?.game_id)
}
</script>

<template>
  <section class="battle-log-page" aria-label="对战日志">
    <button v-if="returnToMatchAvailable" class="return-match-button" @click="emit('back-to-match')">
      <span>返回对局</span>
      <i aria-hidden="true">▶</i>
    </button>
    <section class="battle-log-shell parchment-logbook">
      <HistoryGameList
        :games="gameHistory"
        :selected-game-id="selectedHistoryGameId"
        :loading="historyLoading"
        @select-game="emit('select-history-game', $event)"
        @replay-game="emit('replay-game', $event)"
      />

      <main class="history-detail-panel">
        <MultiAssess
          v-if="selectedHistoryGame && playerAssessmentScores.length"
          :scores="activeAssessScores"
          :dimension="assessDimension"
          :role-icon-image="props.roleIconImage"
          @update:dimension="emit('update:assessDimension', $event)"
        />

        <header v-if="selectedHistoryGame" class="history-detail-header">
          <span>事实推演</span>
          <div class="history-detail-actions">
            <button
              type="button"
              :disabled="reviewLoading || reviewLoaded"
              @click="loadSelectedReview"
            >
              {{ reviewButtonText }}
            </button>
            <button
              type="button"
              :disabled="archiveLoading || archiveLoaded"
              @click="loadSelectedArchive"
            >
              {{ archiveButtonText }}
            </button>
          </div>
        </header>
        <section v-if="selectedHistoryGame" class="history-config-strip" aria-label="对局配置">
          <span v-for="item in historyConfigItems" :key="item.label">
            <small>{{ item.label }}</small>
            <b :title="String(item.value)">{{ item.value }}</b>
          </span>
        </section>
        <SeatLedger
          v-if="selectedHistoryGame"
          :players="selectedHistoryGame.players || []"
          :alive-map="playerAliveAtPage"
          :sheriff-id="selectedHistoryGame.sheriff_id"
          :selected-page="selectedHistoryPage"
          :role-icon-image="props.roleIconImage"
        />
        <PhaseTabs
          v-if="selectedHistoryGame"
          :pages="historyPages"
          :selected-page-key="selectedHistoryPage?.key || selectedHistoryPageKey"
          :page-title="pageTitle"
          @update:selectedPageKey="updatePage"
        />

        <section v-if="selectedHistoryGame && selectedHistoryPage" class="history-page-detail">
          <NightSection
            v-if="selectedHistoryPage.phase === 'night'"
            :night-actions="pageNightActions"
            :night-result="nightResult"
            :selected-decision="selectedDecision"
            :detail-tab="detailTab"
            :night-action-detail="nightActionDetail"
            @update:selectedDecision="updateDecision"
            @update:detailTab="updateDetailTab"
          />
          <SpeechSection
            v-if="['speech', 'sheriff'].includes(selectedHistoryPage.phase)"
            :decisions="pageSpeechDecisions"
            :selected-decision="selectedDecision"
            :detail-tab="detailTab"
            @update:selectedDecision="updateDecision"
            @update:detailTab="updateDetailTab"
          />
          <VoteSection
            v-if="selectedHistoryPage.phase === 'sheriff_result'"
            :decisions="sheriffVotes"
            :tally="sheriffVoteTally"
            :result-message="sheriffResult?.message || ''"
            :selected-decision="selectedDecision"
            :detail-tab="detailTab"
            @update:selectedDecision="updateDecision"
            @update:detailTab="updateDetailTab"
          />
          <VoteSection
            v-if="['vote', 'sheriff_vote'].includes(selectedHistoryPage.phase)"
            :decisions="voteDecisions"
            :tally="currentVoteTally"
            :selected-decision="selectedDecision"
            :detail-tab="detailTab"
            @update:selectedDecision="updateDecision"
            @update:detailTab="updateDetailTab"
          />

          <section v-if="pageLastWords.length" class="history-lastwords-section">
            <div v-for="(word, index) in pageLastWords" :key="'last-word-' + index" class="last-word-card">
              <header>
                <span class="last-word-actor">{{ word.actorName }}玩家</span>
                <span class="last-word-role">{{ word.roleName }}</span>
                <span class="last-word-label">遗言</span>
              </header>
              <p class="last-word-message">{{ word.public_summary || word.reason }}</p>
              <details class="last-word-decision">
                <summary>决策过程</summary>
                <small v-if="word.private_reasoning || word.reason">{{ word.private_reasoning || word.reason }}</small>
                <small v-if="word.candidates?.length">
                  候选：{{ word.candidates.map((item) => item.seat + '号' + item.role).join('、') }}
                </small>
              </details>
            </div>
          </section>

          <section
            v-if="canShowRawLogs"
            class="history-raw-section"
          >
            <div class="history-raw-tools">
              <input v-model="rawLogFilter" type="search" placeholder="筛选日志 / 类型 / 来源" />
              <span>{{ visibleRawLogs.length }} / {{ filteredRawLogs.length }}</span>
            </div>
            <div v-if="!filteredRawLogs.length" class="empty-log">没有匹配的日志</div>
            <article
              v-for="(log, index) in visibleRawLogs"
              :key="'raw-log-' + (log.sequence || log.event_type || log.type || index)"
              class="history-raw-log"
            >
              <template v-if="log.role_assignments">
                <p class="role-assignment-title">角色分配如下</p>
                <div class="role-assignment-grid">
                  <div v-for="item in log.role_assignments" :key="item.seat" class="role-assignment-cell">
                    <span class="ra-seat">{{ item.seat }}号</span>
                    <span class="ra-role">{{ item.role }}</span>
                  </div>
                </div>
              </template>
              <template v-else>
                <header>
                  <b>#{{ log.sequence || '-' }}</b>
                  <span>DAY {{ log.day || selectedHistoryPage.day }} · {{ phaseName(log.phase || selectedHistoryPage.phase) }}</span>
                  <em>{{ logSpeaker(log) || log.speaker || '系统' }}</em>
                </header>
                <p>{{ normalizeText(log.message || '') }}</p>
                <small v-if="log.type || log.event_type">
                  type: {{ log.type || log.event_type }}<template v-if="log.source"> · source: {{ log.source }}</template>
                </small>
              </template>
            </article>
            <div v-if="filteredRawLogs.length > visibleRawLogs.length" class="history-raw-more">
              继续筛选可查看其余 {{ filteredRawLogs.length - visibleRawLogs.length }} 条
            </div>
          </section>

          <section v-if="reviewByGameId[selectedHistoryGame.game_id]" class="archive-review-panel">
            <h3>复盘报告</h3>

            <!-- Structured review display -->
            <template v-if="reviewData">
              <!-- Game Summary Strip -->
              <div v-if="reviewGameSummary" class="review-summary-strip">
                <span v-if="reviewGameSummary.winner" class="review-summary-item review-winner">
                  <small>胜方</small>
                  <b>{{ reviewGameSummary.winner }}</b>
                </span>
                <span v-if="reviewGameSummary.total_days != null" class="review-summary-item">
                  <small>总天数</small>
                  <b>{{ reviewGameSummary.total_days }}</b>
                </span>
                <span v-if="reviewGameSummary.total_deaths != null" class="review-summary-item">
                  <small>死亡人数</small>
                  <b>{{ reviewGameSummary.total_deaths }}</b>
                </span>
                <span v-if="reviewGameSummary.mvp" class="review-summary-item">
                  <small>MVP</small>
                  <b>{{ reviewGameSummary.mvp }}</b>
                </span>
                <template v-for="(val, key) in reviewGameSummary" :key="'gs-extra-' + key">
                  <span
                    v-if="!['winner','total_days','total_deaths','mvp'].includes(key)"
                    class="review-summary-item"
                  >
                    <small>{{ key }}</small>
                    <b>{{ val }}</b>
                  </span>
                </template>
              </div>

              <!-- Player Scores Table -->
              <div v-if="reviewPlayerScores.length" class="review-player-scores">
                <h4>玩家评分</h4>
                <div class="review-score-table">
                  <div v-for="ps in reviewPlayerScores" :key="'ps-' + (ps.player_seat || ps.seat)" class="review-score-row">
                    <span class="review-seat">{{ ps.player_seat || ps.seat }}号</span>
                    <span v-if="ps.role" class="review-role">{{ ps.role }}</span>
                    <span v-if="ps.speech_score != null" class="review-dim" title="发言">
                      <small>发言</small><b>{{ Math.round(ps.speech_score * 100) }}</b>
                    </span>
                    <span v-if="ps.vote_score != null" class="review-dim" title="投票">
                      <small>投票</small><b>{{ Math.round(ps.vote_score * 100) }}</b>
                    </span>
                    <span v-if="ps.skill_score != null" class="review-dim" title="技能">
                      <small>技能</small><b>{{ Math.round(ps.skill_score * 100) }}</b>
                    </span>
                    <span v-if="ps.logic_score != null" class="review-dim" title="逻辑">
                      <small>逻辑</small><b>{{ Math.round(ps.logic_score * 100) }}</b>
                    </span>
                    <span v-if="ps.team_score != null" class="review-dim" title="团队">
                      <small>团队</small><b>{{ Math.round(ps.team_score * 100) }}</b>
                    </span>
                    <span v-if="ps.role_score != null" class="review-dim review-role-score" title="综合分">
                      <small>综合</small><b>{{ Math.round(ps.role_score * 100) }}</b>
                    </span>
                  </div>
                </div>
              </div>

              <!-- Turning Points -->
              <div v-if="reviewTurningPoints.length" class="review-turning-points">
                <h4>关键转折</h4>
                <div v-for="(tp, idx) in reviewTurningPoints" :key="'tp-' + idx" class="review-tp-card">
                  <div class="review-tp-badges">
                    <span class="review-day-badge">Day {{ tp.day || '?' }}</span>
                    <span v-if="tp.phase" class="review-phase-badge">{{ phaseLabel(tp.phase) || tp.phase }}</span>
                    <span v-if="tp.impact" :class="['review-impact-badge', impactClass(tp.impact)]">{{ impactLabel(tp.impact) }}</span>
                  </div>
                  <p class="review-tp-desc">{{ tp.description }}</p>
                </div>
              </div>

              <!-- Counterfactuals -->
              <div v-if="reviewCounterfactuals.length" class="review-counterfactuals">
                <h4>反事实推演</h4>
                <div v-for="(cf, idx) in reviewCounterfactuals" :key="'cf-' + idx" class="review-cf-card">
                  <p class="review-cf-whatif"><strong>如果：</strong>{{ cf.what_if }}</p>
                  <p class="review-cf-outcome"><strong>可能结果：</strong>{{ cf.likely_outcome }}</p>
                  <div v-if="cf.confidence != null" class="review-cf-confidence">
                    <span>置信度</span>
                    <div class="review-confidence-track">
                      <div class="review-confidence-fill" :style="{ width: confidencePercent(cf.confidence) + '%' }"></div>
                    </div>
                    <b>{{ confidencePercent(cf.confidence) }}%</b>
                  </div>
                </div>
              </div>

              <!-- Timeline -->
              <div v-if="reviewTimeline.length" class="review-timeline">
                <h4>事件时间线</h4>
                <div v-for="(ev, idx) in reviewTimeline" :key="'tl-' + idx" class="review-tl-item">
                  <span class="review-tl-badge">Day {{ ev.day || '?' }} {{ phaseLabel(ev.phase) || ev.phase || '' }}</span>
                  <span class="review-tl-event">{{ ev.event }}</span>
                </div>
              </div>
            </template>

            <!-- Fallback: raw JSON if structure is unrecognized -->
            <pre v-if="!reviewData && !reviewGameSummary && !reviewTurningPoints.length">{{ jsonText(reviewByGameId[selectedHistoryGame.game_id]) }}</pre>
          </section>

          <section v-if="archiveByGameId[selectedHistoryGame.game_id]" class="archive-review-panel">
            <h3>智能体档案</h3>

            <!-- Structured archive display -->
            <template v-if="archiveData">
              <!-- KPI Cards -->
              <div class="archive-kpi-strip">
                <span class="archive-kpi-card">
                  <small>决策总数</small>
                  <b>{{ archiveDecisionCount }}</b>
                </span>
                <span class="archive-kpi-card">
                  <small>错误次数</small>
                  <b :class="{ 'archive-kpi-error': archiveErrorCount > 0 }">{{ archiveErrorCount }}</b>
                </span>
                <span class="archive-kpi-card">
                  <small>回退次数</small>
                  <b>{{ archiveFallbackCount }}</b>
                </span>
                <span v-if="archiveData.agent_name || archiveData.name" class="archive-kpi-card">
                  <small>智能体</small>
                  <b>{{ archiveData.agent_name || archiveData.name }}</b>
                </span>
              </div>

              <!-- Decision Source Breakdown -->
              <div v-if="archiveDecisionSources && archiveDecisionSources.length" class="archive-source-breakdown">
                <h4>决策来源分布</h4>
                <div v-for="item in archiveDecisionSources" :key="'ds-' + item.source" class="archive-source-row">
                  <span class="archive-source-label">{{ item.source === 'llm' ? 'LLM 模型' : item.source === 'fallback' ? '回退策略' : item.source }}</span>
                  <div class="archive-source-track">
                    <div
                      class="archive-source-fill"
                      :class="item.source === 'llm' ? 'archive-source-llm' : 'archive-source-fallback'"
                      :style="{ width: (archiveDecisionCount ? Math.round((item.count / archiveDecisionCount) * 100) : 0) + '%' }"
                    ></div>
                  </div>
                  <b class="archive-source-count">{{ item.count }}</b>
                </div>
              </div>

              <!-- Additional archive fields as key-value pairs -->
              <div v-if="archiveExtraFields.length" class="archive-extra-fields">
                <span v-for="field in archiveExtraFields" :key="'ae-' + field.key" class="archive-extra-item">
                  <small>{{ field.key }}</small>
                  <b>{{ field.value }}</b>
                </span>
              </div>
            </template>

            <!-- Fallback: raw JSON -->
            <pre v-if="!archiveData">{{ jsonText(archiveByGameId[selectedHistoryGame.game_id]) }}</pre>
          </section>
        </section>

        <p v-if="!selectedHistoryGame && !historyLoading" class="empty-log">选择一局历史对局查看详情</p>
      </main>
    </section>

    <ReplayControls
      :is-replay-mode="isReplayMode"
      @return-to-history="emit('return-to-history')"
      @exit-replay="emit('exit-replay')"
    />
  </section>
</template>
