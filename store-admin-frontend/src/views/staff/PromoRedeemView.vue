<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import { redeemVoucher, verifyVouchers, type VoucherRow } from '@/api/promotions'
import KioskBlockedNotice from '@/components/KioskBlockedNotice.vue'
import KioskModeToggle from '@/components/KioskModeToggle.vue'
import QrScanner from '@/components/QrScanner.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

// A head-office (本部 / admin) account has no branch, so it can't redeem
// at a store counter — see promotions.views VoucherViewSet.redeem.
const headOfficeBlocked = computed(() => auth.role === 'admin' && !auth.branchId)

type Stage = 'scan' | 'list'
const stage = ref<Stage>('scan')
const scanInput = ref<HTMLInputElement>()

const query = ref('')
const nameQuery = ref('')
const tailQuery = ref('')
const mode = ref<'code' | 'card' | 'phone' | 'name'>('code')
const vouchers = ref<VoucherRow[]>([])
const busy = ref(false)

const isManager = computed(() => auth.role === 'branch' || auth.role === 'admin')

function focusScan() {
  nextTick(() => scanInput.value?.focus())
}

function reset() {
  stage.value = 'scan'
  query.value = ''
  nameQuery.value = ''
  tailQuery.value = ''
  vouchers.value = []
  focusScan()
}

function onScanEnter(event: KeyboardEvent) {
  if (event.isComposing || (event as KeyboardEvent & { keyCode: number }).keyCode === 229) return
  lookup()
}

// --- Tablet camera scan ---------------------------------------------------
const scanning = ref(false)

function onScanDecode(payload: string) {
  scanning.value = false
  let value = payload.trim()
  try {
    const url = new URL(value)
    value = url.searchParams.get('code') || url.searchParams.get('card') || url.pathname.split('/').filter(Boolean).pop() || value
  } catch {
    /* not a URL — use as-is */
  }
  // An 8-char redemption code vs. a longer card token.
  mode.value = /^[A-Z0-9]{8}$/i.test(value) ? 'code' : 'card'
  query.value = value
  lookup()
}

const canLookup = computed(() =>
  mode.value === 'name'
    ? nameQuery.value.trim().length > 0 || tailQuery.value.trim().length > 0
    : query.value.trim().length > 0,
)

function currentQuery() {
  const raw = query.value.trim()
  return mode.value === 'name'
    ? { name: nameQuery.value.trim(), phoneTail: tailQuery.value.trim() }
    : mode.value === 'code'
      ? { redemptionCode: raw }
      : mode.value === 'phone'
        ? { phone: raw }
        : { cardToken: raw }
}

async function lookup() {
  if (!canLookup.value || busy.value) return
  busy.value = true
  try {
    vouchers.value = await verifyVouchers(currentQuery())
    stage.value = 'list'
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) ElMessage.warning(t('promoRedeem.notFound'))
    else ElMessage.error(t('promoRedeem.lookupFailed'))
    query.value = ''
    focusScan()
  } finally {
    busy.value = false
  }
}

async function handleRedeem(v: VoucherRow) {
  if (busy.value) return
  if (!v.redeemable) {
    ElMessage.warning(v.expired ? t('promoRedeem.expired') : t('promoRedeem.notRedeemable'))
    return
  }
  if (v.requiresManualApproval && !isManager.value) {
    ElMessage.error(t('promoRedeem.needsManager'))
    return
  }

  let spendAmountYen: number | undefined
  if (v.minSpendYen) {
    try {
      const { value } = await ElMessageBox.prompt(
        t('promoRedeem.minSpendPrompt', { yen: v.minSpendYen.toLocaleString('ja-JP') }),
        t('promoRedeem.minSpendTitle'),
        {
          confirmButtonText: t('common.confirm'),
          cancelButtonText: t('common.cancel'),
          inputPattern: /^\d+$/,
          inputErrorMessage: t('promoRedeem.minSpendInvalid'),
        },
      )
      spendAmountYen = Number(value)
    } catch {
      return
    }
  }
  if (v.requiresManualApproval && isManager.value) {
    try {
      await ElMessageBox.confirm(t('promoRedeem.approveConfirm', { label: v.label }), t('promoRedeem.approveTitle'), {
        type: 'warning',
        confirmButtonText: t('promoRedeem.approve'),
        cancelButtonText: t('common.cancel'),
      })
    } catch {
      return
    }
  }

  busy.value = true
  try {
    await redeemVoucher({ redemptionCode: v.redemptionCode, spendAmountYen })
    ElMessage.success(t('promoRedeem.redeemedToast', { label: v.label }))
    // Stay on this customer's list so several coupons don't need re-scanning.
    vouchers.value = await verifyVouchers(currentQuery())
  } catch (err) {
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('head-office-account-cannot-scan')) ElMessage.error(t('kioskBlocked.body'))
      else if (body.includes('already-redeemed')) ElMessage.error(t('promoRedeem.alreadyRedeemed'))
      else if (body.includes('expired')) ElMessage.error(t('promoRedeem.expired'))
      else if (body.includes('min-spend')) ElMessage.error(t('promoRedeem.minSpendNotMet'))
      else if (body.includes('manager-approval')) ElMessage.error(t('promoRedeem.needsManager'))
      else ElMessage.error(t('promoRedeem.redeemFailed'))
    } else {
      ElMessage.error(t('promoRedeem.redeemFailed'))
    }
  } finally {
    busy.value = false
  }
}

function exit() {
  router.push({ name: auth.role === 'staff' ? 'my-availability' : 'dashboard' })
}

onMounted(() => {
  // Arrived from the receipt screen ("use this customer's coupons") —
  // prefill and look up straight away, no re-scan.
  const card = (route.query.card as string) || ''
  const phone = (route.query.phone as string) || ''
  if (card) {
    mode.value = 'card'
    query.value = card
    lookup()
  } else if (phone) {
    mode.value = 'phone'
    query.value = phone
    lookup()
  } else {
    focusScan()
  }
})
</script>

<template>
  <KioskBlockedNotice v-if="headOfficeBlocked" />
  <div v-else class="kiosk">
    <header class="kiosk-head">
      <KioskModeToggle active="redeem" />
      <div class="head-right">
        <span class="operator">{{ auth.displayName || auth.account }}</span>
        <button type="button" class="exit-btn" @click="exit">{{ t('promoVerify.exit') }}</button>
      </div>
    </header>

    <main class="kiosk-body">
      <section v-if="stage === 'scan'" class="stage">
        <h1>{{ t('promoRedeem.scanPrompt') }}</h1>
        <div class="mode-toggle">
          <button type="button" :class="{ active: mode === 'code' }" @click="mode = 'code'; focusScan()">
            {{ t('promoRedeem.modeCode') }}
          </button>
          <button type="button" :class="{ active: mode === 'card' }" @click="mode = 'card'; focusScan()">
            {{ t('promoRedeem.modeCard') }}
          </button>
          <button type="button" :class="{ active: mode === 'phone' }" @click="mode = 'phone'; focusScan()">
            {{ t('promoRedeem.modePhone') }}
          </button>
          <button type="button" :class="{ active: mode === 'name' }" @click="mode = 'name'">
            {{ t('promoRedeem.modeName') }}
          </button>
        </div>

        <template v-if="mode === 'name'">
          <input
            v-model="nameQuery"
            class="big-input"
            :placeholder="t('promoRedeem.placeholder_name')"
            autocomplete="off"
            @keydown.enter="onScanEnter"
          />
          <input
            v-model="tailQuery"
            class="big-input"
            inputmode="numeric"
            maxlength="4"
            :placeholder="t('promoRedeem.placeholder_tail')"
            autocomplete="off"
            @keydown.enter="onScanEnter"
            @input="tailQuery = tailQuery.replace(/\D/g, '').slice(0, 4)"
          />
        </template>
        <input
          v-else
          ref="scanInput"
          v-model="query"
          class="big-input"
          :placeholder="t(`promoRedeem.placeholder_${mode}`)"
          autocomplete="off"
          @keydown.enter="onScanEnter"
          @blur="focusScan"
        />

        <button type="button" class="primary-btn" :disabled="busy || !canLookup" @click="lookup">
          {{ t('promoRedeem.lookup') }}
        </button>
        <button v-if="mode !== 'name'" type="button" class="scan-cam-btn" @click="scanning = true">
          <span aria-hidden="true">📷</span> {{ t('promoVerify.scanWithCamera') }}
        </button>
      </section>

      <section v-else-if="stage === 'list'" class="stage stage-list">
        <div class="list-head">
          <h1>{{ t('promoRedeem.listTitle') }}</h1>
          <button type="button" class="ghost-btn" @click="reset">{{ t('promoRedeem.nextCustomer') }}</button>
        </div>
        <p class="list-hint">{{ t('promoRedeem.multiHint') }}</p>
        <ul class="voucher-list">
          <li
            v-for="v in vouchers"
            :key="v.redemptionCode"
            class="voucher"
            :class="{ dim: !v.redeemable }"
          >
            <div class="voucher-info">
              <span class="voucher-label">{{ v.label }}</span>
              <span class="voucher-meta">
                {{ v.redemptionCode }}
                <template v-if="v.customerName"> · {{ v.customerName }}</template>
                <template v-if="v.minSpendYen"> · {{ t('promoRedeem.minSpend', { yen: v.minSpendYen.toLocaleString('ja-JP') }) }}</template>
              </span>
              <span v-if="v.status !== 'active'" class="voucher-status">{{ t(`promoRedeem.status_${v.status}`) }}</span>
              <span v-else-if="v.expired" class="voucher-status">{{ t('promoRedeem.status_expired') }}</span>
              <span v-else-if="v.requiresManualApproval" class="voucher-status warn">{{ t('promoRedeem.managerBadge') }}</span>
            </div>
            <button
              type="button"
              class="redeem-btn"
              :disabled="busy || !v.redeemable"
              @click="handleRedeem(v)"
            >
              {{ t('promoRedeem.use') }}
            </button>
          </li>
        </ul>
      </section>

    </main>

    <QrScanner v-if="scanning" @decode="onScanDecode" @close="scanning = false" />
  </div>
</template>

<style scoped>
.kiosk {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text-primary);
}

.kiosk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.head-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.operator {
  font-size: 12px;
  color: var(--text-secondary);
}

.exit-btn {
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
}

.kiosk-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.stage {
  width: 100%;
  max-width: 480px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.stage h1 {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  text-align: center;
}

.stage-list {
  align-items: stretch;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.list-head h1 {
  text-align: left;
}

.mode-toggle {
  display: flex;
  gap: 8px;
}

.mode-toggle button {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 7px 16px;
  font-size: 13px;
  cursor: pointer;
}

.mode-toggle button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.big-input {
  width: 100%;
  height: 60px;
  font-size: 22px;
  text-align: center;
  border: 2px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-primary);
  outline: none;
  box-sizing: border-box;
  text-transform: uppercase;
}

.big-input:focus {
  border-color: var(--accent);
}

.primary-btn {
  width: 100%;
  height: 56px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  cursor: pointer;
}

.primary-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.scan-cam-btn {
  width: 100%;
  height: 52px;
  border: 1px solid var(--accent);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--accent);
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}

.ghost-btn {
  height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
}

.voucher-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.voucher {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.voucher.dim {
  opacity: 0.55;
}

.voucher-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.voucher-label {
  font-size: 15px;
  font-weight: 600;
}

.voucher-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.voucher-status {
  font-size: 11px;
  color: var(--text-tertiary);
}

.voucher-status.warn {
  color: var(--warning);
}

.redeem-btn {
  flex-shrink: 0;
  height: 44px;
  padding: 0 20px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.redeem-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.list-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: -6px 0 0;
}
</style>
