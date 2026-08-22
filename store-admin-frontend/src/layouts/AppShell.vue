<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppSidebar from '@/components/AppSidebar.vue'
import AppTopbar from '@/components/AppTopbar.vue'

const route = useRoute()
const { t } = useI18n()

const routeTitleKeys: Record<string, string> = {
  'daily-report': 'dailyReport.pageTitle',
  purchasing: 'purchasing.pageTitle',
  suppliers: 'suppliers.pageTitle',
  staff: 'staff.pageTitle',
  settings: 'settings.pageTitle',
}

const pageTitle = computed(() => {
  const key = routeTitleKeys[route.name as string]
  return key ? t(key) : t('topbar.greeting')
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar class="no-print" />
    <div class="app-main">
      <AppTopbar class="no-print" :title="pageTitle" />
      <div class="app-main-body">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 224px 1fr;
  min-height: 100vh;
  background: var(--surface-alt);
}

.app-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.app-main-body {
  padding: 24px 28px 32px;
  flex: 1;
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 140ms ease-out;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .page-fade-enter-active,
  .page-fade-leave-active {
    transition: none;
  }
}

@media print {
  .app-shell {
    display: block;
    min-height: 0;
    background: none;
  }

  .app-main-body {
    padding: 0;
  }
}
</style>
