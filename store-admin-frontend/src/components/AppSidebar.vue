<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Close } from '@element-plus/icons-vue'
import { useNavItems } from '@/composables/useNavItems'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'

defineProps<{ open?: boolean }>()
defineEmits<{ close: [] }>()

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const branchStore = useBranchStore()
onMounted(() => branchStore.ensureLoaded())

// The chain's own name, as entered by the platform super admin (and editable
// in Settings). The platform console belongs to no single chain, so it shows
// the product name instead.
const brandName = computed(() => {
  if (auth.isSuperuser) return t('login.title')
  const zh = auth.organizationNameZh
  const ja = auth.organizationNameJa
  return locale.value === 'ja' ? ja || zh : zh || ja
})

function externalHref(path: string) {
  return router.resolve(path).href
}

const { navItems, systemItems } = useNavItems()
</script>

<template>
  <aside class="app-sidebar" :class="{ 'is-open': open }">
    <div class="brand">
      <span class="dot" />
      <div class="brand-text">
        <span class="brand-name">{{ brandName }}</span>
        <small class="brand-sub">{{ $t('nav.brandSub', { count: branchStore.list.length }) }}</small>
      </div>
      <button type="button" class="close-btn" :aria-label="$t('common.cancel')" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <el-menu :default-active="route.path" router class="sidebar-menu">
      <template v-for="item in navItems" :key="item.path">
        <a
          v-if="item.external"
          :href="externalHref(item.path)"
          target="_blank"
          rel="noopener"
          class="el-menu-item external-menu-item"
          @click="$emit('close')"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ $t(item.labelKey) }}</span>
        </a>
        <el-menu-item v-else :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ $t(item.labelKey) }}</span>
        </el-menu-item>
      </template>

      <template v-if="systemItems.length">
        <div class="nav-group-label">{{ $t('nav.system') }}</div>
        <el-menu-item v-for="item in systemItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ $t(item.labelKey) }}</span>
        </el-menu-item>
      </template>
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

/* The counter-reception link is a real <a target="_blank">, not an
   el-menu-item — borrow the menu-item look but drop the anchor defaults. */
.external-menu-item {
  text-decoration: none;
  color: var(--el-menu-text-color);
}

.external-menu-item:hover {
  color: var(--el-menu-hover-text-color, var(--el-menu-text-color));
}

.close-btn {
  display: none;
  margin-left: auto;
  background: none;
  border: none;
  padding: 6px;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
}

@media (max-width: 768px) {
  .app-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 260px;
    z-index: 100;
    overflow-y: auto;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: 2px 0 12px rgba(0, 0, 0, 0.15);
  }

  .app-sidebar.is-open {
    transform: translateX(0);
  }

  .close-btn {
    display: inline-flex;
  }
}
</style>
