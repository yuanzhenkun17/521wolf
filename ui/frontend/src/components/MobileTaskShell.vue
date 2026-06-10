<script setup lang="ts">
withDefaults(defineProps<{
  mode?: string
  hasTask?: boolean
  replay?: boolean
}>(), {
  mode: 'match',
  hasTask: false,
  replay: false
})
</script>

<template>
  <section
    class="mobile-task-shell"
    :class="{ 'has-task': hasTask, 'is-replay': replay }"
    :data-mode="mode"
  >
    <slot />
  </section>
</template>

<style scoped>
.mobile-task-shell {
  --match-safe-top: env(safe-area-inset-top, 0px);
  --match-safe-right: env(safe-area-inset-right, 0px);
  --match-safe-bottom: env(safe-area-inset-bottom, 0px);
  --match-safe-left: env(safe-area-inset-left, 0px);
  --match-action-gutter: 64px;
  --match-action-bottom: max(18px, calc(18px + var(--match-safe-bottom)));
  --match-action-max-height: calc(100dvh - 112px - var(--match-safe-top) - var(--match-safe-bottom));
  --match-replay-gutter: 52px;
  --match-replay-bottom: max(24px, calc(24px + var(--match-safe-bottom)));
  --match-toast-gutter: 32px;
  --match-toast-top: calc(158px + var(--match-safe-top));
  display: contents;
}

@supports not (height: 100dvh) {
  .mobile-task-shell {
    --match-action-max-height: calc(100vh - 112px - var(--match-safe-top) - var(--match-safe-bottom));
  }
}

@media (max-width: 760px) {
  .mobile-task-shell {
    --match-action-gutter: 18px;
    --match-action-bottom: max(12px, calc(12px + var(--match-safe-bottom)));
    --match-action-max-height: calc(100dvh - 96px - var(--match-safe-top) - var(--match-safe-bottom));
    --match-replay-gutter: 18px;
    --match-replay-bottom: max(12px, calc(12px + var(--match-safe-bottom)));
    --match-toast-gutter: 22px;
    --match-toast-top: calc(146px + var(--match-safe-top));
  }
}
</style>
