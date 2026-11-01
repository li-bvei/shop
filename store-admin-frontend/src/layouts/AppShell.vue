<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppSidebar from '@/components/AppSidebar.vue'
import AppTopbar from '@/components/AppTopbar.vue'
import MobileBottomNav from '@/components/mobile/MobileBottomNav.vue'
import { useIsMobile } from '@/composables/useIsMobile'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const { t } = useI18n()
const auth = useAuthStore()

const routeTitleKeys: Record<string, string> = {
  lottery: 'lottery.pageTitle',
  promotions: 'promotions.pageTitle',
  'daily-report': 'dailyReport.pageTitle',
  purchasing: 'purchasing.pageTitle',
  suppliers: 'suppliers.pageTitle',
  products: 'products.pageTitle',
  inventory: 'inventory.pageTitle',
  staff: 'staff.pageTitle',
  settings: 'settings.pageTitle',
  'platform-overview': 'platformOverview.title',
  'platform-manage': 'platformFeatures.title',
}

// Hour buckets, not a fixed string — this used to say "おはようございます"
// (good morning) all day regardless of the actual time.
function greetingKey() {
  const hour = new Date().getHours()
  if (hour >= 5 && hour < 11) return 'topbar.greetingMorning'
  if (hour >= 11 && hour < 18) return 'topbar.greetingAfternoon'
  if (hour >= 18 && hour < 23) return 'topbar.greetingEvening'
  return 'topbar.greetingLateNight'
}

const pageTitle = computed(() => {
  const key = routeTitleKeys[route.name as string]
  return key ? t(key) : t(greetingKey())
})

// Below the mobile breakpoint the sidebar becomes a slide-in drawer instead
// of a permanent grid column (see .app-shell's media query) — this just
// tracks whether it's open. Any navigation closes it again, since staying
// open over the new page would just be the old page's menu covering the
// content the user just asked to see.
const isMobile = useIsMobile()
const sidebarOpen = ref(false)
watch(() => route.fullPath, () => { sidebarOpen.value = false })
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-open': sidebarOpen }">
    <AppSidebar class="no-print" :open="sidebarOpen" @close="sidebarOpen = false" />
    <div v-if="sidebarOpen" class="sidebar-backdrop no-print" @click="sidebarOpen = false" />
    <div class="app-main">
      <AppTopbar class="no-print" :title="pageTitle" @toggle-sidebar="sidebarOpen = !sidebarOpen" />
      <!-- Standing banner for the sales-demo tenant. Deliberately not
           dismissible and present on EVERY screen: the one thing that must
           never happen is somebody taking a figure out of a demo session
           and believing it is their own. `no-print` so it doesn't follow
           the data into an exported report. -->
      <div v-if="auth.isDemo" class="demo-banner no-print">
        <span class="demo-badge">{{ t('demo.badge') }}</span>
        <span class="demo-text">{{ t('demo.bannerText') }}</span>
      </div>
      <div class="app-main-body">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </div>
    <MobileBottomNav v-if="isMobile" />
  </div>
</template>

<style scoped>
/* Sticky so the banner stays visible while scrolling a long report — a
   warning that scrolls away stops being a warning. */
.demo-banner {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 20px;
  background: #fff7e6;
  border-bottom: 1px solid #f0c78a;
  color: #8a5a00;
  font-size: 12.5px;
}

.demo-badge {
  font-weight: 700;
  letter-spacing: 0.04em;
  background: #f0a020;
  color: #fff;
  border-radius: 4px;
  padding: 1px 8px;
  flex-shrink: 0;
}

/* The explanatory half wraps instead of being clipped on a phone — the
   badge alone doesn't say what it means. */
.demo-text {
  min-width: 0;
}

@media (max-width: 768px) {
  .demo-banner {
    padding: 8px 14px;
  }
}

.app-shell {
  --mobile-nav-h: calc(60px + env(safe-area-inset-bottom, 0px));
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
    /* Room for the fixed bottom bar (and the iOS home indicator) so the last
       row of any page is never hidden underneath it. */
    padding: 16px 16px calc(var(--mobile-nav-h) + 24px);
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
