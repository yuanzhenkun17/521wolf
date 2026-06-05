<script setup>
const props = defineProps({
  pages: { type: Array, default: () => [] },
  selectedPageKey: { type: String, default: '' },
  pageTitle: Function
})

const emit = defineEmits(['select-page', 'update:selectedPageKey'])

function title(page) {
  return props.pageTitle ? props.pageTitle(page) : page.key
}

function selectPage(key) {
  emit('update:selectedPageKey', key)
  emit('select-page', key)
}
</script>

<template>
  <nav v-if="pages.length" class="history-phase-tabs" aria-label="日志阶段筛选">
    <button
      v-for="page in pages"
      :key="page.key"
      :class="{ active: selectedPageKey === page.key }"
      @click="selectPage(page.key)"
    >
      {{ title(page) }}
    </button>
  </nav>
</template>
