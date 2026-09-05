<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * A yen amount field: binds a `number | null`, but shows the value
 * thousand-separated (¥1,234,567) so long amounts stay readable while
 * typing. The grouped form is shown when the field is not focused; while
 * focused it shows the plain digits so caret/selection behave normally.
 */
// `undefined` is accepted (a Record<string, number | null> index can be
// undefined under noUncheckedIndexedAccess) and treated the same as null.
const model = defineModel<number | null | undefined>({ required: true })
withDefaults(defineProps<{ disabled?: boolean; placeholder?: string }>(), { disabled: false })

const focused = ref(false)

const display = computed<string>({
  get() {
    if (model.value == null || Number.isNaN(model.value)) return ''
    return focused.value ? String(model.value) : model.value.toLocaleString('ja-JP')
  },
  set(raw: string) {
    const digits = raw.replace(/[^\d]/g, '')
    model.value = digits === '' ? null : Number(digits)
  },
})
</script>

<template>
  <el-input
    v-model="display"
    inputmode="numeric"
    :disabled="disabled"
    :placeholder="placeholder"
    @focus="focused = true"
    @blur="focused = false"
  >
    <template #prefix>¥</template>
  </el-input>
</template>
