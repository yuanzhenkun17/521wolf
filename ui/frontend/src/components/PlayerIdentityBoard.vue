<script setup lang="ts">
import type { PropType } from 'vue'

interface PlayerIdentityBoardPlayer {
  id?: string | number
  displaySeat?: unknown
  speaking?: unknown
  alive?: boolean
  isSheriff?: unknown
  roleIcon?: string
  role_hint?: string
  [key: string]: unknown
}

const props = defineProps({
  players: { type: Array as PropType<PlayerIdentityBoardPlayer[]>, default: () => [] },
  activeSeat: { type: [String, Number], default: '' },
  selectedTargetId: { type: [String, Number, null] as unknown as PropType<string | number | null>, default: null },
  panelHeight: { type: Number, default: 146 }
})

function isActiveSeat(player: PlayerIdentityBoardPlayer): boolean {
  return Boolean(props.activeSeat) && String(player?.displaySeat ?? '') === String(props.activeSeat)
}

function isSelectedTarget(player: PlayerIdentityBoardPlayer): boolean {
  if (props.selectedTargetId == null || props.selectedTargetId === '') return false
  return Number(player?.id) === Number(props.selectedTargetId)
}
</script>

<template>
  <aside class="role-grid-panel" :style="{ height: `${panelHeight}px` }" aria-label="玩家身份列">
    <div class="role-grid">
      <article
        v-for="(player, index) in players"
        :key="player.id"
        :class="{ speaking: player.speaking, linked: isActiveSeat(player), targeted: isSelectedTarget(player), dead: !player.alive }"
        :style="{ '--i': index }"
      >
        <img v-show="player.isSheriff" class="sheriff-badge-sm" src="/ui/sheriff-badge.png" alt="警长" />
        <div class="role-icon-wrap" :class="{ dead: !player.alive }">
          <img :src="player.roleIcon" :alt="player.role_hint" />
        </div>
        <div class="role-grid-seat">
          <b>{{ player.displaySeat }}</b>
        </div>
      </article>
    </div>
  </aside>
</template>
