<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import { redeemVoucher, verifyVouchers, type VoucherRow } from '@/api/promotions'

const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

type Stage = 'scan' | 'list' | 'done'
const stage = ref<Stage>('scan')
const scanInput = ref<HTMLInputElement>()

const query = ref('')
const mode = ref<'code' | 'card' | 'phone'>('code')
const vouchers = ref<VoucherRow[]>([])
const redeemed = ref<VoucherRow | null>(null)
const busy = ref(false)

let resetTimer: ReturnType<typeof setTimeout> | undefined

const isManager = computed(() => auth.role === 'branch' || auth.role === 'admin')

function focusScan() {
  nextTick(() => scanInput.value?.focus())
}

function reset() {
  clearTimeout(resetTimer)
  stage.value = 'scan'
  query.value = ''
  vouchers.value = []
  redeemed.value = null
  focusScan()
}

function onScanEnter(event: KeyboardEvent) {
  if (event.isComposing || (event as KeyboardEvent & { keyCode: number }).keyCode === 229) return
  lookup()
}

async function lookup() {
  const raw = query.value.trim()
  if (!raw || busy.value) return
  busy.value = true
  try {
    const q =
      mode.value === 'code'
        ? { redemptionCode: raw }
        : mode.value === 'phone'
          ? { phone: raw }
          : { cardToken: raw }
    vouchers.value = await verifyVouchers(q)
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
    redeemed.value = await redeemVoucher({ redemptionCode: v.redemptionCode, spendAmountYen })
    stage.value = 'done'
    resetTimer = setTimeout(reset, 4000)
  } catch (err) {
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('already-redeemed')) ElMessage.error(t('promoRedeem.alreadyRedeemed'))
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

onMounted(focusScan)
</script>

<template>
  <div class="kiosk">
    <header class="kiosk-head">
      <div class="head-left">
        <span class="brand">{{ t('promoRedeem.title') }}</span>
        <router-link :to="{ name: 'promo-verify' }" class="switch-link">{{ t('promoRedeem.toCheckin') }}</router-link>
      </div>
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
        </div>
        <input
          ref="scanInput"
          v-model="query"
          class="big-input"
          :placeholder="t(`promoRedeem.placeholder_${mode}`)"
          autocomplete="off"
          @keydown.enter="onScanEnter"
          @blur="focusScan"
        />
        <button type="button" class="primary-btn" :disabled="busy || !query.trim()" @click="lookup">
          {{ t('promoRedeem.lookup') }}
        </button>
      </section>

      <section v-else-if="stage === 'list'" class="stage stage-list">
        <div class="list-head">
          <h1>{{ t('promoRedeem.listTitle') }}</h1>
          <button type="button" class="ghost-btn" @click="reset">{{ t('promoVerify.cancel') }}</button>
        </div>
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

      <section v-else-if="stage === 'done' && redeemed" class="stage stage-done" @click="reset">
        <div class="check-mark">✓</div>
        <h1>{{ t('promoRedeem.doneTitle') }}</h1>
        <p class="done-label">{{ redeemed.label }}</p>
        <p v-if="redeemed.redeemedSpendYen" class="done-sub">
          {{ t('promoRedeem.doneSpend', { yen: redeemed.redeemedSpendYen.toLocaleString('ja-JP') }) }}
        </p>
        <p class="done-hint">{{ t('promoRedeem.applyHint') }}</p>
        <button type="button" class="primary-btn" @click="reset">{{ t('promoVerify.next') }}</button>
      </section>
    </main>
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
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.head-left {
  display: flex;
  align-items: baseline;
  gap: 14px;
}

.brand {
  font-size: 15px;
  font-weight: 700;
}

.switch-link {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
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

.stage-done {
  cursor: pointer;
}

.check-mark {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  background: var(--success);
  color: #fff;
  font-size: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.done-label {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
}

.done-sub {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.done-hint {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
  text-align: center;
}
</style>
