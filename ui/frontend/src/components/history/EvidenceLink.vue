<script setup lang="ts">
import { computed, type PropType } from 'vue'
import { buildEvidenceLink } from './evidenceLinks.ts'

const props = defineProps({
  target: { type: Object as PropType<Record<string, unknown>>, default: () => ({}) },
  kind: { type: String, default: 'game' },
  label: { type: String, default: '' },
  compact: Boolean,
  disabledLabel: { type: String, default: 'Evidence unavailable' }
})

const link = computed(() => buildEvidenceLink(props.target, {
  kind: props.kind,
  label: props.label
}))
const displayLabel = computed(() => link.value.label || props.label || 'Evidence')
const detailText = computed(() => link.value.disabled
  ? (link.value.unavailableReason || props.disabledLabel)
  : (link.value.id || link.value.href)
)
const titleText = computed(() => link.value.disabled ? detailText.value : link.value.href)
</script>

<template>
  <a
    v-if="!link.disabled"
    :href="link.href"
    :title="titleText"
    :class="['evidence-link', { 'evidence-link--compact': compact }]"
    :data-kind="link.kind"
  >
    <span>{{ displayLabel }}</span>
    <small v-if="detailText">{{ detailText }}</small>
  </a>
  <span
    v-else
    :title="titleText"
    :class="['evidence-link', 'evidence-link--disabled', { 'evidence-link--compact': compact }]"
    :data-kind="link.kind"
    aria-disabled="true"
  >
    <span>{{ displayLabel }}</span>
    <small>{{ detailText }}</small>
  </span>
</template>

<style scoped>
.evidence-link {
  display: inline-grid;
  grid-template-columns: minmax(0, auto);
  align-content: center;
  gap: 2px;
  min-width: 0;
  max-width: 100%;
  min-height: 34px;
  padding: 6px 9px;
  border: 1px solid rgba(62, 88, 100, 0.2);
  border-radius: 6px;
  background: rgba(244, 249, 250, 0.78);
  color: #25373c;
  text-decoration: none;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62);
}

.evidence-link:hover {
  border-color: rgba(33, 103, 121, 0.36);
  background: rgba(232, 245, 248, 0.92);
}

.evidence-link span {
  overflow: hidden;
  font-size: 11px;
  font-weight: 850;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-link small {
  overflow: hidden;
  color: rgba(37, 55, 60, 0.62);
  font-size: 10px;
  font-weight: 750;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-link--compact {
  min-height: 30px;
  padding: 5px 8px;
}

.evidence-link--disabled {
  border-color: rgba(92, 63, 37, 0.16);
  background: rgba(247, 241, 232, 0.72);
  color: rgba(68, 48, 32, 0.7);
  cursor: not-allowed;
}

.evidence-link--disabled small {
  color: rgba(96, 65, 40, 0.68);
}
</style>
