<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useElLocale } from '@/locale/elLocale'
import { startVersionWatch } from '@/utils/versionCheck'

const elLocale = useElLocale()
const { t } = useI18n()

const newVersionAvailable = ref(false)
onMounted(() => {
  startVersionWatch(() => { newVersionAvailable.value = true })
})

function reloadNow() {
  window.location.reload()
}
</script>

<template>
  <el-config-provider :locale="elLocale">
    <RouterView />
    <div v-if="newVersionAvailable" class="new-version-banner">
      <span>{{ t('common.newVersionAvailable') }}</span>
      <el-button size="small" type="primary" @click="reloadNow">{{ t('common.reloadNow') }}</el-button>
    </div>
  </el-config-provider>
</template>

<style scoped>
.new-version-banner {
  position: fixed;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%);
  z-index: 3000;
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  border-radius: var(--radius-sm, 8px);
  padding: 10px 14px;
  font-size: 13px;
  color: var(--text-primary);
}
</style>
