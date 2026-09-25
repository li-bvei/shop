<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { More } from '@element-plus/icons-vue'
import { useNavItems, type NavItem } from '@/composables/useNavItems'
import { useAuthStore } from '@/stores/auth'
import MobileSheet from '@/components/mobile/MobileSheet.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { navItems, systemItems } = useNavItems()

// The four screens a manager actually lives in. Everything else — and any
// item the account isn't entitled to, which `navItems` has already dropped —
// stays reachable through その他, so role/feature gating is exactly the
// desktop sidebar's, never a second copy of it.
const PRIMARY_PATHS = ['/dashboard', '/monthly-analysis', '/daily-report', '/purchasing']
const SHORT_LABEL_KEYS: Record<string, string> = {
  '/dashboard': 'nav.tabHome',
  '/monthly-analysis': 'nav.tabManagement',
  '/daily-report': 'nav.tabDailyReport',
  '/purchasing': 'nav.tabPurchasing',
}

const primaryItems = computed<NavItem[]>(() => {
  // Staff and platform super admins have none of those four screens; give
  // them their own first few entries directly instead of an empty bar.
  if (auth.isSuperuser || auth.role === 'staff') return navItems.value.filter((i) => !i.external).slice(0, 4)
  return navItems.value.filter((i) => PRIMARY_PATHS.includes(i.path))
})
const overflowItems = computed<NavItem[]>(() => [
  ...navItems.value.filter((i) => !primaryItems.value.includes(i)),
  ...systemItems.value,
])

function labelKey(item: NavItem) { return SHORT_LABEL_KEYS[item.path] ?? item.labelKey }
function isActive(item: NavItem) { return route.path === item.path || route.path.startsWith(`${item.path}/`) }
const moreActive = computed(() => overflowItems.value.some((i) => !i.external && isActive(i)))

const moreOpen = ref(false)
watch(() => route.fullPath, () => { moreOpen.value = false })

function externalHref(path: string) { return router.resolve(path).href }
function go(item: NavItem) { moreOpen.value = false; router.push(item.path) }
</script>

<template>
  <nav class="mnav no-print" :aria-label="$t('nav.mobileNavLabel')">
    <router-link
      v-for="item in primaryItems" :key="item.path" :to="item.path" class="mnav-tab"
      :class="{ 'is-active': isActive(item) }" :aria-current="isActive(item) ? 'page' : undefined"
    >
      <el-icon :size="24"><component :is="item.icon" /></el-icon>
      <span class="mnav-label">{{ $t(labelKey(item)) }}</span>
    </router-link>
    <button
      v-if="overflowItems.length" type="button" class="mnav-tab" :class="{ 'is-active': moreActive }"
      aria-haspopup="dialog" @click="moreOpen = true"
    >
      <el-icon :size="24"><More /></el-icon>
      <span class="mnav-label">{{ $t('nav.tabMore') }}</span>
    </button>
  </nav>

  <MobileSheet v-model="moreOpen" :title="$t('nav.moreTitle')" :close-label="$t('nav.closeMenu')">
    <ul class="more-list">
      <li v-for="item in overflowItems" :key="item.path">
        <a
          v-if="item.external" :href="externalHref(item.path)" target="_blank" rel="noopener"
          class="more-row" @click="moreOpen = false"
        >
          <el-icon :size="24"><component :is="item.icon" /></el-icon>
          <span>{{ $t(item.labelKey) }}</span>
        </a>
        <button
          v-else type="button" class="more-row" :class="{ 'is-active': isActive(item) }"
          :aria-current="isActive(item) ? 'page' : undefined" @click="go(item)"
        >
          <el-icon :size="24"><component :is="item.icon" /></el-icon>
          <span>{{ $t(item.labelKey) }}</span>
        </button>
      </li>
    </ul>
  </MobileSheet>
</template>

<style scoped>
.mnav {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 80;
  display: flex; height: var(--mobile-nav-h, 60px); padding-bottom: env(safe-area-inset-bottom, 0px);
  background: var(--surface); border-top: 1px solid var(--border); box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.05);
}
.mnav-tab {
  flex: 1 1 0; min-width: 0; min-height: 56px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  padding: 4px 2px; border: 0; background: transparent; color: var(--text-secondary); text-decoration: none; cursor: pointer; font: inherit;
  -webkit-tap-highlight-color: transparent;
}
.mnav-label { font-size: 12px; font-weight: 700; line-height: 1.2; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mnav-tab.is-active { color: #05aa49; }
.mnav-tab:focus-visible, .more-row:focus-visible { outline: 3px solid #05aa49; outline-offset: -3px; border-radius: 8px; }
.more-list { list-style: none; margin: 0; padding: 0; }
.more-row {
  width: 100%; min-height: 60px; display: flex; align-items: center; gap: 16px; padding: 8px 12px;
  border: 0; border-bottom: 1px solid var(--border); background: transparent; color: var(--text-primary); text-decoration: none;
  font: inherit; font-size: 17px; font-weight: 600; text-align: left; cursor: pointer;
}
.more-row.is-active { color: #05aa49; }
</style>
