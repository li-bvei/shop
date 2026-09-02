<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

const props = defineProps<{ label: string; disabled?: boolean }>()
const emit = defineEmits<{ confirm: [] }>()

const THUMB = 48

const track = ref<HTMLElement>()
const x = ref(0)
const dragging = ref(false)
const done = ref(false)
let startPointer = 0
let maxX = 0

function begin(clientX: number) {
  if (props.disabled || done.value) return
  dragging.value = true
  startPointer = clientX - x.value
  maxX = Math.max(0, (track.value?.clientWidth ?? 0) - THUMB - 6)
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', end)
}
function moveTo(clientX: number) {
  if (!dragging.value) return
  x.value = Math.max(0, Math.min(maxX, clientX - startPointer))
}
function end() {
  if (!dragging.value) return
  dragging.value = false
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', end)
  if (x.value >= maxX * 0.9) {
    x.value = maxX
    done.value = true
    emit('confirm')
  } else {
    x.value = 0
  }
}

function onMouseDown(e: MouseEvent) {
  begin(e.clientX)
}
function onMouseMove(e: MouseEvent) {
  moveTo(e.clientX)
}
function onTouchStart(e: TouchEvent) {
  const t = e.touches[0]
  if (t) begin(t.clientX)
}
function onTouchMove(e: TouchEvent) {
  const t = e.touches[0]
  if (t) moveTo(t.clientX)
}

function reset() {
  done.value = false
  x.value = 0
}
defineExpose({ reset })

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', end)
})
</script>

<template>
  <div
    ref="track"
    class="s2c"
    :class="{ disabled, done }"
    @mousedown="onMouseDown"
    @touchstart.passive="onTouchStart"
    @touchmove.passive="onTouchMove"
    @touchend="end"
    @touchcancel="end"
  >
    <span class="s2c-label">{{ label }}</span>
    <div
      class="s2c-thumb"
      :style="{ transform: `translateX(${x}px)`, transition: dragging ? 'none' : 'transform 0.22s ease' }"
    >
      {{ done ? '✓' : '›' }}
    </div>
  </div>
</template>

<style scoped>
.s2c {
  position: relative;
  height: 52px;
  border-radius: 26px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  overflow: hidden;
  user-select: none;
  touch-action: pan-y;
}

.s2c.disabled {
  opacity: 0.5;
}

.s2c-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  padding-left: 40px;
}

.s2c.done .s2c-label {
  color: var(--success);
}

.s2c-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 48px;
  height: 44px;
  border-radius: 22px;
  background: var(--accent);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
}

.s2c.done .s2c-thumb {
  background: var(--success);
}
</style>
