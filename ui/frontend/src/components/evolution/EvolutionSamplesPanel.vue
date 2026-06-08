<script setup>
import { sourceText } from '../../composables/workbenchShared.js'

defineProps({
  evo: { type: Object, required: true }
})

const emit = defineEmits(['open-sample-log', 'replay-sample-game'])

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

function sideText(value) {
  return {
    baseline: '基线',
    candidate: '候选',
    training: '训练'
  }[value] || sourceText(value)
}

function selectedMeta(evo) {
  const detail = evo.selectedGameDetail.value || {}
  const archive = detail.archive || {}
  const game = evo.selectedSampleGame.value || {}
  const decisions = detail.decisions || []
  const events = detail.events || []
  return [
    { label: '历史ID', value: evo.selectedSampleHistoryGameId.value || '—' },
    { label: '样本ID', value: valueText(archive.game_id || game.id) },
    { label: '阶段', value: sideText(archive.side || archive.phase || game.side || game.bucket) },
    { label: '胜方', value: game.winnerLabel || valueText(archive.winner) },
    { label: '天数', value: valueText(game.days || game.day || archive.days || archive.day) },
    { label: '种子', value: valueText(archive.seed || game.seed) },
    { label: '事件', value: valueText(archive.event_count ?? game.eventCount ?? events.length) },
    { label: '决策', value: valueText(archive.decision_count ?? game.decisionCount ?? decisions.length) }
  ]
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
              <h3>{{ evo.selectedGameDetail.value.archive?.title || evo.selectedGameId.value || '选择一局样本' }}</h3>
              <div class="evo-sample-actions">
                <button
                  type="button"
                  class="evo-ghost-action"
                  :disabled="Boolean(evo.selectedSampleHistoryUnavailableReason.value)"
                  :title="evo.selectedSampleHistoryUnavailableReason.value || '打开样本局日志'"
                  @click="openSampleLog(evo.selectedSampleHistoryGameId.value)"
                >
                  日志
                </button>
                <button
                  type="button"
                  class="evo-action"
                  :disabled="Boolean(evo.selectedSampleHistoryUnavailableReason.value)"
                  :title="evo.selectedSampleHistoryUnavailableReason.value || '在大厅回放样本局'"
                  @click="replaySampleGame(evo.selectedSampleHistoryGameId.value)"
                >
                  回放
                </button>
              </div>
            </div>
            <div v-if="evo.selectedGameDetail.value.warning" class="evo-alert compact">
              {{ evo.selectedGameDetail.value.warning }}
            </div>
            <p v-if="evo.selectedSampleHistoryUnavailableReason.value" class="evo-muted-reason">
              {{ evo.selectedSampleHistoryUnavailableReason.value }}
            </p>
            <p>{{ evo.selectedGameDetail.value.archive?.summary || '暂无档案摘要' }}</p>

            <div class="evo-config-grid">
              <span v-for="item in selectedMeta(evo)" :key="item.label">
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

            <div class="evo-evidence-columns">
              <div>
                <h4>决策 {{ evo.selectedGameDetail.value.decisions.length }}</h4>
                <ol v-if="evo.selectedGameDetail.value.decisions.length">
                  <li
                    v-for="decision in evo.selectedGameDetail.value.decisions.slice(0, 20)"
                    :key="decision.id || decision.action || decisionText(decision)"
                  >
                    <strong>{{ actorLabel(decision) }}</strong>
                    <span>
                      {{ decisionText(decision) }}
                      <br v-if="decisionMeta(decision)" />
                      <small v-if="decisionMeta(decision)">{{ decisionMeta(decision) }}</small>
                    </span>
                  </li>
                  <li v-if="evo.selectedGameDetail.value.decisions.length > 20">
                    <strong>更多</strong>
                    <span>还有 {{ evo.selectedGameDetail.value.decisions.length - 20 }} 条决策，可通过日志查看完整记录。</span>
                  </li>
                </ol>
                <span v-else>—</span>
              </div>
              <div>
                <h4>事件 {{ evo.selectedGameDetail.value.events.length }}</h4>
                <ol v-if="evo.selectedGameDetail.value.events.length">
                  <li
                    v-for="event in evo.selectedGameDetail.value.events.slice(0, 30)"
                    :key="event.sequence || event.event_type || eventText(event)"
                  >
                    <strong>{{ eventLabel(event) }}</strong>
                    <span>
                      {{ eventText(event) }}
                      <br v-if="eventMeta(event)" />
                      <small v-if="eventMeta(event)">{{ eventMeta(event) }}</small>
                    </span>
                  </li>
                  <li v-if="evo.selectedGameDetail.value.events.length > 30">
                    <strong>更多</strong>
                    <span>还有 {{ evo.selectedGameDetail.value.events.length - 30 }} 条事件，可通过日志查看完整记录。</span>
                  </li>
                </ol>
                <span v-else>—</span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </article>
  </div>
</template>
