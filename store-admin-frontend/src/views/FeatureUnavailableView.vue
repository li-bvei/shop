<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const moduleKey = computed(() => String(route.query.m ?? ''))
const moduleName = computed(() =>
  moduleKey.value ? t(`featureUnavailable.modules.${moduleKey.value}`) : '',
)

function goHome() {
  router.push({ name: auth.role === 'staff' ? 'my-availability' : 'dashboard' })
}
</script>

<template>
  <div class="feature-unavailable">
    <div class="icon">🔒</div>
    <h1>{{ t('featureUnavailable.title') }}</h1>
    <p class="body">
      <template v-if="moduleName">{{ t('featureUnavailable.bodyNamed', { module: moduleName }) }}</template>
      <template v-else>{{ t('featureUnavailable.body') }}</template>
    </p>
    <p class="contact">{{ t('featureUnavailable.contact') }}</p>
    <el-button type="primary" @click="goHome">{{ t('featureUnavailable.backHome') }}</el-button>
  </div>
</template>

<style scoped>
.feature-unavailable {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  text-align: center;
  padding: 24px;
}

.icon {
  font-size: 48px;
}

.feature-unavailable h1 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.body {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
  max-width: 420px;
  line-height: 1.6;
}

.contact {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0 0 8px;
}
</style>
