<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Lightweight in-page QR reader for the counter tablet. Uses the device
 * camera via getUserMedia + a per-frame jsQR decode on an offscreen
 * canvas — no navigation, no native camera app, no barcode-scanner
 * hardware. jsQR is loaded lazily so it never enters the first-paint
 * bundle. Needs a secure context (HTTPS or localhost); iOS Safari/Chrome
 * have no BarcodeDetector, which is why we ship our own decoder.
 */
const emit = defineEmits<{ decode: [value: string]; close: [] }>()
const { t } = useI18n()

const video = useTemplateRef<HTMLVideoElement>('video')
const errorKey = ref('')
let stream: MediaStream | null = null
let raf = 0
let canvas: HTMLCanvasElement | null = null
let done = false

async function tick(jsQR: typeof import('jsqr').default) {
  if (done || !video.value || video.value.readyState !== video.value.HAVE_ENOUGH_DATA) {
    raf = requestAnimationFrame(() => tick(jsQR))
    return
  }
  const v = video.value
  if (!canvas) canvas = document.createElement('canvas')
  canvas.width = v.videoWidth
  canvas.height = v.videoHeight
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return
  ctx.drawImage(v, 0, 0, canvas.width, canvas.height)
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const hit = jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' })
  if (hit && hit.data) {
    done = true
    stop()
    emit('decode', hit.data.trim())
    return
  }
  raf = requestAnimationFrame(() => tick(jsQR))
}

async function start() {
  if (!navigator.mediaDevices?.getUserMedia) {
    errorKey.value = 'qrScanner.unsupported'
    return
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
      audio: false,
    })
  } catch (err) {
    errorKey.value =
      err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError')
        ? 'qrScanner.denied'
        : 'qrScanner.unavailable'
    return
  }
  if (!video.value) return
  video.value.srcObject = stream
  await video.value.play().catch(() => {})
  const jsQR = (await import('jsqr')).default
  raf = requestAnimationFrame(() => tick(jsQR))
}

function stop() {
  cancelAnimationFrame(raf)
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
}

onMounted(start)
onBeforeUnmount(stop)
</script>

<template>
  <div class="qr-scanner" role="dialog" aria-modal="true">
    <div v-if="errorKey" class="qr-error">
      <p>{{ t(errorKey) }}</p>
      <button type="button" class="qr-btn" @click="$emit('close')">{{ t('qrScanner.back') }}</button>
    </div>
    <template v-else>
      <video ref="video" class="qr-video" playsinline muted />
      <div class="qr-frame" />
      <p class="qr-hint">{{ t('qrScanner.hint') }}</p>
      <button type="button" class="qr-btn" @click="$emit('close')">{{ t('qrScanner.cancel') }}</button>
    </template>
  </div>
</template>

<style scoped>
.qr-scanner {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: #000;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
}

.qr-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.qr-frame {
  position: relative;
  width: min(66vw, 320px);
  aspect-ratio: 1;
  border: 3px solid rgba(255, 255, 255, 0.9);
  border-radius: 18px;
  box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.5);
}

.qr-hint {
  position: relative;
  color: #fff;
  font-size: 15px;
  margin: 0;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
}

.qr-btn {
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.7);
  background: rgba(0, 0, 0, 0.35);
  color: #fff;
  border-radius: 10px;
  padding: 12px 28px;
  font-size: 16px;
  cursor: pointer;
}

.qr-error {
  position: relative;
  max-width: 320px;
  text-align: center;
  color: #fff;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 0 24px;
}

.qr-error p {
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
}
</style>
