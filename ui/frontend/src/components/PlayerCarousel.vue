<script setup>
import { computed } from 'vue'

const props = defineProps({
  game: Object,
  isNight: Boolean,
  carousel: { type: Array, default: () => [] },
  message: { type: String, default: '' }
})

const dayLabel = computed(() => props.game?.day ?? '-')
const messageKey = computed(() => `message-${props.game?.current_speaker_id || props.game?.phase || 'empty'}`)
</script>

<template>
  <section class="speaker-core">
    <header>
      <span>DAY {{ dayLabel }}</span>
      <i>{{ isNight ? '☾' : '☀' }}</i>
      <b>{{ isNight ? '黑夜' : '白天' }}</b>
    </header>
    <div class="speaker-carousel">
      <article v-for="item in carousel" :key="item.key" :class="['speaker-avatar', item.tone]">
        <img :src="item.image" alt="发言者" />
        <strong>{{ item.label }}</strong>
      </article>
    </div>
    <div class="speaker-message-slot">
      <Transition name="message-slide">
        <p :key="messageKey">{{ message }}</p>
      </Transition>
    </div>
  </section>
</template>
