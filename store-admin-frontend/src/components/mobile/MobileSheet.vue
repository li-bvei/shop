<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'

const props = defineProps<{ modelValue: boolean; title: string; closeLabel: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const panel = ref<HTMLElement>()
let previouslyFocused: HTMLElement | null = null

function close() { emit('update:modelValue', false) }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') close() }

watch(() => props.modelValue, async (open) => {
  if (open) {
    previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    document.body.style.overflow = 'hidden'
    await nextTick()
    panel.value?.focus()
  } else {
    document.body.style.overflow = ''
    previouslyFocused?.focus?.()
    previouslyFocused = null
  }
})
onBeforeUnmount(() => { document.body.style.overflow = '' })
</script>

<template>
  <Teleport to="body">
    <Transition name="msheet">
      <div v-if="modelValue" class="msheet-root no-print" @keydown="onKeydown">
        <div class="msheet-backdrop" @click="close" />
        <section
          ref="panel" class="msheet-panel" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1"
        >
          <header class="msheet-head">
            <h2 class="msheet-title">{{ title }}</h2>
            <button type="button" class="msheet-close" :aria-label="closeLabel" @click="close">
              <el-icon :size="26"><Close /></el-icon>
            </button>
          </header>
          <div class="msheet-body"><slot /></div>
          <footer v-if="$slots.footer" class="msheet-foot"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.msheet-root { position: fixed; inset: 0; z-index: 120; display: flex; align-items: flex-end; justify-content: center; }
.msheet-backdrop { position: absolute; inset: 0; background: rgba(20, 23, 26, 0.5); }
.msheet-panel {
  position: relative; width: 100%; max-width: 640px; max-height: 88vh; max-height: 88dvh;
  display: flex; flex-direction: column; outline: none;
  background: var(--surface); color: var(--text-primary); border-radius: 20px 20px 0 0;
  box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.18);
}
.msheet-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px 6px 20px; border-bottom: 1px solid var(--border); }
.msheet-title { margin: 0; font-size: 18px; font-weight: 700; }
.msheet-close {
  width: 52px; height: 52px; display: inline-flex; align-items: center; justify-content: center;
  border: 0; background: transparent; color: var(--text-primary); border-radius: 12px; cursor: pointer;
}
.msheet-body { overflow-y: auto; -webkit-overflow-scrolling: touch; padding: 16px 20px; flex: 1; }
.msheet-foot { padding: 12px 20px calc(12px + env(safe-area-inset-bottom, 0px)); border-top: 1px solid var(--border); background: var(--surface); }
.msheet-body:last-child { padding-bottom: calc(16px + env(safe-area-inset-bottom, 0px)); }
.msheet-enter-active, .msheet-leave-active { transition: opacity 0.2s ease; }
.msheet-enter-active .msheet-panel, .msheet-leave-active .msheet-panel { transition: transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1); }
.msheet-enter-from, .msheet-leave-to { opacity: 0; }
.msheet-enter-from .msheet-panel, .msheet-leave-to .msheet-panel { transform: translateY(100%); }
@media (prefers-reduced-motion: reduce) {
  .msheet-enter-active, .msheet-leave-active, .msheet-enter-active .msheet-panel, .msheet-leave-active .msheet-panel { transition: none; }
}
</style>
