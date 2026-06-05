<script setup>
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'
import VoteResults from './VoteResults.vue'

defineProps({
  decisions: { type: Array, default: () => [] },
  tally: { type: Array, default: () => [] },
  resultMessage: { type: String, default: '' },
  selectedDecision: Object,
  detailTab: { type: String, default: 'summary' }
})

const emit = defineEmits(['update:selectedDecision', 'update:detailTab'])

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
            :key="'vd-' + index"
            :action="vote"
            :selected="selectedDecision?.id === vote.id"
            mode="vote"
            @select="selectDecision"
          />
        </div>
      </div>
      <DecisionDetail
        :decision="selectedDecision"
        :detail-tab="detailTab"
        @update:detailTab="emit('update:detailTab', $event)"
      />
    </div>
  </section>
</template>
