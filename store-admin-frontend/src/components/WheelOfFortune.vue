<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Wheel } from 'spin-wheel'
import type { WheelPrize } from '@/api/guest'

/**
 * The lottery wheel, drawn by spin-wheel (pinned version). It never decides
 * anything: the parent draws on the server first, then calls
 * `spinToPrize(prizeId)` with the id the backend returned, and the wheel
 * lands on exactly that segment. Nothing here picks, weights or randomises a
 * prize.
 */
const props = defineProps<{ prizes: WheelPrize[]; busy?: boolean; disabled?: boolean; sound?: boolean }>()
const emit = defineEmits<{ spin: [] }>()
const { t } = useI18n()

const host = ref<HTMLElement>()
const bump = ref(false)
const spinning = ref(false)
const ready = ref(false)
let wheel: Wheel | null = null
let restResolver: ((index: number) => void) | null = null
let audio: AudioContext | null = null
let lastTick = 0

// Segment fills: white / mint / soft gray, so the wheel stays in the app's
// white-and-brand-green palette; the refund segment is a stronger green so it
// reads as its own landing spot, and sold-out prizes go flat gray.
const FILLS = ['#ffffff', '#edf9f2', '#f1f3f4']
const REFUND_FILL = '#c9ecd6'
const SOLD_OUT_FILL = '#e3e6e8'
const INK = '#202326'

function reducedMotion() {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

// The library shrinks a label until the whole string fits its segment, which
// made long prize names unreadable; cap the on-wheel text and let the result
// card show the full name.
const LABEL_MAX_CHARS = 8
function shortLabel(name: string) {
  const chars = Array.from(name.replace(/\s+/g, ' ').trim())
  return chars.length > LABEL_MAX_CHARS ? `${chars.slice(0, LABEL_MAX_CHARS - 1).join('')}…` : chars.join('')
}

function buildItems() {
  return props.prizes.map((p, i) => ({
    label: shortLabel(p.name),
    backgroundColor: p.soldOut ? SOLD_OUT_FILL : p.rewardType === 'points_refund' ? REFUND_FILL : FILLS[i % FILLS.length],
    labelColor: p.soldOut ? '#8a9096' : INK,
  }))
}

// A short tick per segment boundary, synthesised with WebAudio (no audio
// asset involved). Only ever plays when the parent enabled sound, and the
// context is created inside the tap that starts the spin so iOS allows it.
function tick() {
  if (!props.sound || !audio || audio.state !== 'running') return
  const now = audio.currentTime
  if (now - lastTick < 0.03) return
  lastTick = now
  const osc = audio.createOscillator()
  const gain = audio.createGain()
  osc.type = 'square'
  osc.frequency.value = 1300
  gain.gain.setValueAtTime(0.06, now)
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.035)
  osc.connect(gain).connect(audio.destination)
  osc.start(now)
  osc.stop(now + 0.04)
}

function onIndexChange() {
  tick()
  if (reducedMotion()) return
  bump.value = false
  requestAnimationFrame(() => { bump.value = true })
}

function create() {
  ready.value = false
  wheel?.remove()
  wheel = null
  if (!host.value || props.prizes.length === 0) return
  try {
    wheel = new Wheel(host.value, {
      items: buildItems(),
      radius: 0.96,
      pointerAngle: 0,
      isInteractive: false,
      borderWidth: 6,
      borderColor: '#e2483d',
      lineWidth: 1,
      lineColor: '#d5d9dc',
      itemLabelRadius: 0.92,
      itemLabelRadiusMax: 0.34,
      itemLabelAlign: 'right',
      itemLabelFont: 'sans-serif',
      itemLabelFontSizeMax: 22,
      onCurrentIndexChange: onIndexChange,
      onRest: (event) => {
        spinning.value = false
        restResolver?.(event.currentIndex)
        restResolver = null
      },
    })
    ready.value = true
  } catch {
    wheel = null
  }
}

onMounted(create)
watch(() => props.prizes, create, { deep: true })
onBeforeUnmount(() => {
  restResolver?.(-1)
  restResolver = null
  wheel?.remove()
  wheel = null
  void audio?.close()
  audio = null
})

/** Land on the segment whose prize id the backend returned. Resolves with
 * the index the wheel came to rest on, or `null` (without spinning) when that
 * id isn't a segment on this wheel — the caller then shows the result
 * directly rather than pretending the wheel picked it. */
function spinToPrize(prizeId: number | null): Promise<number | null> {
  const index = props.prizes.findIndex((p) => p.id === prizeId)
  if (!wheel || index < 0) return Promise.resolve(null)
  spinning.value = true
  return new Promise((resolve) => {
    restResolver = (landed) => resolve(landed)
    if (reducedMotion()) wheel!.spinToItem(index, 600, true, 0, 1)
    else wheel!.spinToItem(index, 4200, true, 5, 1)
  })
}

async function onHubClick() {
  if (!ready.value || props.busy || props.disabled || spinning.value) return
  if (props.sound) {
    try {
      audio ??= new AudioContext()
      await audio.resume()
    } catch {
      audio = null
    }
  }
  emit('spin')
}

const hubLabel = computed(() => (props.busy || spinning.value ? t('guest.wheelSpinning') : t('guest.wheelSpin')))
defineExpose({ spinToPrize, ready })
</script>

<template>
  <div class="wheel-wrap">
    <div class="pointer" :class="{ bump }" aria-hidden="true" @animationend="bump = false" />
    <div ref="host" class="wheel-host" role="img" :aria-label="t('guest.wheelAria')" />
    <button
      type="button" class="hub" :disabled="!ready || busy || disabled || spinning" :aria-label="hubLabel" @click="onHubClick"
    >
      {{ hubLabel }}
    </button>
  </div>
</template>

<style scoped>
.wheel-wrap { position: relative; width: min(320px, 84vw); aspect-ratio: 1; margin: 18px auto 10px; }
.wheel-host { position: absolute; inset: 0; }
.pointer {
  position: absolute; top: -14px; left: 50%; z-index: 3; width: 0; height: 0; transform: translateX(-50%); transform-origin: 50% 0;
  border-left: 14px solid transparent; border-right: 14px solid transparent; border-top: 30px solid #e2483d;
  filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.25));
}
.pointer.bump { animation: pointer-bump 0.12s ease-out; }
@keyframes pointer-bump { 0% { transform: translateX(-50%) rotate(0); } 40% { transform: translateX(-50%) rotate(-14deg); } 100% { transform: translateX(-50%) rotate(0); } }
.hub {
  position: absolute; top: 50%; left: 50%; z-index: 2; width: 84px; height: 84px; transform: translate(-50%, -50%);
  border: 5px solid #fff; border-radius: 50%; background: #e2483d; color: #fff; font: inherit; font-size: 15px; font-weight: 800;
  line-height: 1.15; padding: 0 4px; cursor: pointer; box-shadow: 0 3px 10px rgba(226, 72, 61, 0.45);
}
.hub:disabled { opacity: 0.75; cursor: default; }
.hub:focus-visible { outline: 3px solid #202326; outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { .pointer.bump { animation: none; } }
</style>
