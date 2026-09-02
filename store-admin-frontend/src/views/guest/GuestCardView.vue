<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api/http'
import {
  SELF_SERVE_REWARD_TYPES,
  fetchCard,
  fetchPrizes,
  guestLogin,
  pulseCard,
  redeem,
  selfServeRedeem,
  setPin,
  useDrawChance,
  type DrawResult,
  type GuestCard,
  type GuestVoucher,
  type WheelPrize,
} from '@/api/guest'
import QrCanvas from '@/components/QrCanvas.vue'
import GuestOnboarding from '@/components/GuestOnboarding.vue'
import AnimatedNumber from '@/components/AnimatedNumber.vue'
import WheelOfFortune from '@/components/WheelOfFortune.vue'
import SlideToConfirm from '@/components/SlideToConfirm.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const ONBOARDED_KEY = 'pc_onboarded'
function hasOnboarded() {
  try {
    return localStorage.getItem(ONBOARDED_KEY) === '1'
  } catch {
    return false
  }
}
const showOnboarding = ref(false)
function openOnboarding() {
  showOnboarding.value = true
}
function closeOnboarding() {
  showOnboarding.value = false
  try {
    localStorage.setItem(ONBOARDED_KEY, '1')
  } catch {
    /* ignore */
  }
  if (route.query.welcome) router.replace({ name: 'guest-card' })
}

function shortDateTime(iso: string) {
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return new Intl.DateTimeFormat('ja-JP', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo',
  }).format(dt)
}

function shortDate(iso: string) {
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'Asia/Tokyo',
  }).format(dt)
}

const card = ref<GuestCard | null>(null)
const loading = ref(true)
const loadError = ref(false)
const readonly = ref(route.query.readonly === '1')

const busy = ref(false)
const drawResult = ref<DrawResult | null>(null)
const voucherModal = ref<GuestVoucher | null>(null)

// Lottery wheel
const wheelModal = ref(false)
const wheelSource = ref<'points' | 'chance'>('points')
const wheelPrizes = ref<WheelPrize[]>([])
const wheelRef = ref<InstanceType<typeof WheelOfFortune>>()

// One-time "set a recovery PIN" prompt, shown on a full card that has none.
const pinPromptDismissed = ref(false)
const pinValue = ref('')
const pinSaving = ref(false)
const pinError = ref('')
const showPinPrompt = computed(
  () => !readonly.value && card.value != null && !card.value.hasPin && !pinPromptDismissed.value,
)

async function savePin() {
  if (!/^\d{6}$/.test(pinValue.value) || pinSaving.value) return
  pinSaving.value = true
  pinError.value = ''
  try {
    await setPin(pinValue.value)
    pinValue.value = ''
    pinPromptDismissed.value = true
    await load()
  } catch (err) {
    pinError.value =
      err instanceof ApiError && JSON.stringify(err.body).includes('pin-too-common')
        ? t('guest.errPinCommon')
        : t('guest.errPinFormat')
  } finally {
    pinSaving.value = false
  }
}

const stampFilled = computed(() => {
  const target = card.value?.stampTarget ?? 0
  if (!target) return 0
  return (card.value?.stampCount ?? 0) % target
})
const stampCells = computed(() => {
  const target = card.value?.stampTarget ?? 0
  return Array.from({ length: target }, (_, i) => i < stampFilled.value)
})

const c = computed(() => card.value?.campaign ?? {})
const canDrawWithPoints = computed(
  () => !!c.value.hasPrizes && !!c.value.pointsPerDraw && (card.value?.pointsBalance ?? 0) >= c.value.pointsPerDraw,
)
const canRedeemVoucher = computed(
  () => !!c.value.pointsPerVoucher && (card.value?.pointsBalance ?? 0) >= c.value.pointsPerVoucher,
)
const activeVouchers = computed(() => card.value?.vouchers.filter((v) => v.status === 'active') ?? [])

const reasonLabel = (reason: string) => t(`guest.reason.${reason}`, reason)

function newRequestId() {
  return `pc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    if (readonly.value) {
      const state = history.state as { phone?: string; birthdayMd?: string }
      if (!state?.phone || !state?.birthdayMd) {
        router.replace({ name: 'guest-login' })
        return
      }
      card.value = await guestLogin(state.phone, state.birthdayMd)
    } else {
      card.value = await fetchCard()
    }
    if (!readonly.value && card.value && route.query.welcome === '1' && !hasOnboarded()) {
      showOnboarding.value = true
    }
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function openWheel(source: 'points' | 'chance') {
  if (busy.value || readonly.value) return
  wheelSource.value = source
  drawResult.value = null
  wheelModal.value = true
  if (wheelPrizes.value.length === 0) {
    try {
      wheelPrizes.value = await fetchPrizes()
    } catch {
      /* the wheel still spins to a random segment; the real result is authoritative */
    }
  }
}

async function onWheelSpin() {
  if (busy.value) return
  busy.value = true
  try {
    const res =
      wheelSource.value === 'points'
        ? await redeem('draw', newRequestId())
        : await useDrawChance(newRequestId())
    const idx = wheelPrizes.value.findIndex((p) => p.name === res.result?.prizeName)
    await wheelRef.value?.spin(idx >= 0 ? idx : Math.floor(Math.random() * (wheelPrizes.value.length || 1)))
    await new Promise((r) => setTimeout(r, 650)) // let it land before the reveal
    drawResult.value = res.result ?? null
    await load()
  } catch (err) {
    wheelModal.value = false
    handleError(err)
  } finally {
    busy.value = false
  }
}

function closeWheel() {
  wheelModal.value = false
  drawResult.value = null
}

// --- self-serve redeem (drink / dessert / side dish, on the guest's phone) ---
const s2cRef = ref<InstanceType<typeof SlideToConfirm>>()
const selfServeBusy = ref(false)
const selfServeError = ref('')

function canSelfServe(v: GuestVoucher) {
  return v.status === 'active' && SELF_SERVE_REWARD_TYPES.includes(v.rewardType)
}

async function onSelfServe() {
  const v = voucherModal.value
  if (!v || selfServeBusy.value) return
  selfServeBusy.value = true
  selfServeError.value = ''
  try {
    await selfServeRedeem(v.redemptionCode)
    voucherModal.value = null
    bonusMsg.value = t('guest.selfServeDone')
    confettiKey.value += 1
    window.setTimeout(() => (bonusMsg.value = ''), 3000)
    await load()
  } catch (err) {
    selfServeError.value =
      err instanceof ApiError && JSON.stringify(err.body).includes('already-redeemed')
        ? t('guest.selfServeAlready')
        : t('guest.errGeneric')
    s2cRef.value?.reset()
  } finally {
    selfServeBusy.value = false
  }
}

async function redeemVoucher() {
  if (busy.value || readonly.value) return
  busy.value = true
  try {
    const res = await redeem('voucher', newRequestId())
    await load()
    if (res.voucher) voucherModal.value = res.voucher
  } catch (err) {
    handleError(err)
  } finally {
    busy.value = false
  }
}

function handleError(err: unknown) {
  if (!(err instanceof ApiError)) {
    window.alert(t('guest.errGeneric'))
    return
  }
  const body = JSON.stringify(err.body)
  if (body.includes('insufficient-points')) window.alert(t('guest.errInsufficientPoints'))
  else if (body.includes('daily-draw-limit')) window.alert(t('guest.errDrawLimit'))
  else if (body.includes('no-prizes')) window.alert(t('guest.errNoPrizes'))
  else window.alert(t('guest.errGeneric'))
}

// --- live updates: poll a tiny endpoint, animate when the counter acts ---
const pointsGain = ref(0)
const showGain = ref(false)
const bonusMsg = ref('')
const justFilledStamp = ref(-1)
const confettiKey = ref(0)
let pollTimer: ReturnType<typeof setInterval> | undefined

function startPolling() {
  stopPolling()
  if (readonly.value) return
  pollTimer = setInterval(pollTick, 3000)
}
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = undefined
}

async function pollTick() {
  if (document.visibilityState !== 'visible' || busy.value || !card.value || showOnboarding.value) return
  let p
  try {
    p = await pulseCard()
  } catch {
    return
  }
  if (!card.value) return
  const pointsUp = p.pointsBalance - card.value.pointsBalance
  const stampUp = p.stampCount - card.value.stampCount
  const drawUp = p.drawChances - card.value.drawChances
  const voucherUp = p.voucherCount - activeVouchers.value.length
  if (pointsUp <= 0 && stampUp <= 0 && drawUp <= 0 && voucherUp <= 0) return

  const stampBefore = stampFilled.value
  await load()
  confettiKey.value += 1 // one fresh key per celebration so animations replay cleanly

  if (pointsUp > 0) {
    pointsGain.value = pointsUp
    showGain.value = true
    window.setTimeout(() => (showGain.value = false), 2400)
  }
  if (stampUp > 0 && card.value?.stampTarget) {
    justFilledStamp.value = stampBefore % card.value.stampTarget
    window.setTimeout(() => (justFilledStamp.value = -1), 800)
  }
  if (drawUp > 0 || voucherUp > 0) {
    bonusMsg.value =
      drawUp > 0 ? t('guest.liveDrawChance', { n: drawUp }) : t('guest.liveNewVoucher')
    window.setTimeout(() => (bonusMsg.value = ''), 3400)
  }
}

function onVisibility() {
  if (document.visibilityState === 'visible') pollTick()
}

onMounted(async () => {
  await load()
  startPolling()
  document.addEventListener('visibilitychange', onVisibility)
})
onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div class="wrap">
    <div v-if="loading" class="card skeleton">{{ t('guest.loading') }}</div>

    <div v-else-if="loadError" class="card">
      <h1>{{ t('guest.notFoundTitle') }}</h1>
      <p class="lead">{{ t('guest.notFoundBody') }}</p>
      <router-link :to="{ name: 'guest-login' }" class="btn-primary">{{ t('guest.goLogin') }}</router-link>
    </div>

    <template v-else-if="card">
      <div class="card qr-card">
        <div class="greeting">
          <span class="hello">{{ card.name ? t('guest.helloName', { name: card.name }) : t('guest.hello') }}</span>
          <span v-if="readonly" class="readonly-badge">{{ t('guest.readonlyBadge') }}</span>
        </div>

        <div v-if="!readonly" class="qr-box">
          <QrCanvas :value="card.cardToken" :size="200" />
          <span class="short-code">{{ card.cardToken }}</span>
          <p class="qr-hint">{{ t('guest.qrHint') }}</p>
        </div>

        <div class="points" :class="{ bump: showGain }">
          <span class="points-value"><AnimatedNumber :value="card.pointsBalance" /></span>
          <span class="points-unit">{{ t('guest.points') }}</span>
          <span v-if="showGain" :key="`g${confettiKey}`" class="points-gain">+{{ pointsGain }}</span>
          <div v-if="showGain" :key="`c${confettiKey}`" class="confetti" aria-hidden="true">
            <span v-for="n in 16" :key="n" :style="{ '--i': n }" />
          </div>
        </div>

        <div v-if="card.stampTarget" class="stamps">
          <span class="stamps-label">{{ t('guest.stampProgress', { count: stampFilled, target: card.stampTarget }) }}</span>
          <div class="stamp-row">
            <span
              v-for="(filled, i) in stampCells"
              :key="i"
              class="stamp"
              :class="{ filled, pop: i === justFilledStamp }"
            />
          </div>
        </div>
      </div>

      <div v-if="bonusMsg" :key="`t${confettiKey}`" class="live-toast">{{ bonusMsg }}</div>

      <!-- Set a recovery PIN -->
      <div v-if="showPinPrompt" class="card pin-card">
        <h2>{{ t('guest.setPinTitle') }}</h2>
        <p class="pin-body">{{ t('guest.setPinBody') }}</p>
        <input
          v-model="pinValue"
          class="pin-input"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          maxlength="6"
          :placeholder="t('guest.pinPlaceholder')"
          @input="pinValue = pinValue.replace(/\D/g, '').slice(0, 6)"
        />
        <p v-if="pinError" class="pin-error">{{ pinError }}</p>
        <div class="pin-actions">
          <button type="button" class="pin-skip" @click="pinPromptDismissed = true">
            {{ t('guest.later') }}
          </button>
          <button
            type="button"
            class="pin-save"
            :disabled="pinSaving || !/^\d{6}$/.test(pinValue)"
            @click="savePin"
          >
            {{ pinSaving ? t('guest.submitting') : t('guest.setPinCta') }}
          </button>
        </div>
      </div>

      <!-- Spend points -->
      <div v-if="!readonly && (canDrawWithPoints || canRedeemVoucher || card.drawChances > 0)" class="card spend-card">
        <h2>{{ t('guest.spendTitle') }}</h2>

        <button
          v-if="card.drawChances > 0"
          type="button"
          class="spend-btn accent"
          :disabled="busy"
          @click="openWheel('chance')"
        >
          <span class="spend-btn-main">{{ t('guest.drawFree') }}</span>
          <span class="spend-btn-sub">{{ t('guest.drawChancesLeft', { n: card.drawChances }) }}</span>
        </button>

        <button
          v-if="canDrawWithPoints"
          type="button"
          class="spend-btn"
          :disabled="busy"
          @click="openWheel('points')"
        >
          <span class="spend-btn-main">{{ t('guest.drawWithPoints') }}</span>
          <span class="spend-btn-sub">{{ c.pointsPerDraw }} {{ t('guest.points') }}</span>
        </button>

        <button
          v-if="canRedeemVoucher"
          type="button"
          class="spend-btn"
          :disabled="busy"
          @click="redeemVoucher"
        >
          <span class="spend-btn-main">{{ t('guest.redeemVoucher', { yen: c.voucherYenPerUnit }) }}</span>
          <span class="spend-btn-sub">{{ c.pointsPerVoucher }} {{ t('guest.points') }}</span>
        </button>
      </div>

      <!-- Vouchers -->
      <div v-if="activeVouchers.length" class="card voucher-card">
        <h2>{{ t('guest.vouchersTitle') }}</h2>
        <ul class="vouchers">
          <li v-for="v in activeVouchers" :key="v.redemptionCode" @click="voucherModal = v">
            <div class="voucher-main">
              <span class="voucher-label">{{ v.label }}</span>
              <span class="voucher-meta">
                {{ t('guest.voucherExpires', { date: shortDate(v.expiresAt) }) }}
                <template v-if="v.minSpendYen"> · {{ t('guest.voucherMinSpend', { yen: v.minSpendYen.toLocaleString('ja-JP') }) }}</template>
              </span>
            </div>
            <span class="voucher-code">{{ v.redemptionCode }}</span>
          </li>
        </ul>
        <p class="voucher-hint">{{ t('guest.voucherHint') }}</p>
      </div>

      <!-- Milestones -->
      <div v-if="card.milestones.length" class="card milestone-card">
        <h2>{{ t('guest.milestonesTitle') }}</h2>
        <ul class="milestones">
          <li v-for="m in card.milestones" :key="m.threshold" :class="{ reached: m.reached }">
            <span class="ms-dot" />
            <span class="ms-label">{{ m.label }}</span>
            <span class="ms-threshold">{{ m.threshold }} {{ t('guest.points') }}</span>
          </li>
        </ul>
        <p class="ms-progress">{{ t('guest.lifetimePoints', { n: card.lifetimePoints.toLocaleString('ja-JP') }) }}</p>
      </div>

      <div v-if="c.pointsPer1000yen" class="card info-card">
        <h2>{{ c.name || t('guest.campaignFallback') }}</h2>
        <ul>
          <li>{{ t('guest.rateEarn', { yen: 1000, pts: c.pointsPer1000yen }) }}</li>
          <li v-if="c.pointsPerVoucher && c.voucherYenPerUnit">
            {{ t('guest.rateVoucher', { pts: c.pointsPerVoucher, yen: c.voucherYenPerUnit }) }}
          </li>
          <li v-if="c.pointsPerDraw && c.hasPrizes">{{ t('guest.rateDraw', { pts: c.pointsPerDraw }) }}</li>
        </ul>
      </div>

      <div class="card ledger-card">
        <h2>{{ t('guest.history') }}</h2>
        <ul v-if="card.ledger.length" class="ledger">
          <li v-for="row in card.ledger" :key="row.id">
            <div class="ledger-main">
              <span class="ledger-reason">{{ reasonLabel(row.reason) }}</span>
              <span class="ledger-date">{{ shortDateTime(row.createdAt) }}</span>
            </div>
            <span v-if="row.delta" class="ledger-delta" :class="{ minus: row.delta < 0 }">
              {{ row.delta > 0 ? '+' : '' }}{{ row.delta }}
            </span>
          </li>
        </ul>
        <p v-else class="empty">{{ t('guest.historyEmpty') }}</p>
      </div>

      <p class="footnote">
        {{ t('guest.saveHint') }}
        <template v-if="!readonly"> · <button type="button" class="link-btn" @click="openOnboarding">{{ t('guest.howToUse') }}</button></template>
      </p>
    </template>

    <GuestOnboarding v-if="showOnboarding && card" :card="card" @close="closeOnboarding" />

    <!-- Lottery wheel -->
    <div v-if="wheelModal" class="modal-overlay wheel-overlay">
      <div class="wheel-sheet">
        <button v-if="!busy && !drawResult" type="button" class="wheel-x" @click="closeWheel">✕</button>

        <template v-if="!drawResult">
          <p class="wheel-heading">
            {{ wheelSource === 'points' ? t('guest.drawWithPoints') : t('guest.drawFree') }}
          </p>
          <WheelOfFortune ref="wheelRef" :prizes="wheelPrizes" :busy="busy" @spin="onWheelSpin" />
          <p class="wheel-cost">
            {{ wheelSource === 'points'
              ? t('guest.wheelCostPoints', { n: c.pointsPerDraw })
              : t('guest.drawChancesLeft', { n: card?.drawChances ?? 0 }) }}
          </p>
        </template>

        <template v-else>
          <div class="modal-emoji">{{ drawResult.status === 'won' ? '🎉' : '🍀' }}</div>
          <p class="modal-title">
            {{ drawResult.status === 'won' ? t('guest.drawWon') : t('guest.drawRefund', { n: drawResult.pointsRefunded }) }}
          </p>
          <p v-if="drawResult.status === 'won'" class="modal-prize">{{ drawResult.prizeName }}</p>
          <div v-if="drawResult.voucher" class="modal-voucher">
            <span class="voucher-code big">{{ drawResult.voucher.redemptionCode }}</span>
            <span class="modal-voucher-note">{{ t('guest.voucherAddedNote') }}</span>
          </div>
          <button type="button" class="btn-primary inline" @click="closeWheel">{{ t('guest.close') }}</button>
        </template>
      </div>
    </div>

    <!-- Voucher detail modal -->
    <div v-if="voucherModal" class="modal-overlay" @click.self="voucherModal = null">
      <div class="modal">
        <p class="modal-title">{{ voucherModal.label }}</p>
        <QrCanvas :value="voucherModal.redemptionCode" :size="180" />
        <span class="voucher-code big">{{ voucherModal.redemptionCode }}</span>
        <p class="modal-voucher-note">
          {{ t('guest.voucherExpires', { date: shortDate(voucherModal.expiresAt) }) }}
          <template v-if="voucherModal.minSpendYen">
            <br />{{ t('guest.voucherMinSpend', { yen: voucherModal.minSpendYen.toLocaleString('ja-JP') }) }}
          </template>
          <template v-if="voucherModal.requiresManualApproval">
            <br />{{ t('guest.voucherNeedsApproval') }}
          </template>
        </p>

        <template v-if="!readonly && canSelfServe(voucherModal)">
          <p class="s2c-hint">{{ t('guest.selfServeHint') }}</p>
          <SlideToConfirm
            ref="s2cRef"
            class="s2c-wrap"
            :label="t('guest.selfServeSlide')"
            :disabled="selfServeBusy"
            @confirm="onSelfServe"
          />
          <p v-if="selfServeError" class="s2c-error">{{ selfServeError }}</p>
        </template>

        <button type="button" class="btn-primary inline" @click="voucherModal = null">{{ t('guest.close') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 20px;
}

.card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 22px 20px;
}

.skeleton {
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 40px 20px;
}

h1 {
  font-size: 19px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.lead {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 16px;
}

.qr-card {
  text-align: center;
}

.greeting {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 14px;
}

.hello {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.readonly-badge {
  font-size: 10.5px;
  color: var(--warning);
  background: var(--warning-light);
  border-radius: 20px;
  padding: 2px 8px;
}

.qr-box {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px;
  background: #fff;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.short-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.qr-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 2px 0 0;
}

.points {
  position: relative;
  margin-top: 18px;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  transition: transform 0.25s ease;
}

.points.bump {
  transform: scale(1.08);
}

.points-value {
  font-size: 40px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.points-unit {
  font-size: 14px;
  color: var(--text-secondary);
}

.points-gain {
  position: absolute;
  top: -6px;
  left: 50%;
  font-size: 15px;
  font-weight: 700;
  color: var(--success);
  pointer-events: none;
  white-space: nowrap;
  animation: gain-float 2.2s cubic-bezier(0.2, 0.7, 0.3, 1) forwards;
}

@keyframes gain-float {
  0% {
    opacity: 0;
    transform: translate(-50%, 14px);
  }
  15% {
    opacity: 1;
    transform: translate(-50%, -20px);
  }
  75% {
    opacity: 1;
    transform: translate(-50%, -30px);
  }
  100% {
    opacity: 0;
    transform: translate(-50%, -40px);
  }
}

.confetti {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: visible;
}

.confetti span {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 6px;
  height: 9px;
  border-radius: 1px;
  background: hsl(calc(var(--i) * 42deg), 82%, 62%);
  animation: confetti-fly 0.9s ease-out forwards;
}

@keyframes confetti-fly {
  0% {
    opacity: 1;
    transform: rotate(calc(var(--i) * 22.5deg)) translateY(0) scale(1);
  }
  100% {
    opacity: 0;
    transform: rotate(calc(var(--i) * 22.5deg)) translateY(-66px) rotate(220deg) scale(0.35);
  }
}

.live-toast {
  position: sticky;
  top: 8px;
  z-index: 20;
  align-self: center;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: 999px;
  box-shadow: var(--shadow-card);
  animation: toast-in 3.4s ease forwards;
}

@keyframes toast-in {
  0% {
    opacity: 0;
    transform: translateY(-8px);
  }
  8%,
  90% {
    opacity: 1;
    transform: translateY(0);
  }
  100% {
    opacity: 0;
    transform: translateY(-8px);
  }
}

.stamps {
  margin-top: 16px;
}

.stamps-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.stamp-row {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.stamp {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid var(--border);
}

.stamp.filled {
  background: var(--accent);
  border-color: var(--accent);
}

.stamp.pop {
  animation: stamp-pop 0.6s ease;
}

@keyframes stamp-pop {
  0% {
    transform: scale(0.4);
  }
  55% {
    transform: scale(1.35);
  }
  100% {
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .points.bump,
  .stamp.pop,
  .confetti,
  .points-gain,
  .live-toast {
    animation: none;
    transition: none;
  }
  .points.bump {
    transform: none;
  }
}

/* Set-PIN prompt */
.pin-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pin-body {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

.pin-input {
  width: 100%;
  height: 46px;
  padding: 0 14px;
  font-size: 20px;
  letter-spacing: 0.3em;
  text-align: center;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-alt);
  color: var(--text-primary);
  outline: none;
  box-sizing: border-box;
}

.pin-input:focus {
  border-color: var(--accent);
}

.pin-error {
  font-size: 11.5px;
  color: var(--danger);
  margin: 0;
}

.pin-actions {
  display: flex;
  gap: 10px;
}

.pin-skip {
  flex: 0 0 auto;
  padding: 0 16px;
  height: 42px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}

.pin-save {
  flex: 1;
  height: 42px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.pin-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Spend points */
.spend-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.spend-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-alt);
  cursor: pointer;
  text-align: left;
}

.spend-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spend-btn.accent {
  background: var(--accent-light);
  border-color: var(--accent);
}

.spend-btn-main {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.spend-btn-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

/* Vouchers */
.vouchers {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vouchers li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border: 1px dashed var(--accent);
  border-radius: var(--radius-md);
  background: var(--accent-light);
  cursor: pointer;
}

.voucher-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.voucher-label {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.voucher-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.voucher-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
  white-space: nowrap;
}

.voucher-code.big {
  font-size: 22px;
  color: var(--text-primary);
  margin: 8px 0;
}

.voucher-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 10px 0 0;
}

/* Milestones */
.milestones {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.milestones li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.milestones li.reached {
  color: var(--text-primary);
}

.ms-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--border);
  flex-shrink: 0;
}

.milestones li.reached .ms-dot {
  background: var(--success);
  border-color: var(--success);
}

.ms-label {
  flex: 1;
}

.ms-threshold {
  font-size: 11px;
}

.ms-progress {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 12px 0 0;
}

.info-card ul {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-card li {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.ledger {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.ledger li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.ledger li:last-child {
  border-bottom: none;
}

.ledger-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ledger-reason {
  font-size: 13px;
  color: var(--text-primary);
}

.ledger-date {
  font-size: 11px;
  color: var(--text-tertiary);
}

.ledger-delta {
  font-size: 15px;
  font-weight: 600;
  color: var(--success);
}

.ledger-delta.minus {
  color: var(--danger);
}

.empty {
  font-size: 12.5px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 12px 0;
  margin: 0;
}

.btn-primary {
  display: block;
  text-align: center;
  text-decoration: none;
  height: 46px;
  line-height: 46px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  width: 100%;
}

.btn-primary.inline {
  margin-top: 16px;
}

.footnote {
  text-align: center;
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 4px 0 0;
}

.link-btn {
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: 11.5px;
  padding: 0;
  cursor: pointer;
}

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 100;
}

.modal {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 28px 24px;
  max-width: 320px;
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.modal-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 12px 0 0;
}

.modal-prize {
  font-size: 15px;
  color: var(--accent);
  font-weight: 600;
  margin: 6px 0 0;
}

.modal-emoji {
  font-size: 52px;
  line-height: 1;
}

.modal-voucher {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 8px;
}

.modal-voucher-note {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* Lottery wheel sheet */
.wheel-overlay {
  padding: 16px;
}

.wheel-sheet {
  position: relative;
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 26px 20px 22px;
  max-width: 360px;
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.wheel-x {
  position: absolute;
  top: 10px;
  right: 12px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: 16px;
  cursor: pointer;
}

.wheel-heading {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 18px;
}

.wheel-cost {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 18px 0 0;
}

.s2c-hint {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 16px 0 8px;
  text-align: center;
}

.s2c-wrap {
  width: 100%;
}

.s2c-error {
  font-size: 11.5px;
  color: var(--danger);
  margin: 8px 0 0;
}
</style>
