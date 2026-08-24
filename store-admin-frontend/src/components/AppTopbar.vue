<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowDown, Menu } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName } from '@/utils/format'
import LangSwitch from './LangSwitch.vue'
import ThemeSwitch from './ThemeSwitch.vue'

defineProps<{ title: string }>()
defineEmits<{ 'toggle-sidebar': [] }>()

const { t, locale } = useI18n()
const auth = useAuthStore()
const router = useRouter()
const branchStore = useBranchStore()
onMounted(() => branchStore.ensureLoaded())

// Admins manage every branch, so "all N branches" is accurate for them —
// a branch account only ever sees its own data, so showing that same pill
// would be misleading; show their actual branch name instead.
const branchPillLabel = computed(() => {
  if (auth.role === 'admin') return t('topbar.allBranches', { count: branchStore.list.length })
  return branchDisplayName(branchStore.list.find((b) => b.id === auth.branchId), locale.value, auth.branchId ?? '')
})

function handleLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <header class="app-topbar">
    <div class="topbar-left">
      <button type="button" class="menu-btn" :aria-label="$t('nav.system')" @click="$emit('toggle-sidebar')">
        <el-icon><Menu /></el-icon>
      </button>
      <h2>{{ title }}</h2>
    </div>
    <div class="topbar-right">
      <el-tag round class="branch-pill">{{ branchPillLabel }}</el-tag>
      <LangSwitch />
      <ThemeSwitch />
      <el-dropdown trigger="click" @command="handleLogout">
        <span class="avatar-trigger">
          <el-avatar :size="30" class="avatar">{{ auth.displayName }}</el-avatar>
          <el-icon class="caret"><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">{{ $t('common.logout') }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.app-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 28px;
  border-bottom: 1px solid var(--border);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.app-topbar h2 {
  font-size: 17px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.menu-btn {
  display: none;
  background: none;
  border: none;
  padding: 6px;
  margin-left: -6px;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
  flex-shrink: 0;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.branch-pill {
  font-size: 12.5px;
  background: var(--surface);
  border-color: var(--border);
  color: var(--text-secondary);
  padding: 6px 12px;
  height: auto;
}

@media (max-width: 768px) {
  .app-topbar {
    padding: 14px 16px;
  }

  .menu-btn {
    display: inline-flex;
  }

  .branch-pill {
    display: none;
  }
}

@media (max-width: 480px) {
  .app-topbar h2 {
    font-size: 15px;
  }
}

.avatar-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.avatar {
  background: var(--avatar-bg);
  color: var(--avatar-text);
  font-size: 12px;
  font-weight: 600;
}

.caret {
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
