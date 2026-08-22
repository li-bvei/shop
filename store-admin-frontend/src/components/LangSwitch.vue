<script setup lang="ts">
import { computed } from 'vue'
import { usePreferenceStore } from '@/stores/preference'
import type { AppLocale } from '@/i18n'

const preference = usePreferenceStore()

const options = [
  { label: '中文', value: 'zh' },
  { label: '日本語', value: 'ja' },
]

const modelValue = computed({
  get: () => preference.locale,
  set: (value: AppLocale) => preference.setLocale(value),
})
</script>

<template>
  <el-segmented v-model="modelValue" :options="options" class="lang-segmented" />
</template>
