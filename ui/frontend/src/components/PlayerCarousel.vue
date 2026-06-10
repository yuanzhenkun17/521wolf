<script setup lang="ts">
import { computed } from 'vue'
import type { PropType } from 'vue'

interface CarouselGame {
  day?: number | string
  current_speaker_id?: number | string | null
  phase?: string | null
}

interface CarouselItem {
  key: number | string
  tone?: string
  image: string
  label: string
}

const props = defineProps({
  game: Object as PropType<CarouselGame | null>,
  isNight: Boolean,
  carousel: { type: Array as PropType<CarouselItem[]>, default: () => [] },
  message: { type: String, default: '' }
})

const dayLabel = computed(() => props.game?.day ?? '-')
const messageKey = computed(() => `message-${props.game?.current_speaker_id || props.game?.phase || 'empty'}`)
</script>

<template>
  <section class="speaker-core">
    <header>
      <span>第{{ dayLabel }}天</span>
      <i>{{ isNight ? '☾' : '☀' }}</i>
      <b>{{ isNight ? '黑夜' : '白天' }}</b>
    </header>
    <div class="speaker-carousel">
      <article v-for="item in carousel" :key="item.key" :class="['speaker-avatar', item.tone]">
        <img :src="item.image" alt="发言者" decoding="async" loading="lazy" />
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
