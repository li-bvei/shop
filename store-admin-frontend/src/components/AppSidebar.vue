<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Odometer,
  Document,
  Box,
  OfficeBuilding,
  User,
  Setting,
  TrendCharts,
  Calendar,
  Money,
  Lock,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'

const route = useRoute()
const auth = useAuthStore()
const branchStore = useBranchStore()
onMounted(() => branchStore.ensureLoaded())

const adminBranchNavItems = [
  { path: '/dashboard', icon: Odometer, labelKey: 'nav.dashboard' },
  { path: '/monthly-analysis', icon: TrendCharts, labelKey: 'nav.monthlyAnalysis' },
  { path: '/daily-report', icon: Document, labelKey: 'nav.dailyReport' },
  { path: '/purchasing', icon: Box, labelKey: 'nav.purchasing' },
  { path: '/suppliers', icon: OfficeBuilding, labelKey: 'nav.suppliers' },
  { path: '/staff', icon: User, labelKey: 'nav.staff' },
  { path: '/scheduling', icon: Calendar, labelKey: 'nav.scheduling' },
  { path: '/wages', icon: Money, labelKey: 'nav.wages' },
]

const staffNavItems = [
  { path: '/my-availability', icon: Calendar, labelKey: 'nav.myAvailability' },
  { path: '/my-shifts', icon: Document, labelKey: 'nav.myShifts' },
  { path: '/my-wages', icon: Money, labelKey: 'nav.myWages' },
]

const navItems = computed(() => (auth.role === 'staff' ? staffNavItems : adminBranchNavItems))
const systemItems = computed(() =>
  auth.role === 'staff'
    ? [{ path: '/my-password', icon: Lock, labelKey: 'nav.myPassword' }]
    : [{ path: '/settings', icon: Setting, labelKey: 'nav.settings' }],
)
</script>

<template>
  <aside class="app-sidebar">
    <div class="brand">
      <span class="dot" />
      <div class="brand-text">
        <span class="brand-name">{{ $t('nav.brandName') }}</span>
        <small class="brand-sub">{{ $t('nav.brandSub', { count: branchStore.list.length }) }}</small>
      </div>
    </div>

    <el-menu :default-active="route.path" router class="sidebar-menu">
      <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ $t(item.labelKey) }}</span>
      </el-menu-item>

      <div class="nav-group-label">{{ $t('nav.system') }}</div>
      <el-menu-item v-for="item in systemItems" :key="item.path" :index="item.path">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ $t(item.labelKey) }}</span>
      </el-menu-item>
    </el-menu>
  </aside>
</template>

<style scoped>
.app-sidebar {
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  padding: 20px 12px;
  transition: background-color 0.25s ease;
  height: 100%;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px 22px;
}

.brand .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.brand-sub {
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 400;
}

.sidebar-menu {
  border-right: none;
  background: transparent;
}

.nav-group-label {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 14px 10px 6px;
  font-weight: 600;
  letter-spacing: 0.03em;
}
</style>
