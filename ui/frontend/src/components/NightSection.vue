<script setup lang="ts">
import { computed, type PropType } from 'vue'
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'

interface HistoryDecision {
  id?: string | number
  decision_id?: string | number
  sequence?: string | number
  index?: string | number
  day?: string | number
  phase?: string
  action?: string
  actor_id?: string | number
  actorName?: string
  target_id?: string | number
  targetName?: string
}

type NightActionDetail = (decision: HistoryDecision) => unknown
type RoleIconImage = (player: unknown) => string

const props = defineProps({
  nightActions: { type: Array as PropType<HistoryDecision[]>, default: () => [] },
  nightResult: { type: String, default: '' },
  selectedDecision: Object as PropType<HistoryDecision | null>,
  detailTab: { type: String, default: 'summary' },
  nightActionDetail: Function as PropType<NightActionDetail>,
  roleIconImage: Function as PropType<RoleIconImage>
})

const emit = defineEmits(['update:selectedDecision', 'update:detailTab'])

function decisionKey(decision: HistoryDecision | null | undefined, index = 0) {
  if (!decision) return ''
  return [
    decision.id ?? decision.decision_id ?? decision.sequence ?? decision.index ?? index,
    decision.day ?? '',
    decision.phase ?? '',
    decision.action ?? '',
    decision.actor_id ?? decision.actorName ?? '',
    decision.target_id ?? decision.targetName ?? ''
  ].map((part) => String(part)).join('|')
}

const activeDecision = computed(() => {
  if (!props.nightActions.length) return null
  const selectedKey = decisionKey(props.selectedDecision)
  return props.nightActions.find((action, index) => decisionKey(action, index) === selectedKey) || props.nightActions[0]
})

function isSelected(action: HistoryDecision, index: number) {
  return decisionKey(activeDecision.value) === decisionKey(action, index)
}

function selectDecision(action: HistoryDecision) {
  emit('update:selectedDecision', action)
  emit('update:detailTab', 'summary')
}
</script>

<template>
  <section v-if="nightActions.length" class="history-night-section">
    <div v-if="nightResult" class="night-result-bar">{{ nightResult }}</div>
    <div class="night-two-col">
      <div class="night-left">
        <div class="night-action-grid">
          <NightActionCard
            v-for="(action, index) in nightActions"
            :key="decisionKey(action, index)"
            :action="action"
            :selected="isSelected(action, index)"
            :night-action-detail="nightActionDetail"
            :role-icon-image="roleIconImage"
            mode="night"
            @select="selectDecision"
          />
        </div>
      </div>
      <DecisionDetail
        :decision="activeDecision"
        :detail-tab="detailTab"
        @update:detailTab="emit('update:detailTab', $event)"
      />
    </div>
  </section>
</template>
