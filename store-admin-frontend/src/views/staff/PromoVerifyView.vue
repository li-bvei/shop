<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import {
  confirmSpend,
  fetchMyVerifications,
  lookupCustomer,
  recordCheckin,
  type CheckinResult,
  type CustomerLookup,
  type SpendVerification,
} from '@/api/promotions'
import KioskBlockedNotice from '@/components/KioskBlockedNotice.vue'
import QrScanner from '@/components/QrScanner.vue'

const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()

// A head-office (本部 / admin) account has no branch, so it can't run the
// counter kiosk — see promotions.views SpendVerificationViewSet._resolve_branch.
const headOfficeBlocked = computed(() => auth.role === 'admin' && !auth.branchId)

type Stage = 'scan' | 'amount' | 'done' | 'checkin-done'
const stage = ref<Stage>('scan')

const scanInput = ref<HTMLInputElement>()
const amountInput = ref<HTMLInputElement>()

const tokenValue = ref('')
const manualMode = ref<'card' | 'phone'>('card')
const amount = ref<number | null>(null)
const tableNumber = ref('')

const customer = ref<CustomerLookup | null>(null)
const lastResult = ref<{ pointsGranted: number; pointsBalance: number; stampCount: number } | null>(null)
const checkinResult = ref<CheckinResult | null>(null)
const busy = ref(false)
const recent = ref<SpendVerification[]>([])

// One id per (customer, amount screen). A retry after a timeout reuses it
// so the backend won't double-grant; a new customer gets a fresh one.
const requestId = ref('')
function newRequestId() {
  return `sv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

let resetTimer: ReturnType<typeof setTimeout> | undefined

const stampTarget = computed(() => customer.value?.stampTarget ?? 0)
const stampFilled = computed(() =>
  stampTarget.value ? (customer.value?.stampCount ?? 0) % stampTarget.value : 0,
)

function focusScan() {
  nextTick(() => scanInput.value?.focus())
}

function focusAmount() {
  nextTick(() => amountInput.value?.focus())
}

function resetToScan() {
  clearTimeout(resetTimer)
  stage.value = 'scan'
  tokenValue.value = ''
  amount.value = null
  tableNumber.value = ''
  customer.value = null
  lastResult.value = null
  checkinResult.value = null
  requestId.value = ''
  focusScan()
}

async function loadRecent() {
  try {
    recent.value = await fetchMyVerifications()
  } catch {
    /* non-critical */
  }
}

// IME guard — a scanner never composes, but a human typing a phone number
// on a soft keyboard might; only submit on a real Enter.
function onScanEnter(event: KeyboardEvent) {
  if (event.isComposing || (event as KeyboardEvent & { keyCode: number }).keyCode === 229) return
  handleLookup()
}

// --- Tablet camera scan -----------------------------------------------------
const scanning = ref(false)

function extractCardToken(payload: string): string {
  // The card QR carries the raw card_token; stay tolerant of a URL form
  // (?card= / ?t= / trailing path segment) in case that ever changes.
  try {
    const url = new URL(payload)
    return (
      url.searchParams.get('card') ||
      url.searchParams.get('t') ||
      url.pathname.split('/').filter(Boolean).pop() ||
      payload
    )
  } catch {
    return payload
  }
}

function onScanDecode(payload: string) {
  scanning.value = false
  manualMode.value = 'card'
  tokenValue.value = extractCardToken(payload)
  handleLookup()
}

async function handleLookup() {
  const raw = tokenValue.value.trim()
  if (!raw || busy.value) return
  busy.value = true
  try {
    const query = manualMode.value === 'phone' ? { phone: raw } : { cardToken: raw }
    customer.value = await lookupCustomer(query)
    requestId.value = newRequestId()
    stage.value = 'amount'
    focusAmount()
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) ElMessage.warning(t('promoVerify.notFound'))
    else if (err instanceof ApiError && err.status === 403) ElMessage.error(t('promoVerify.blocked'))
    else ElMessage.error(t('promoVerify.lookupFailed'))
    tokenValue.value = ''
    focusScan()
  } finally {
    busy.value = false
  }
}

function onAmountEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  handleConfirm()
}

async function handleConfirm() {
  if (busy.value || !customer.value) return
  const value = Number(amount.value)
  if (!Number.isFinite(value) || value < 0) {
    ElMessage.warning(t('promoVerify.amountInvalid'))
    return
  }
  busy.value = true
  try {
    const query = manualMode.value === 'phone' ? { phone: tokenValue.value.trim() } : { cardToken: tokenValue.value.trim() }
    const res = await confirmSpend({
      ...query,
      amountYen: Math.round(value),
      tableNumber: tableNumber.value.trim(),
      requestId: requestId.value,
    })
    lastResult.value = {
      pointsGranted: res.pointsGranted,
      pointsBalance: res.pointsBalance,
      stampCount: res.stampCount,
    }
    stage.value = 'done'
    loadRecent()
    resetTimer = setTimeout(resetToScan, 3500)
  } catch (err) {
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('head-office-account-cannot-scan')) ElMessage.error(t('kioskBlocked.body'))
      else if (body.includes('consumed-at')) ElMessage.error(t('promoVerify.errBusinessDay'))
      else if (body.includes('no-active-campaign')) ElMessage.error(t('promoVerify.errNoCampaign'))
      else if (body.includes('customer-blocked')) ElMessage.error(t('promoVerify.blocked'))
      else if (body.includes('amount-too-large')) ElMessage.error(t('promoVerify.errAmountTooLarge'))
      else ElMessage.error(t('promoVerify.confirmFailed'))
    } else {
      ElMessage.error(t('promoVerify.confirmFailed'))
    }
  } finally {
    busy.value = false
  }
}

// "Check-in only" — the customer showed their QR but isn't paying now
// (e.g. just walked in). Records the visit and issues the daily reward.
async function handleCheckinOnly() {
  if (busy.value || !customer.value) return
  busy.value = true
  try {
    const query = manualMode.value === 'phone' ? { phone: tokenValue.value.trim() } : { cardToken: tokenValue.value.trim() }
    checkinResult.value = await recordCheckin(query)
    stage.value = 'checkin-done'
    resetTimer = setTimeout(resetToScan, 3500)
  } catch (err) {
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('head-office-account-cannot-scan')) ElMessage.error(t('kioskBlocked.body'))
      else if (body.includes('no-active-campaign')) ElMessage.error(t('promoVerify.errNoCampaign'))
      else if (body.includes('customer-blocked')) ElMessage.error(t('promoVerify.blocked'))
      else ElMessage.error(t('promoVerify.confirmFailed'))
    } else {
      ElMessage.error(t('promoVerify.confirmFailed'))
    }
  } finally {
    busy.value = false
  }
}

function exit() {
  router.push({ name: auth.role === 'staff' ? 'my-availability' : 'dashboard' })
}

onMounted(() => {
  focusScan()
  loadRecent()
})

onBeforeUnmount(() => clearTimeout(resetTimer))
</script>

<template>
  <KioskBlockedNotice v-if="headOfficeBlocked" />
  <div v-else class="kiosk">
    <header class="kiosk-head">
      <div class="head-left">
        <span class="brand">{{ t('promoVerify.title') }}</span>
        <router-link :to="{ name: 'promo-redeem' }" class="switch-link">{{ t('promoVerify.toRedeem') }}</router-link>
      </div>
      <div class="head-right">
        <span class="operator">{{ auth.displayName || auth.account }}</span>
        <button type="button" class="exit-btn" @click="exit">{{ t('promoVerify.exit') }}</button>
      </div>
    </header>

    <main class="kiosk-body">
      <!-- Stage: scan -->
      <section v-if="stage === 'scan'" class="stage stage-scan">
        <h1>{{ t('promoVerify.scanPrompt') }}</h1>
        <div class="mode-toggle">
          <button type="button" :class="{ active: manualMode === 'card' }" @click="manualMode = 'card'; focusScan()">
            {{ t('promoVerify.modeCard') }}
          </button>
          <button type="button" :class="{ active: manualMode === 'phone' }" @click="manualMode = 'phone'; focusScan()">
            {{ t('promoVerify.modePhone') }}
          </button>
        </div>
        <input
          ref="scanInput"
          v-model="tokenValue"
          class="big-input"
          :inputmode="manualMode === 'phone' ? 'numeric' : 'text'"
          :placeholder="manualMode === 'phone' ? t('promoVerify.phonePlaceholder') : t('promoVerify.cardPlaceholder')"
          autocomplete="off"
          @keydown.enter="onScanEnter"
          @blur="focusScan"
        />
        <button type="button" class="primary-btn" :disabled="busy || !tokenValue.trim()" @click="handleLookup">
          {{ t('promoVerify.lookup') }}
        </button>
        <button type="button" class="scan-cam-btn" @click="scanning = true">
          <span aria-hidden="true">📷</span> {{ t('promoVerify.scanWithCamera') }}
        </button>
      </section>

      <!-- Stage: amount -->
      <section v-else-if="stage === 'amount' && customer" class="stage stage-amount">
        <div class="customer-card">
          <span class="cust-name">{{ customer.name || t('promoVerify.noName') }}</span>
          <span class="cust-phone">{{ customer.phoneMasked }}</span>
          <div class="cust-stats">
            <div><strong>{{ customer.pointsBalance.toLocaleString('ja-JP') }}</strong><span>{{ t('promoVerify.points') }}</span></div>
            <div v-if="stampTarget">
              <strong>{{ stampFilled }} / {{ stampTarget }}</strong><span>{{ t('promoVerify.stamps') }}</span>
            </div>
          </div>
        </div>

        <label class="amount-label">{{ t('promoVerify.amountLabel') }}</label>
        <div class="amount-input-wrap">
          <span class="yen">¥</span>
          <input
            ref="amountInput"
            v-model.number="amount"
            class="big-input amount"
            type="number"
            inputmode="numeric"
            min="0"
            step="1"
            @keydown.enter="onAmountEnter"
          />
        </div>
        <input v-model="tableNumber" class="table-input" :placeholder="t('promoVerify.tableNumber')" />

        <div class="amount-actions">
          <button type="button" class="ghost-btn" @click="resetToScan">{{ t('promoVerify.cancel') }}</button>
          <button type="button" class="primary-btn" :disabled="busy || amount === null" @click="handleConfirm">
            {{ t('promoVerify.confirm') }}
          </button>
        </div>
        <button type="button" class="scan-cam-btn" :disabled="busy" @click="handleCheckinOnly">
          {{ t('promoVerify.checkinOnly') }}
        </button>
      </section>

      <!-- Stage: done -->
      <section v-else-if="stage === 'done' && lastResult" class="stage stage-done" @click="resetToScan">
        <div class="check-mark">✓</div>
        <h1>{{ t('promoVerify.doneTitle') }}</h1>
        <p class="done-detail">
          <template v-if="lastResult.pointsGranted > 0">
            {{ t('promoVerify.donePoints', { pts: lastResult.pointsGranted }) }}
          </template>
          <template v-else>{{ t('promoVerify.doneNoPoints') }}</template>
        </p>
        <p class="done-balance">{{ t('promoVerify.doneBalance', { bal: lastResult.pointsBalance.toLocaleString('ja-JP') }) }}</p>
        <button type="button" class="primary-btn" @click="resetToScan">{{ t('promoVerify.next') }}</button>
      </section>

      <!-- Stage: check-in only done -->
      <section v-else-if="stage === 'checkin-done' && checkinResult" class="stage stage-done" @click="resetToScan">
        <div class="check-mark">✓</div>
        <h1>{{ t('promoVerify.checkinDoneTitle') }}</h1>
        <p v-if="checkinResult.alreadyCheckedIn" class="done-detail">{{ t('promoVerify.checkinAlready') }}</p>
        <p v-else-if="checkinResult.rewardVoucher" class="done-detail">
          {{ t('promoVerify.checkinVoucher', { label: checkinResult.rewardVoucher.label }) }}
        </p>
        <p v-else class="done-detail">{{ t('promoVerify.checkinNoReward') }}</p>
        <button type="button" class="primary-btn" @click="resetToScan">{{ t('promoVerify.next') }}</button>
      </section>
    </main>

    <footer v-if="recent.length" class="kiosk-foot">
      <span class="foot-label">{{ t('promoVerify.recentLabel') }}</span>
      <ul>
        <li v-for="r in recent.slice(0, 6)" :key="r.id" :class="{ voided: r.status === 'voided' }">
          <span>{{ r.customerName || r.customerPhone || '—' }}</span>
          <span>¥{{ r.amountYen.toLocaleString('ja-JP') }}</span>
          <span>+{{ r.pointsGranted }}</span>
        </li>
      </ul>
    </footer>

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
  max-width: 460px;
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
  font-size: 24px;
  text-align: center;
  border: 2px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-primary);
  outline: none;
  box-sizing: border-box;
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
  height: 56px;
  padding: 0 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 16px;
  cursor: pointer;
}

.customer-card {
  width: 100%;
  background: var(--surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-soft);
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.cust-name {
  font-size: 20px;
  font-weight: 700;
}

.cust-phone {
  font-size: 13px;
  color: var(--text-tertiary);
}

.cust-stats {
  display: flex;
  gap: 28px;
  margin-top: 10px;
}

.cust-stats div {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.cust-stats strong {
  font-size: 22px;
}

.cust-stats span {
  font-size: 11px;
  color: var(--text-secondary);
}

.amount-label {
  font-size: 14px;
  color: var(--text-secondary);
  align-self: flex-start;
}

.amount-input-wrap {
  position: relative;
  width: 100%;
}

.amount-input-wrap .yen {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 22px;
  color: var(--text-tertiary);
}

.big-input.amount {
  padding-left: 44px;
  text-align: right;
  padding-right: 16px;
}

.table-input {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  font-size: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-primary);
  outline: none;
  box-sizing: border-box;
}

.amount-actions {
  display: flex;
  gap: 12px;
  width: 100%;
}

.amount-actions .primary-btn {
  flex: 1;
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

.done-detail {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.done-balance {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.kiosk-foot {
  border-top: 1px solid var(--border);
  background: var(--surface);
  padding: 10px 20px 14px;
}

.foot-label {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.kiosk-foot ul {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kiosk-foot li {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 16px;
  font-size: 12.5px;
  color: var(--text-secondary);
  padding: 3px 0;
}

.kiosk-foot li.voided {
  text-decoration: line-through;
  color: var(--text-tertiary);
}
</style>
