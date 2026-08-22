<script setup lang="ts">
import { Sunny, Moon } from '@element-plus/icons-vue'
import { usePreferenceStore } from '@/stores/preference'

const preference = usePreferenceStore()
</script>

<template>
  <el-button circle class="theme-btn" :aria-label="$t('topbar.toggleTheme')" @click="preference.toggleTheme()">
    <el-icon><Sunny v-if="preference.theme === 'dark'" /><Moon v-else /></el-icon>
  </el-button>
</template>

<style scoped>
.theme-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-secondary);
}
</style>
