<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

/**
 * Full-screen notice for the counter kiosk when the signed-in account
 * can't operate it — currently only the head-office (本部 / admin) account,
 * which has no branch and so can't be attributed to a store.
 */
const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

function exit() {
  router.push({ name: auth.role === 'staff' ? 'my-availability' : 'dashboard' })
}
</script>

<template>
  <div class="kiosk-blocked">
    <div class="lock">🔒</div>
    <h1>{{ t('kioskBlocked.title') }}</h1>
    <p class="body">{{ t('kioskBlocked.body') }}</p>
    <p class="sub">{{ t('kioskBlocked.bodyZh') }}</p>
    <button type="button" class="exit-btn" @click="exit">{{ t('promoVerify.exit') }}</button>
  </div>
</template>

<style scoped>
.kiosk-blocked {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 24px;
  background: var(--bg);
  color: var(--text-primary);
  text-align: center;
}

.lock {
  font-size: 46px;
}

.kiosk-blocked h1 {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  max-width: 460px;
}

.body {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
  max-width: 420px;
  line-height: 1.6;
}

.sub {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0;
  max-width: 420px;
}

.exit-btn {
  margin-top: 10px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 9px 18px;
  font-size: 13px;
  cursor: pointer;
}
</style>
