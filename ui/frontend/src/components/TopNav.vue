<script setup>
defineProps({
  brand: { type: String, default: 'NightCouncil' }
})

const emit = defineEmits(['go-lobby', 'open-logs', 'open-evolution'])
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <img src="/topbar-characters.png" :alt="brand" />
      <strong>{{ brand }}</strong>
    </div>
    <nav>
      <button @click="emit('go-lobby')">大厅</button>
      <button @click="emit('open-logs')">日志</button>
      <button @click="emit('open-evolution')">自进化</button>
    </nav>
  </header>
</template>
