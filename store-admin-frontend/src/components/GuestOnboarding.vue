<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { GuestCard } from '@/api/guest'

const props = defineProps<{ card: GuestCard }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const c = computed(() => props.card.campaign ?? {})

interface Slide {
  emoji: string
  title: string
  body: string
}

const slides = computed<Slide[]>(() => {
  const list: Slide[] = [
    {
      emoji: '🧾',
      title: t('guest.onboard.s1Title'),
      body: t('guest.onboard.s1Body', { yen: 1000, pts: c.value.pointsPer1000yen ?? 0 }),
    },
  ]
  if (props.card.stampTarget) {
    list.push({
      emoji: '🎫',
      title: t('guest.onboard.s2Title'),
      body: t('guest.onboard.s2Body', { n: props.card.stampTarget }),
    })
  }
  list.push({ emoji: '🎁', title: t('guest.onboard.s3Title'), body: t('guest.onboard.s3Body') })
  list.push({ emoji: '🍰', title: t('guest.onboard.s4Title'), body: t('guest.onboard.s4Body') })
  list.push({ emoji: '🔑', title: t('guest.onboard.s5Title'), body: t('guest.onboard.s5Body') })
  return list
})

const index = ref(0)
const isLast = computed(() => index.value >= slides.value.length - 1)
const current = computed(() => slides.value[Math.min(index.value, slides.value.length - 1)] as Slide)

function next() {
  if (isLast.value) emit('close')
  else index.value += 1
}
function skip() {
  emit('close')
}

let touchX: number | null = null
function onTouchStart(e: TouchEvent) {
  touchX = e.changedTouches[0]?.clientX ?? null
}
function onTouchEnd(e: TouchEvent) {
  const end = e.changedTouches[0]?.clientX
  if (touchX === null || end === undefined) return
  const dx = end - touchX
  if (dx < -40 && !isLast.value) index.value += 1
  else if (dx > 40 && index.value > 0) index.value -= 1
}
</script>

<template>
  <div class="onboard" @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd">
    <button type="button" class="skip" @click="skip">{{ t('guest.onboard.skip') }}</button>

    <div class="stage">
      <div :key="index" class="slide">
        <div class="emoji">{{ current.emoji }}</div>
        <h2>{{ current.title }}</h2>
        <p>{{ current.body }}</p>
      </div>
    </div>

    <div class="dots">
      <span v-for="(s, i) in slides" :key="i" :class="{ on: i === index }" />
    </div>

    <button type="button" class="cta" @click="next">
      {{ isLast ? t('guest.onboard.start') : t('guest.onboard.next') }}
    </button>
  </div>
</template>

<style scoped>
.onboard {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 56px 28px 40px;
  box-sizing: border-box;
}

.skip {
  position: absolute;
  top: 16px;
  right: 18px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 13px;
  cursor: pointer;
}

.stage {
  flex: 1;
  display: flex;
  align-items: flex-start;
  padding-top: 14vh;
  width: 100%;
  max-width: 340px;
}

.slide {
  width: 100%;
  text-align: center;
}

.emoji {
  font-size: 76px;
  line-height: 1;
  margin-bottom: 28px;
}

.slide h2 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.slide p {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin: 0;
}

.slide {
  animation: slide-in 0.22s ease;
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateX(14px);
  }
}

.dots {
  display: flex;
  gap: 7px;
  margin: 24px 0;
}

.dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border);
  transition: background 0.2s, width 0.2s;
}

.dots span.on {
  background: var(--accent);
  width: 20px;
  border-radius: 4px;
}

.cta {
  width: 100%;
  max-width: 340px;
  height: 48px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

@media (prefers-reduced-motion: reduce) {
  .slide {
    animation: none;
  }
}
</style>
