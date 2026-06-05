<script setup>
import DecisionDetail from './DecisionDetail.vue'
import NightActionCard from './NightActionCard.vue'

defineProps({
  nightActions: { type: Array, default: () => [] },
  nightResult: { type: String, default: '' },
  selectedDecision: Object,
  detailTab: { type: String, default: 'summary' },
  nightActionDetail: Function
})

const emit = defineEmits(['update:selectedDecision', 'update:detailTab'])

function selectDecision(action) {
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
            :key="'night-action-' + index"
            :action="action"
            :selected="selectedDecision?.id === action.id"
            :night-action-detail="nightActionDetail"
            mode="night"
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
