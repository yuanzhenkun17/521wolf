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

type RoleIconImage = (player: unknown) => string

const props = defineProps({
  decisions: { type: Array as PropType<HistoryDecision[]>, default: () => [] },
  selectedDecision: Object as PropType<HistoryDecision | null>,
  detailTab: { type: String, default: 'summary' },
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
  if (!props.decisions.length) return null
  const selectedKey = decisionKey(props.selectedDecision)
  return props.decisions.find((decision, index) => decisionKey(decision, index) === selectedKey) || props.decisions[0]
})

function isSelected(decision: HistoryDecision, index: number) {
  return decisionKey(activeDecision.value) === decisionKey(decision, index)
}

function selectDecision(decision: HistoryDecision) {
  emit('update:selectedDecision', decision)
  emit('update:detailTab', 'summary')
}
</script>

<template>
  <section v-if="decisions.length" class="history-night-section">
    <div class="night-two-col">
      <div class="night-left">
        <div class="night-action-grid">
          <NightActionCard
            v-for="(decision, index) in decisions"
            :key="decisionKey(decision, index)"
            :action="decision"
            :selected="isSelected(decision, index)"
            mode="speech"
            :role-icon-image="roleIconImage"
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
