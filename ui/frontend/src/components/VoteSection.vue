<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'
import VoteResults from './VoteResults.vue'

const props = defineProps({
  decisions: { type: Array, default: () => [] },
  tally: { type: Array, default: () => [] },
  resultMessage: { type: String, default: '' },
  selectedDecision: Object,
  detailTab: { type: String, default: 'summary' },
  roleIconImage: Function
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
  <section v-if="decisions.length || resultMessage" class="history-night-section">
    <div v-if="resultMessage" class="night-result-bar">{{ resultMessage }}</div>
    <VoteResults :tally="tally" />
    <div v-if="decisions.length" class="night-two-col">
      <div class="night-left">
        <div class="night-action-grid">
          <NightActionCard
            v-for="(vote, index) in decisions"
            :key="decisionKey(vote, index)"
            :action="vote"
            :selected="isSelected(vote, index)"
            mode="vote"
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
