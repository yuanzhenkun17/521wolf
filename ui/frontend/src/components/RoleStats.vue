<script setup>
defineProps({
  stats: { type: Array, default: () => [] },
  livingCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 }
});
</script>

<template>
  <section class="identity-panel match-panel">
    <header>
      <span>本局身份</span>
      <strong>{{ livingCount }} / {{ totalCount }} 存活</strong>
    </header>
    <div class="identity-list">
      <article v-for="item in stats" :key="item.role">
        <b>{{ item.role }}</b>
        <span>{{ item.alive }}/{{ item.total }}</span>
      </article>
    </div>
  </section>
</template>
