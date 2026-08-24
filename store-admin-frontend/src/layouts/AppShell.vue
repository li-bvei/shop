<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  products: 'products.pageTitle',
  inventory: 'inventory.pageTitle',
  staff: 'staff.pageTitle',
  settings: 'settings.pageTitle',
}

const pageTitle = computed(() => {
  const key = routeTitleKeys[route.name as string]
  return key ? t(key) : t('topbar.greeting')
})

// Below the mobile breakpoint the sidebar becomes a slide-in drawer instead
// of a permanent grid column (see .app-shell's media query) — this just
// tracks whether it's open. Any navigation closes it again, since staying
// open over the new page would just be the old page's menu covering the
// content the user just asked to see.
const sidebarOpen = ref(false)
watch(() => route.fullPath, () => { sidebarOpen.value = false })
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-open': sidebarOpen }">
    <AppSidebar class="no-print" :open="sidebarOpen" @close="sidebarOpen = false" />
    <div v-if="sidebarOpen" class="sidebar-backdrop no-print" @click="sidebarOpen = false" />
    <div class="app-main">
      <AppTopbar class="no-print" :title="pageTitle" @toggle-sidebar="sidebarOpen = !sidebarOpen" />
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

.sidebar-backdrop {
  display: none;
}

@media (max-width: 768px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    z-index: 90;
  }

  .app-main-body {
    padding: 16px 16px 24px;
  }
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
