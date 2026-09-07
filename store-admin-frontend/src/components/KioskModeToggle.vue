<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

// Prominent switch between the two counter modes. `active` is the page
// currently showing.
defineProps<{ active: 'verify' | 'redeem' }>()

const { t } = useI18n()
const router = useRouter()

function go(name: string) {
  router.push({ name })
}
</script>

<template>
  <div class="kiosk-mode" role="tablist">
    <button
      type="button"
      role="tab"
      :class="{ on: active === 'verify' }"
      :aria-selected="active === 'verify'"
      @click="go('promo-verify')"
    >
      {{ t('promoVerify.modeReceipt') }}
    </button>
    <button
      type="button"
      role="tab"
      :class="{ on: active === 'redeem' }"
      :aria-selected="active === 'redeem'"
      @click="go('promo-redeem')"
    >
      {{ t('promoRedeem.modeUse') }}
    </button>
  </div>
</template>

<style scoped>
.kiosk-mode {
  display: flex;
  gap: 6px;
  padding: 5px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 999px;
}

.kiosk-mode button {
  flex: 1;
  min-width: 120px;
  padding: 10px 18px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.kiosk-mode button.on {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
</style>
