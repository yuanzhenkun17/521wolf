<script setup lang="ts">
// @ts-nocheck
import { sourceText } from '../../composables/workbenchShared.ts'

defineProps({
  evo: { type: Object, required: true }
})

const emit = defineEmits(['open-sample-log', 'replay-sample-game'])

const DECISION_PREVIEW_LIMIT = 8
const EVENT_PREVIEW_LIMIT = 10

function sampleTitle(game) {
  if (!game) return '—'
  return `${game.short} · ${game.winnerLabel}`
}

function decisionText(decision) {
  return decision?.public_summary || decision?.reason || decision?.private_reasoning || sourceText(decision?.action) || '—'
}

function eventText(event) {
  return event?.message || event?.public_summary || sourceText(event?.event_type || event?.type) || '—'
}

function actorLabel(decision) {
  return decision?.actor_name || decision?.role || sourceText(decision?.action) || '智能体'
}

function eventLabel(event) {
  return sourceText(event?.phase || event?.event_type || event?.type) || '事件'
}

function valueText(value) {
  if (value == null || value === '') return '—'
  return String(value)
}

function labelText(value) {
  if (value == null || value === '') return '—'
  const label = sourceText(value)
  return label === '未知' ? String(value) : label
}

function sideText(value) {
  return {
    baseline: '基线',
    candidate: '候选',
    training: '训练'
  }[value] || labelText(value)
}

function winnerText(archive, game) {
  const raw = archive?.winner || game?.winner
  const mapped = {
    good: '好人',
    village: '好人',
    werewolves: '狼人',
    wolf: '狼人'
  }[raw]
  if (mapped) return mapped
  if (game?.winnerLabel && game.winnerLabel !== '未知') return game.winnerLabel
  return valueText(raw)
}

function selectedMeta(evo) {
  const detail = evo.selectedGameDetail.value || {}
  const archive = detail.archive || {}
  const game = evo.selectedSampleGame.value || {}
  const decisions = detail.decisions || []
  const events = detail.events || []
  const phase = archive.phase || game.phase || archive.stage || game.stage
  const bucket = archive.side || game.side || game.bucket || evo.selectedGameBucket.value
  return [
    { label: '历史 ID', value: valueText(evo.selectedSampleHistoryGameId.value), mono: true },
    { label: '样本 ID', value: valueText(archive.game_id || game.id), mono: true },
    { label: '阶段', value: labelText(phase) },
    { label: '样本桶', value: sideText(bucket) },
    { label: '胜方', value: winnerText(archive, game) },
    { label: '天数', value: valueText(game.days ?? game.day ?? archive.days ?? archive.day) },
    { label: '种子', value: valueText(archive.seed ?? game.seed), mono: true },
    { label: '事件数', value: valueText(archive.event_count ?? game.eventCount ?? events.length), count: true },
    { label: '决策数', value: valueText(archive.decision_count ?? game.decisionCount ?? decisions.length), count: true }
  ]
}

function detailDecisions(evo) {
  return evo.selectedGameDetail.value.decisions || []
}

function detailEvents(evo) {
  return evo.selectedGameDetail.value.events || []
}

function decisionOverflowCount(evo) {
  return Math.max(0, detailDecisions(evo).length - DECISION_PREVIEW_LIMIT)
}

function eventOverflowCount(evo) {
  return Math.max(0, detailEvents(evo).length - EVENT_PREVIEW_LIMIT)
}

function decisionMeta(decision) {
  return [
    decision?.day ? `第${decision.day}天` : '',
    decision?.phase ? sourceText(decision.phase) : '',
    decision?.action ? sourceText(decision.action) : '',
    decision?.target_id != null ? `目标 ${decision.target_id}号` : '',
    decision?.choice != null ? `选择 ${sourceText(decision.choice)}` : '',
    decision?.source ? `来源 ${sourceText(decision.source)}` : ''
  ].filter(Boolean).join(' · ')
}

function eventMeta(event) {
  return [
    event?.day ? `第${event.day}天` : '',
    event?.phase ? sourceText(event.phase) : '',
    event?.actor_id != null ? `行动者 ${event.actor_id}号` : '',
    event?.target_id != null ? `目标 ${event.target_id}号` : '',
    event?.visibility ? `可见性 ${sourceText(event.visibility)}` : '',
    event?.sequence != null ? `#${event.sequence}` : ''
  ].filter(Boolean).join(' · ')
}

function reviewText(item) {
  if (typeof item === 'string') return item
  return item?.description || item?.summary || item?.title || sourceText(item)
}

function reviewItems(archive) {
  const review = archive?.review
  if (!review || typeof review !== 'object') return []
  return [
    ...(review.key_turning_points || []),
    ...(review.recommendations || []),
    ...(review.turning_points || [])
  ].map(reviewText).filter(Boolean).slice(0, 8)
}

function openSampleLog(historyId) {
  if (!historyId) return
  emit('open-sample-log', historyId)
}

function replaySampleGame(historyId) {
  if (!historyId) return
  emit('replay-sample-game', historyId)
}

function sampleEmptyText(evo) {
  if (evo.selectedSampleState.value.unsupported) return evo.selectedSampleState.value.error
  if (evo.selectedSampleState.value.loading) return '正在读取样本局...'
  return evo.selectedSampleBucketError.value || evo.selectedSampleState.value.error || '暂无样本局'
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>样本局</h2>
        <b>{{ evo.selectedSamplePagination.value.total || evo.selectedGameRows.value.length }}</b>
      </header>

      <div v-if="evo.selectedSampleState.value.unsupported" class="evo-alert compact">
        {{ evo.selectedSampleState.value.error }}
      </div>
      <div v-else-if="evo.selectedSampleState.value.error" class="evo-alert compact">
        {{ evo.selectedSampleState.value.error }}
      </div>

      <div class="evo-sample-tabs">
        <button
          v-for="bucket in evo.sampleBuckets.value"
          :key="bucket.key"
          type="button"
          :class="{ active: evo.selectedGameBucket.value === bucket.key }"
          @click="evo.selectSampleGame(bucket.key)"
        >
          {{ bucket.label }} <span>{{ bucket.count }}</span>
        </button>
      </div>

      <div class="evo-run-tools">
        <input v-model="evo.sampleGameFilter.value" type="search" placeholder="筛选对局 / 阶段 / 胜负" />
        <span>{{ evo.visibleSampleGameRows.value.length }} / {{ evo.selectedSamplePagination.value.total || evo.filteredSampleGameRows.value.length }}</span>
      </div>

      <div class="evo-sample-layout">
        <div v-if="!evo.filteredSampleGameRows.value.length" class="evo-empty compact">
          {{ sampleEmptyText(evo) }}
        </div>
        <div v-else class="evo-sample-list">
          <div v-if="evo.selectedSampleBucketError.value" class="evo-alert compact">
            {{ evo.selectedSampleBucketError.value }}
          </div>
          <button
            v-for="game in evo.visibleSampleGameRows.value"
            :key="game.id"
            type="button"
            :class="['evo-sample-row', { selected: evo.selectedGameId.value === game.id }]"
            @click="evo.selectSampleGame(game.bucket, game.id)"
          >
            <strong>{{ sampleTitle(game) }}</strong>
            <span>{{ game.dayLabel }} · {{ game.phaseLabel }} · {{ game.eventCount }} 事件 · {{ game.decisionCount }} 决策</span>
          </button>
          <div v-if="evo.sampleGameHasMore.value" class="evo-run-more">
            <span>
              已载入 {{ evo.selectedGameRows.value.length }} / {{ evo.selectedSamplePagination.value.total || evo.selectedGameRows.value.length }}
            </span>
            <button
              type="button"
              class="evo-load-more"
              :disabled="evo.sampleGameLoadingMore.value"
              @click="evo.loadMoreSampleGames(evo.selectedGameBucket.value)"
            >
              {{ evo.sampleGameLoadingMore.value ? '加载中' : '加载更多' }}
            </button>
          </div>
        </div>

        <div class="evo-sample-detail">
          <div v-if="evo.selectedGameDetail.value.loading" class="evo-empty compact">读取样本局...</div>
          <div v-else-if="evo.selectedGameDetail.value.error" class="evo-alert">{{ evo.selectedGameDetail.value.error }}</div>
          <template v-else>
            <div class="evo-sample-detail-head">
              <div class="evo-sample-detail-title">
                <small>证据追溯</small>
                <h3>{{ evo.selectedGameDetail.value.archive?.title || evo.selectedGameId.value || '选择一局样本' }}</h3>
              </div>
              <div class="evo-sample-actions">
                <button
                  type="button"
                  class="evo-ghost-action"
                  :disabled="Boolean(evo.selectedSampleHistoryUnavailableReason.value)"
                  :title="evo.selectedSampleHistoryUnavailableReason.value || '打开样本局日志'"
                  aria-label="打开样本局日志"
                  @click="openSampleLog(evo.selectedSampleHistoryGameId.value)"
                >
                  打开日志
                </button>
                <button
                  type="button"
                  class="evo-action"
                  :disabled="Boolean(evo.selectedSampleHistoryUnavailableReason.value)"
                  :title="evo.selectedSampleHistoryUnavailableReason.value || '在大厅回放样本局'"
                  aria-label="回放样本局"
                  @click="replaySampleGame(evo.selectedSampleHistoryGameId.value)"
                >
                  回放样本局
                </button>
              </div>
            </div>
            <div v-if="evo.selectedGameDetail.value.warning" class="evo-alert compact">
              {{ evo.selectedGameDetail.value.warning }}
            </div>
            <p v-if="evo.selectedSampleHistoryUnavailableReason.value" class="evo-muted-reason">
              {{ evo.selectedSampleHistoryUnavailableReason.value }}
            </p>
            <p class="evo-sample-summary">{{ evo.selectedGameDetail.value.archive?.summary || '暂无档案摘要' }}</p>

            <div class="evo-config-grid evo-sample-evidence-meta" data-evolution-sample-evidence-trace>
              <span
                v-for="item in selectedMeta(evo)"
                :key="item.label"
                :class="{ mono: item.mono, count: item.count }"
              >
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
              </span>
            </div>

            <ul
              v-if="evo.selectedGameDetail.value.archive?.highlights?.length || reviewItems(evo.selectedGameDetail.value.archive).length"
              class="evo-highlight-list"
            >
              <li v-for="item in evo.selectedGameDetail.value.archive?.highlights?.slice(0, 8)" :key="`highlight-${item}`">
                {{ item }}
              </li>
              <li v-for="item in reviewItems(evo.selectedGameDetail.value.archive)" :key="`review-${item}`">
                {{ item }}
              </li>
            </ul>

            <div class="evo-evidence-columns evo-sample-evidence-columns" data-evolution-sample-compact-evidence>
              <section>
                <header>
                  <h4>决策预览</h4>
                  <b>{{ detailDecisions(evo).length }}</b>
                </header>
                <ol v-if="detailDecisions(evo).length">
                  <li
                    v-for="decision in detailDecisions(evo).slice(0, DECISION_PREVIEW_LIMIT)"
                    :key="decision.id || decision.action || decisionText(decision)"
                  >
                    <strong>{{ actorLabel(decision) }}</strong>
                    <span>
                      <em>{{ decisionText(decision) }}</em>
                      <small v-if="decisionMeta(decision)">{{ decisionMeta(decision) }}</small>
                    </span>
                  </li>
                  <li v-if="decisionOverflowCount(evo)" class="evo-evidence-overflow">
                    <strong>日志</strong>
                    <span>还有 {{ decisionOverflowCount(evo) }} 条决策未显示，请打开日志查看完整记录。</span>
                  </li>
                </ol>
                <span v-else>—</span>
              </section>
              <section>
                <header>
                  <h4>事件预览</h4>
                  <b>{{ detailEvents(evo).length }}</b>
                </header>
                <ol v-if="detailEvents(evo).length">
                  <li
                    v-for="event in detailEvents(evo).slice(0, EVENT_PREVIEW_LIMIT)"
                    :key="event.sequence || event.event_type || eventText(event)"
                  >
                    <strong>{{ eventLabel(event) }}</strong>
                    <span>
                      <em>{{ eventText(event) }}</em>
                      <small v-if="eventMeta(event)">{{ eventMeta(event) }}</small>
                    </span>
                  </li>
                  <li v-if="eventOverflowCount(evo)" class="evo-evidence-overflow">
                    <strong>日志</strong>
                    <span>还有 {{ eventOverflowCount(evo) }} 条事件未显示，请打开日志查看完整记录。</span>
                  </li>
                </ol>
                <span v-else>—</span>
              </section>
            </div>
          </template>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.evo-sample-detail-title {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.evo-sample-detail-title small {
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.evo-sample-summary {
  border-left: 2px solid rgba(93, 48, 17, 0.22);
  padding-left: 9px;
}

.evo-sample-evidence-meta {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.evo-sample-evidence-meta span {
  min-width: 0;
}

.evo-sample-evidence-meta span.mono b,
.evo-sample-evidence-meta span.count b {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  letter-spacing: 0;
}

.evo-sample-evidence-columns {
  gap: 12px;
}

.evo-sample-evidence-columns section {
  min-width: 0;
  overflow: hidden;
}

.evo-sample-evidence-columns header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.evo-sample-evidence-columns header h4 {
  margin: 0;
}

.evo-sample-evidence-columns header b {
  color: var(--evo-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
}

.evo-sample-evidence-columns ol {
  display: grid;
  gap: 0;
  padding: 0;
  list-style: none;
}

.evo-sample-evidence-columns li {
  display: grid;
  grid-template-columns: minmax(56px, 0.28fr) minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  padding: 6px 0;
  border-top: 1px solid rgba(93, 48, 17, 0.1);
}

.evo-sample-evidence-columns li strong,
.evo-sample-evidence-columns li span {
  min-width: 0;
}

.evo-sample-evidence-columns li strong {
  overflow: hidden;
  margin: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-sample-evidence-columns li span {
  display: grid;
  gap: 2px;
}

.evo-sample-evidence-columns li em {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-style: normal;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-sample-evidence-columns li small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-sample-evidence-columns .evo-evidence-overflow span {
  color: var(--evo-accent-strong);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.45;
}

@media (max-width: 1180px) {
  .evo-sample-evidence-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-sample-evidence-columns {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
