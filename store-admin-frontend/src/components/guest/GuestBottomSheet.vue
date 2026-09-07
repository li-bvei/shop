<script setup lang="ts">
// Presentation-only mobile bottom sheet for the /pc/* pages. No business
// logic: the parent owns open/close state and whatever the sheet shows.
import { onBeforeUnmount, onMounted, watch } from 'vue'

const props = defineProps<{ open: boolean; title?: string; description?: string }>()
const emit = defineEmits<{ close: [] }>()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close')
}

function lock(on: boolean) {
  document.body.style.overflow = on ? 'hidden' : ''
}

watch(() => props.open, lock)
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  lock(false)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="g-sheet-fade">
      <div
        v-if="open"
        class="guest-shell g-sheet-backdrop"
        role="dialog"
        aria-modal="true"
        @click.self="emit('close')"
      >
        <div class="g-sheet">
          <div class="g-sheet-grip" aria-hidden="true" />
          <p v-if="title" class="g-sheet-title">{{ title }}</p>
          <p v-if="description" class="g-sheet-desc">{{ description }}</p>
          <div class="g-sheet-body">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.g-sheet-body {
  margin-top: 16px;
}

.g-sheet-fade-enter-active,
.g-sheet-fade-leave-active {
  transition: opacity 0.2s ease;
}

.g-sheet-fade-enter-from,
.g-sheet-fade-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .g-sheet-fade-enter-active,
  .g-sheet-fade-leave-active {
    transition: none;
  }
}
</style>
