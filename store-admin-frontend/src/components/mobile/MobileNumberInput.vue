<script setup lang="ts">
import { computed, ref, useId } from 'vue'

/** Phone-sized number field: 56px tall, 20px digits, always with a real
 * <label> (never a placeholder standing in for one). Binds `number | null`
 * exactly like the desktop MoneyInput does — shows ¥1,234 grouping when not
 * focused, plain digits while typing — so both forms write identical data. */
const model = defineModel<number | null | undefined>({ required: true })
const props = defineProps<{
  label: string
  prefix?: string
  disabled?: boolean
  decimal?: boolean
  hint?: string
  autoValue?: string
}>()

const id = useId()
const focused = ref(false)

const display = computed<string>({
  get() {
    if (model.value == null || Number.isNaN(model.value)) return ''
    return focused.value ? String(model.value) : model.value.toLocaleString('ja-JP')
  },
  set(raw: string) {
    const cleaned = props.decimal ? raw.replace(/[^\d.]/g, '') : raw.replace(/[^\d]/g, '')
    if (cleaned === '' || cleaned === '.') { model.value = null; return }
    const parsed = Number(cleaned)
    model.value = Number.isNaN(parsed) ? null : parsed
  },
})
function onInput(event: Event) { display.value = (event.target as HTMLInputElement).value }
</script>

<template>
  <div class="mnum">
    <label :for="id" class="mnum-label">{{ label }}</label>
    <div class="mnum-box" :class="{ 'is-disabled': disabled, 'is-auto': autoValue !== undefined }">
      <span v-if="prefix" class="mnum-prefix" aria-hidden="true">{{ prefix }}</span>
      <input
        v-if="autoValue === undefined"
        :id="id" class="mnum-input" type="text" :inputmode="decimal ? 'decimal' : 'numeric'" enterkeyhint="next"
        autocomplete="off" :disabled="disabled" :value="display"
        @input="onInput" @focus="focused = true" @blur="focused = false"
      >
      <output v-else :for="id" class="mnum-input mnum-auto">{{ autoValue }}</output>
    </div>
    <p v-if="hint" class="mnum-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.mnum { display: flex; flex-direction: column; gap: 6px; }
.mnum-label { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.mnum-box {
  display: flex; align-items: center; min-height: 56px; padding: 0 14px; gap: 6px;
  background: var(--surface); border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px;
}
.mnum-box:focus-within { border-color: var(--accent); }
.mnum-box.is-disabled, .mnum-box.is-auto { background: var(--surface-alt); }
.mnum-prefix { font-size: 20px; font-weight: 700; color: var(--text-secondary); }
.mnum-input {
  flex: 1; min-width: 0; height: 52px; border: 0; outline: 0; background: transparent; color: var(--text-primary);
  font: inherit; font-size: 20px; font-weight: 700; text-align: right;
}
.mnum-auto { display: flex; align-items: center; justify-content: flex-end; }
.mnum-hint { margin: 0; font-size: 16px; color: var(--text-secondary); }
</style>
