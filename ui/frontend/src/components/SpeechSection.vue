<script setup>
import { computed } from 'vue'
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'

const props = defineProps({
  decisions: { type: Array, default: () => [] },
  selectedDecision: Object,
  detailTab: { type: String, default: 'summary' }
})

const emit = defineEmits(['update:selectedDecision', 'update:detailTab'])

function decisionKey(decision, index = 0) {
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

function isSelected(decision, index) {
  return decisionKey(activeDecision.value) === decisionKey(decision, index)
}

function selectDecision(decision) {
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
