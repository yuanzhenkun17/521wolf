<script setup>
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'

defineProps({
  decisions: { type: Array, default: () => [] },
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
  <section v-if="decisions.length" class="history-night-section">
    <div class="night-two-col">
      <div class="night-left">
        <div class="night-action-grid">
          <NightActionCard
            v-for="(decision, index) in decisions"
            :key="'sp-' + index"
            :action="decision"
            :selected="selectedDecision?.id === decision.id"
            mode="speech"
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
