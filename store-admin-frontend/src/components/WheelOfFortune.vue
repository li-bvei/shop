<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WheelPrize } from '@/api/guest'

const props = defineProps<{ prizes: WheelPrize[]; busy?: boolean }>()
const emit = defineEmits<{ spin: [] }>()
const { t } = useI18n()

const count = computed(() => Math.max(props.prizes.length, 1))
const seg = computed(() => 360 / count.value)

// Alternating segment fills — warm "prize wheel" palette, fixed (not
// theme-swapped: the wheel reads the same in light and dark).
const FILLS = ['#FFE2A8', '#FFD066', '#FFB4A2', '#FFC97A']
const wheelBg = computed(() => {
  const stops: string[] = []
  for (let i = 0; i < count.value; i++) {
    const c = FILLS[i % FILLS.length]
    stops.push(`${c} ${i * seg.value}deg ${(i + 1) * seg.value}deg`)
  }
  return `conic-gradient(from ${-seg.value / 2}deg, ${stops.join(', ')})`
})

const rotation = ref(0)
const spinning = ref(false)
const wheelEl = ref<HTMLElement>()

function labelStyle(i: number) {
  return { transform: `rotate(${i * seg.value}deg)` }
}

/** Spin so segment `targetIndex` lands under the top pointer. Resolves
 * when the wheel stops. */
function spin(targetIndex: number): Promise<void> {
  if (spinning.value || props.prizes.length === 0) return Promise.resolve()
  spinning.value = true
  const s = seg.value
  const idx = ((targetIndex % count.value) + count.value) % count.value
  // Segment i's centre sits at screen-angle i*s from the top (the
  // conic-gradient starts `from -s/2`), so the wheel must rotate to
  // `-i*s (mod 360)` to bring it under the top pointer.
  const currentMod = ((rotation.value % 360) + 360) % 360
  const want = (((360 - idx * s) % 360) + 360) % 360
  let delta = want - currentMod
  if (delta <= 0) delta += 360
  // land a touch off dead-centre so it doesn't look mechanical
  const jitter = (Math.random() - 0.5) * s * 0.5
  rotation.value += delta + jitter + 360 * 5

  return new Promise((resolve) => {
    let done = false
    const finish = () => {
      if (done) return
      done = true
      spinning.value = false
      wheelEl.value?.removeEventListener('transitionend', finish)
      resolve()
    }
    wheelEl.value?.addEventListener('transitionend', finish)
    window.setTimeout(finish, 5000)
  })
}

defineExpose({ spin })
</script>

<template>
  <div class="wheel-wrap">
    <div class="pointer" aria-hidden="true" />
    <div ref="wheelEl" class="wheel" :style="{ transform: `rotate(${rotation}deg)`, background: wheelBg }">
      <div
        v-for="(p, i) in prizes"
        :key="p.id"
        class="seg"
        :class="{ dim: p.soldOut }"
        :style="labelStyle(i)"
      >
        <span>{{ p.name }}</span>
      </div>
    </div>
    <button type="button" class="hub" :disabled="busy || spinning" @click="emit('spin')">
      <span v-if="spinning" class="hub-dots">●●●</span>
      <span v-else>{{ t('guest.wheelSpin') }}</span>
    </button>
  </div>
</template>

<style scoped>
.wheel-wrap {
  position: relative;
  width: min(300px, 82vw);
  height: min(300px, 82vw);
  margin: 0 auto;
}

.pointer {
  position: absolute;
  top: -4px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 12px solid transparent;
  border-right: 12px solid transparent;
  border-top: 20px solid #e2483d;
  z-index: 3;
  filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.25));
}

.wheel {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 7px solid #fff;
  box-shadow:
    0 0 0 3px #e2483d,
    0 10px 30px rgba(0, 0, 0, 0.25);
  transition: transform 4.1s cubic-bezier(0.12, 0.82, 0.18, 1);
}

.seg {
  position: absolute;
  inset: 0;
  display: flex;
  justify-content: center;
  padding-top: 24px;
  transform-origin: center;
  pointer-events: none;
}

.seg span {
  max-width: 82px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.15;
  color: #7a3b12;
  text-align: center;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.seg.dim span {
  opacity: 0.4;
  text-decoration: line-through;
}

.hub {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 78px;
  height: 78px;
  border-radius: 50%;
  border: 4px solid #fff;
  background: #e2483d;
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  z-index: 2;
  box-shadow: 0 4px 12px rgba(226, 72, 61, 0.5);
}

.hub:disabled {
  cursor: default;
  opacity: 0.85;
}

.hub-dots {
  font-size: 11px;
  letter-spacing: 1px;
  animation: hub-pulse 1s ease-in-out infinite;
}

@keyframes hub-pulse {
  50% {
    opacity: 0.4;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wheel {
    transition-duration: 0.4s;
  }
}
</style>
