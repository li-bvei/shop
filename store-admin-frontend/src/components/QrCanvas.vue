<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import QRCode from 'qrcode'

const props = withDefaults(defineProps<{ value: string; size?: number }>(), { size: 220 })

const canvas = ref<HTMLCanvasElement>()

async function render() {
  if (!canvas.value || !props.value) return
  await QRCode.toCanvas(canvas.value, props.value, {
    width: props.size,
    margin: 1,
    errorCorrectionLevel: 'M',
    color: { dark: '#1d1d1f', light: '#ffffff' },
  })
}

onMounted(render)
watch(() => [props.value, props.size], render)
</script>

<template>
  <canvas ref="canvas" class="qr-canvas" :width="size" :height="size" :aria-label="value" />
</template>

<style scoped>
.qr-canvas {
  display: block;
  width: v-bind('size + "px"');
  height: v-bind('size + "px"');
  border-radius: 8px;
  background: #fff;
}
</style>
