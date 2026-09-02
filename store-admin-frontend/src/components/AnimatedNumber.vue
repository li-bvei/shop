<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ value: number; duration?: number }>(), {
  duration: 750,
})

const display = ref(props.value)
let raf = 0

function tween(to: number) {
  cancelAnimationFrame(raf)
  const from = display.value
  if (from === to) {
    display.value = to
    return
  }
  const start = performance.now()
  const step = (now: number) => {
    const p = Math.min(1, (now - start) / props.duration)
    const eased = 1 - Math.pow(1 - p, 3)
    display.value = Math.round(from + (to - from) * eased)
    if (p < 1) raf = requestAnimationFrame(step)
    else display.value = to
  }
  raf = requestAnimationFrame(step)
}

watch(
  () => props.value,
  (v) => tween(v),
)

onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>{{ display.toLocaleString('ja-JP') }}</template>
