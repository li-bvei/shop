<script setup lang="ts">
import { computed, useId } from 'vue'
import { Minus, Plus } from '@element-plus/icons-vue'

/** − / number / + for counting things (cash-register notes and coins):
 * 52px buttons, so the common "one more" is a thumb tap, and the number is
 * still directly typeable. */
const model = defineModel<number | null | undefined>({ required: true })
const props = defineProps<{ label: string; minusLabel: string; plusLabel: string; disabled?: boolean }>()

const id = useId()
const current = computed(() => model.value ?? 0)
function set(next: number) { model.value = Math.max(0, Math.floor(next)) }
function onInput(event: Event) {
  const digits = (event.target as HTMLInputElement).value.replace(/[^\d]/g, '')
  model.value = digits === '' ? null : Number(digits)
}
</script>

<template>
  <div class="mstep" role="group" :aria-labelledby="`${id}-l`">
    <span :id="`${id}-l`" class="mstep-label">{{ label }}</span>
    <button type="button" class="mstep-btn" :aria-label="`${label} ${minusLabel}`" :disabled="props.disabled || current <= 0" @click="set(current - 1)">
      <el-icon :size="22"><Minus /></el-icon>
    </button>
    <input
      class="mstep-input" type="text" inputmode="numeric" autocomplete="off" :aria-label="label"
      :disabled="props.disabled" :value="model == null ? '' : String(model)" placeholder="0" @input="onInput"
    >
    <button type="button" class="mstep-btn" :aria-label="`${label} ${plusLabel}`" :disabled="props.disabled" @click="set(current + 1)">
      <el-icon :size="22"><Plus /></el-icon>
    </button>
  </div>
</template>

<style scoped>
.mstep { display: flex; align-items: center; gap: 6px; }
.mstep-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.mstep-btn {
  width: 52px; height: 52px; flex: none; display: inline-flex; align-items: center; justify-content: center;
  border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; background: var(--surface); color: var(--text-primary); cursor: pointer;
}
.mstep-btn:active:not(:disabled) { background: var(--surface-alt); }
.mstep-btn:disabled { opacity: 0.4; cursor: default; }
.mstep-input {
  width: 64px; height: 52px; min-width: 0; flex: none; text-align: center; font: inherit; font-size: 22px; font-weight: 700;
  color: var(--text-primary); background: var(--surface); border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; outline: 0;
}
.mstep-input:focus { border-color: var(--accent); }
</style>
