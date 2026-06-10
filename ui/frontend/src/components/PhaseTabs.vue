<script setup lang="ts">
import type { PropType } from 'vue'

interface PhasePage {
  key: string
  phase?: string
  day?: number | string
}

type PageTitle = (page: PhasePage) => string

const props = defineProps({
  pages: { type: Array as PropType<PhasePage[]>, default: () => [] },
  selectedPageKey: { type: String, default: '' },
  pageTitle: Function as PropType<PageTitle>
})

const emit = defineEmits(['select-page', 'update:selectedPageKey'])

function title(page: PhasePage) {
  return props.pageTitle ? props.pageTitle(page) : page.key
}

function phaseName(page: PhasePage) {
  return String(page?.phase || '').toLowerCase()
}

function dayNumber(page: PhasePage) {
  const value = Number(page?.day || 1)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function stepContext(page: PhasePage) {
  const phase = phaseName(page)
  if (phase === 'setup') return '开局'
  if (phase === 'ended' || phase === 'result' || phase === 'finished') return '终局'
  if (phase === 'sheriff' || phase === 'sheriff_vote' || phase === 'sheriff_result') return '警长'
  return `第${dayNumber(page)}天`
}

function stepLabel(page: PhasePage) {
  const phase = phaseName(page)
  const map: Record<string, string> = {
    setup: '准备',
    night: '夜晚',
    sheriff: '竞选',
    sheriff_vote: '投票',
    sheriff_result: '结果',
    speech: '白天',
    exile_vote: '放逐',
    pk_vote: '对决',
    vote: '放逐',
    ended: '结果',
    result: '结果',
    finished: '结果'
  }
  return map[phase] || title(page)
}

function stepClass(page: PhasePage) {
  const phase = phaseName(page) || 'unknown'
  return `phase-${phase.replace(/[^a-z0-9_-]/g, '-')}`
}

function selectPage(key: string) {
  emit('update:selectedPageKey', key)
  emit('select-page', key)
}
</script>

<template>
  <nav v-if="pages.length" class="history-phase-tabs" aria-label="日志阶段筛选">
    <button
      v-for="page in pages"
      :key="page.key"
      :class="['phase-step', stepClass(page), { active: selectedPageKey === page.key }]"
      :title="title(page)"
      :aria-current="selectedPageKey === page.key ? 'step' : undefined"
      @click="selectPage(page.key)"
    >
      <span class="phase-dot" aria-hidden="true"></span>
      <span class="phase-copy">
        <small>{{ stepContext(page) }}</small>
        <b>{{ stepLabel(page) }}</b>
      </span>
    </button>
  </nav>
</template>
