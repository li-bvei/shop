<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, EditPen, Plus } from '@element-plus/icons-vue'
import {
  CASH_REGISTER_DENOMINATIONS,
  CASH_REGISTER_DEFAULTS_CUTOFF_DATE,
  CASH_REGISTER_EXPECTED_TOTAL,
  CASH_REGISTER_FLOAT_DENOMINATIONS,
  cashRegisterDenominationBreakdown,
  computeCashRegisterStatus,
  computeDerived,
  syncPaymentAmountKeysOn,
  visiblePaymentMethodsFor,
  type DailyReportFormData,
} from '@/components/DailyReportForm.vue'
import MobileNumberInput from '@/components/mobile/MobileNumberInput.vue'
import MobileStepper from '@/components/mobile/MobileStepper.vue'
import {
  addPaymentMethod, deletePaymentMethod, fetchExpenseSuggestions, fetchPaymentMethods, renamePaymentMethod,
  type ExpenseSuggestion, type PaymentMethodDef,
} from '@/api/masterData'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import { fetchCashRegisterDefaults, updateCashRegisterDefaults, type CashRegisterDefaults } from '@/api/cashRegisterDefaults'
import { formatCurrency, formatNumber } from '@/utils/format'

/**
 * The phone version of DailyReportForm: same `DailyReportFormData` object,
 * same computeDerived / cashRegisterDenominationBreakdown / status helpers
 * (imported, never re-derived here), so the same numbers typed on a phone
 * and on the desktop form always produce the same report. Only the
 * presentation differs — one short step at a time, 56px fields, and a
 * fixed 前へ / 次へ / 保存 bar.
 */
const props = defineProps<{
  branchId: string
  reportDate: string
  readonly?: boolean
  saving?: boolean
  allowCashRegisterDefaultEdits?: boolean
}>()
const emit = defineEmits<{ save: []; history: [] }>()
const data = defineModel<DailyReportFormData>('data', { required: true })

const { t } = useI18n()

const STEPS = ['mStepBasic', 'mStepPayment', 'mStepCash', 'mStepExpense', 'mStepConfirm'] as const
const step = ref(0)
function goTo(index: number) {
  step.value = Math.min(Math.max(index, 0), STEPS.length - 1)
  window.scrollTo({ top: 0 })
}

// ---- reference data (same sources as the desktop form) -----------------
const staffList = ref<StaffMember[]>([])
const paymentMethods = ref<PaymentMethodDef[]>([])
const topSuggestions = ref<ExpenseSuggestion[]>([])
const cashDefaults = ref<CashRegisterDefaults>({ denominationDefaults: {}, expectedTotal: CASH_REGISTER_EXPECTED_TOTAL })

const hallStaff = computed(() => staffList.value.filter((s) => s.workArea === 'hall'))
const visibleMethods = computed(() => visiblePaymentMethodsFor(paymentMethods.value, data.value.paymentAmounts))
const derived = computed(() => computeDerived(data.value, paymentMethods.value))
const cashStatus = computed(() => computeCashRegisterStatus(
  data.value.cashRegisterCounts, cashDefaults.value.denominationDefaults, cashDefaults.value.expectedTotal, props.reportDate,
))
const showDefaultsSettings = computed(
  () => !!props.allowCashRegisterDefaultEdits && props.reportDate >= CASH_REGISTER_DEFAULTS_CUTOFF_DATE,
)

function methodLabel(method: PaymentMethodDef) {
  return method.customName || (method.i18nKey ? t(method.i18nKey) : '')
}

async function loadReferenceData() {
  const [methods, staff, suggestions, defaults] = await Promise.all([
    fetchPaymentMethods(props.branchId),
    fetchStaffByBranch(props.branchId),
    fetchExpenseSuggestions(props.branchId),
    fetchCashRegisterDefaults(props.branchId),
  ])
  paymentMethods.value = methods
  syncPaymentAmountKeysOn(data.value.paymentAmounts, methods)
  staffList.value = staff
  topSuggestions.value = suggestions.slice(0, 3)
  cashDefaults.value = defaults
}
onMounted(loadReferenceData)
watch(() => props.branchId, loadReferenceData)

async function refreshPaymentMethods() {
  const methods = await fetchPaymentMethods(props.branchId)
  paymentMethods.value = methods
  syncPaymentAmountKeysOn(data.value.paymentAmounts, methods)
}

// ---- payment methods ------------------------------------------------------
const editingMethods = ref(false)

async function renameMethod(method: PaymentMethodDef) {
  try {
    const { value } = await ElMessageBox.prompt(t('dailyReport.addPaymentMethodPlaceholder'), t('dailyReport.renamePaymentMethod'), {
      inputValue: methodLabel(method), confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
      inputValidator: (v: string) => !!v?.trim(),
    })
    await renamePaymentMethod(method.id, value.trim())
    await refreshPaymentMethods()
  } catch { /* cancelled */ }
}
async function removeMethod(method: PaymentMethodDef) {
  try {
    await ElMessageBox.confirm(t('dailyReport.deletePaymentMethodConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
    })
    await deletePaymentMethod(method.id)
    await refreshPaymentMethods()
  } catch { /* cancelled */ }
}
async function addMethod() {
  try {
    const { value } = await ElMessageBox.prompt(t('dailyReport.addPaymentMethodPlaceholder'), t('dailyReport.addPaymentMethod'), {
      confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputValidator: (v: string) => !!v?.trim(),
    })
    await addPaymentMethod(props.branchId, value.trim())
    await refreshPaymentMethods()
  } catch { /* cancelled */ }
}

// ---- cash register ---------------------------------------------------------
function breakdown(denomination: number) {
  return cashRegisterDenominationBreakdown(
    denomination, data.value.cashRegisterCounts, cashDefaults.value.denominationDefaults, props.reportDate,
  )
}
const cashStatusText = computed(() => {
  const s = cashStatus.value
  if (s.status === 'match') return t('dailyReport.cashRegisterMatch')
  if (s.status === 'over') return t('dailyReport.cashRegisterOver', { amount: formatCurrency(s.difference) })
  if (s.status === 'short') return t('dailyReport.cashRegisterShort', { amount: formatCurrency(Math.abs(s.difference)) })
  return t('dailyReport.cashRegisterEmpty')
})

const savingSettings = ref(false)
// Edits made in the collapsed settings block are sent along with the main 保存,
// so the difference the user saw on screen matches what the PDF and tomorrow's
// report will use (the desktop form saves each field as it changes).
const settingsDirty = ref(false)
async function saveCashSettings() {
  savingSettings.value = true
  try {
    cashDefaults.value = await updateCashRegisterDefaults(props.branchId, {
      expectedTotal: cashDefaults.value.expectedTotal,
      denominationDefaults: { ...cashDefaults.value.denominationDefaults },
    })
    settingsDirty.value = false
    ElMessage.success(t('dailyReport.mSettingsSaved'))
  } finally {
    savingSettings.value = false
  }
}
function defaultOf(denomination: number) {
  return cashDefaults.value.denominationDefaults[String(denomination)] ?? 0
}
function setDefault(denomination: number, value: number | null | undefined) {
  cashDefaults.value.denominationDefaults[String(denomination)] = value ?? 0
  settingsDirty.value = true
}
function setExpectedTotal(value: number | null | undefined) {
  cashDefaults.value.expectedTotal = value ?? 0
  settingsDirty.value = true
}
async function onSave() {
  if (settingsDirty.value && showDefaultsSettings.value && !props.readonly) {
    try {
      await saveCashSettings()
    } catch {
      return
    }
  }
  emit('save')
}

// ---- expenses --------------------------------------------------------------
function addExpenseRow() { data.value.expenses.push({ itemName: '', amount: null, purpose: '' }) }
function removeExpenseRow(index: number) { data.value.expenses.splice(index, 1) }
// Item name (and purpose, which tends to repeat) come from history; the
// amount never does — same rule as the desktop form.
function applyQuickSuggestion(s: ExpenseSuggestion) {
  const emptyRow = data.value.expenses.find((r) => !r.itemName)
  const target = emptyRow ?? { itemName: '', amount: null, purpose: '' }
  target.itemName = s.itemName
  target.purpose = s.lastPurpose
  if (!emptyRow) data.value.expenses.push(target)
}
</script>

<template>
  <div class="dmf">
    <nav class="dmf-steps" :aria-label="t('dailyReport.mStepsLabel')">
      <button
        v-for="(key, index) in STEPS" :key="key" type="button" class="dmf-step"
        :class="{ 'is-active': step === index, 'is-done': index < step }" :aria-current="step === index ? 'step' : undefined"
        @click="goTo(index)"
      >
        <span class="dmf-step-no">{{ index + 1 }}</span>
        <span class="dmf-step-name">{{ t(`dailyReport.${key}`) }}</span>
      </button>
    </nav>

    <!-- 1. basics -->
    <section v-show="step === 0" class="dmf-card">
      <h2 class="dmf-h">{{ t(`dailyReport.${STEPS[0]}`) }}</h2>
      <div class="dmf-field">
        <label class="dmf-label" for="dmf-person">{{ t('dailyReport.personInCharge') }}</label>
        <select id="dmf-person" v-model="data.personInCharge" class="dmf-select" :disabled="readonly">
          <option value="">{{ t('dailyReport.personInChargePlaceholder') }}</option>
          <option v-for="s in hallStaff" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>
      <MobileNumberInput v-model="data.totalRevenue" :label="t('dailyReport.totalRevenue')" prefix="¥" :disabled="readonly" />
      <MobileNumberInput v-model="data.totalCustomers" :label="t('dailyReport.totalCustomers')" :disabled="readonly" />
      <MobileNumberInput v-model="data.groupCount" :label="t('dailyReport.groupCount')" :disabled="readonly" />
      <h3 class="dmf-h3">{{ t('dailyReport.splitLabel') }}</h3>
      <MobileNumberInput v-model="data.morningRevenue" :label="t('dailyReport.morningRevenue')" prefix="¥" :disabled="readonly" />
      <MobileNumberInput v-model="data.morningCustomers" :label="t('dailyReport.morningCustomers')" :disabled="readonly" />
      <MobileNumberInput v-model="data.morningGroupCount" :label="t('dailyReport.morningGroupCount')" :disabled="readonly" />
    </section>

    <!-- 2. payment methods -->
    <section v-show="step === 1" class="dmf-card">
      <h2 class="dmf-h">{{ t('dailyReport.paymentMethodsTitle') }}</h2>
      <div v-for="method in visibleMethods" :key="method.id" class="dmf-method">
        <MobileNumberInput
          v-if="method.protected" :model-value="derived.cashAmount" :label="t('dailyReport.mCashSales')"
          prefix="¥" :auto-value="formatNumber(derived.cashAmount)"
        />
        <MobileNumberInput
          v-else v-model="data.paymentAmounts[String(method.id)]" :label="methodLabel(method)" prefix="¥" :disabled="readonly"
        />
        <div v-if="editingMethods && !method.protected && !readonly" class="dmf-method-actions">
          <button type="button" class="dmf-btn dmf-btn-ghost" @click="renameMethod(method)">
            <el-icon><EditPen /></el-icon>{{ t('dailyReport.renamePaymentMethod') }}
          </button>
          <button type="button" class="dmf-btn dmf-btn-danger" @click="removeMethod(method)">
            <el-icon><Close /></el-icon>{{ t('common.delete') }}
          </button>
        </div>
      </div>
      <div v-if="!readonly" class="dmf-row-buttons">
        <button type="button" class="dmf-btn dmf-btn-ghost" @click="addMethod">
          <el-icon><Plus /></el-icon>{{ t('dailyReport.addPaymentMethod') }}
        </button>
        <button type="button" class="dmf-btn dmf-btn-ghost" @click="editingMethods = !editingMethods">
          {{ editingMethods ? t('dailyReport.mEditMethodsDone') : t('dailyReport.mEditMethods') }}
        </button>
      </div>
    </section>

    <!-- 3. cash register -->
    <section v-show="step === 2" class="dmf-card">
      <h2 class="dmf-h">{{ t('dailyReport.cashRegisterTitle') }}</h2>
      <p class="dmf-note">{{ t('dailyReport.cashRegisterHint') }}</p>
      <div v-for="denomination in CASH_REGISTER_DENOMINATIONS" :key="denomination" class="dmf-denom">
        <div class="dmf-denom-top">
          <strong class="dmf-denom-name">{{ formatCurrency(denomination) }}</strong>
          <span class="dmf-denom-sub">{{ formatCurrency(breakdown(denomination).subtotal) }}</span>
        </div>
        <MobileStepper
          v-model="data.cashRegisterCounts[String(denomination)]" :label="formatCurrency(denomination)"
          :minus-label="t('dailyReport.mMinus')" :plus-label="t('dailyReport.mPlus')" :disabled="readonly"
        />
        <span v-if="breakdown(denomination).defaultQuantity" class="dmf-denom-default">
          {{ t('dailyReport.mIncludesDefault', { count: breakdown(denomination).defaultQuantity }) }}
        </span>
      </div>
      <dl class="dmf-sum">
        <div><dt>{{ t('dailyReport.cashRegisterExpected') }}</dt><dd>{{ formatCurrency(cashDefaults.expectedTotal) }}</dd></div>
        <div><dt>{{ t('dailyReport.cashRegisterActual') }}</dt><dd>{{ formatCurrency(cashStatus.actual) }}</dd></div>
        <div class="is-strong" :class="`is-${cashStatus.status}`"><dt>{{ t('dailyReport.cashRegisterDifference') }}</dt><dd>{{ cashStatusText }}</dd></div>
      </dl>
      <details v-if="showDefaultsSettings && !readonly" class="dmf-settings">
        <summary>{{ t('dailyReport.mCashSettings') }}</summary>
        <MobileNumberInput
          :model-value="cashDefaults.expectedTotal" :label="t('dailyReport.cashRegisterExpected')" prefix="¥"
          @update:model-value="setExpectedTotal"
        />
        <div v-for="denomination in CASH_REGISTER_FLOAT_DENOMINATIONS" :key="denomination" class="dmf-denom">
          <strong class="dmf-denom-name">{{ formatCurrency(denomination) }} · {{ t('dailyReport.cashRegisterDefaultQuantity') }}</strong>
          <MobileStepper
            :model-value="defaultOf(denomination)" :label="`${formatCurrency(denomination)} ${t('dailyReport.cashRegisterDefaultQuantity')}`"
            :minus-label="t('dailyReport.mMinus')" :plus-label="t('dailyReport.mPlus')" @update:model-value="setDefault(denomination, $event)"
          />
        </div>
        <button type="button" class="dmf-btn dmf-btn-primary" :disabled="savingSettings" @click="saveCashSettings">
          {{ t('dailyReport.mCashSettingsSave') }}
        </button>
      </details>
    </section>

    <!-- 4. expenses -->
    <section v-show="step === 3" class="dmf-card">
      <h2 class="dmf-h">{{ t('dailyReport.expenseTitle') }}</h2>
      <p class="dmf-total">{{ t('dailyReport.expenseTotal') }}　<strong>{{ formatCurrency(derived.expenseTotal) }}</strong></p>
      <div v-if="!readonly && topSuggestions.length" class="dmf-chips" role="group" :aria-label="t('dailyReport.mQuickAdd')">
        <button v-for="s in topSuggestions" :key="s.itemName" type="button" class="dmf-chip" @click="applyQuickSuggestion(s)">{{ s.itemName }}</button>
      </div>
      <p v-if="!data.expenses.length" class="dmf-note">{{ t('dailyReport.mNoExpenses') }}</p>
      <div v-for="(row, index) in data.expenses" :key="index" class="dmf-expense">
        <div class="dmf-expense-head">
          <strong>{{ t('dailyReport.mExpenseRowN', { n: index + 1 }) }}</strong>
          <button v-if="!readonly" type="button" class="dmf-btn dmf-btn-danger dmf-btn-small" @click="removeExpenseRow(index)">
            <el-icon><Close /></el-icon>{{ t('dailyReport.mRemoveRow') }}
          </button>
        </div>
        <div class="dmf-field">
          <label class="dmf-label" :for="`dmf-item-${index}`">{{ t('dailyReport.itemName') }}</label>
          <input :id="`dmf-item-${index}`" v-model="row.itemName" class="dmf-text" type="text" autocomplete="off" :disabled="readonly">
        </div>
        <MobileNumberInput v-model="row.amount" :label="t('dailyReport.amount')" prefix="¥" :disabled="readonly" />
        <div class="dmf-field">
          <label class="dmf-label" :for="`dmf-purpose-${index}`">{{ t('dailyReport.purpose') }}</label>
          <input :id="`dmf-purpose-${index}`" v-model="row.purpose" class="dmf-text" type="text" autocomplete="off" :disabled="readonly">
        </div>
      </div>
      <button v-if="!readonly" type="button" class="dmf-btn dmf-btn-ghost dmf-btn-wide" @click="addExpenseRow">
        <el-icon><Plus /></el-icon>{{ t('dailyReport.addExpenseRow') }}
      </button>
    </section>

    <!-- 5. confirm -->
    <section v-show="step === 4" class="dmf-card">
      <h2 class="dmf-h">{{ t('dailyReport.mSummaryTitle') }}</h2>
      <dl class="dmf-sum">
        <div><dt>{{ t('dailyReport.totalRevenue') }}</dt><dd>{{ formatCurrency(data.totalRevenue ?? 0) }}</dd></div>
        <div><dt>{{ t('dailyReport.totalCustomers') }}</dt><dd>{{ formatNumber(data.totalCustomers ?? 0) }}</dd></div>
        <div><dt>{{ t('dailyReport.groupCount') }}</dt><dd>{{ formatNumber(data.groupCount ?? 0) }}</dd></div>
        <div><dt>{{ t('dailyReport.morningRevenue') }}</dt><dd>{{ formatCurrency(data.morningRevenue ?? 0) }}</dd></div>
        <div><dt>{{ t('dailyReport.afternoonRevenueAuto') }}</dt><dd>{{ formatCurrency(derived.afternoonRevenue) }}</dd></div>
        <div><dt>{{ t('dailyReport.afternoonCustomersAuto') }}</dt><dd>{{ formatNumber(derived.afternoonCustomers) }}</dd></div>
        <div><dt>{{ t('dailyReport.afternoonGroupCountAuto') }}</dt><dd>{{ formatNumber(derived.afternoonGroupCount) }}</dd></div>
        <div><dt>{{ t('dailyReport.mCashSales') }}</dt><dd>{{ formatCurrency(derived.cashAmount) }}</dd></div>
        <div><dt>{{ t('dailyReport.expenseTotal') }}</dt><dd>{{ formatCurrency(derived.expenseTotal) }}</dd></div>
        <div class="is-strong"><dt>{{ t('dailyReport.cashRemaining') }}</dt><dd>{{ formatCurrency(derived.cashRemaining) }}</dd></div>
        <div class="is-strong" :class="`is-${cashStatus.status}`"><dt>{{ t('dailyReport.cashRegisterDifference') }}</dt><dd>{{ cashStatusText }}</dd></div>
      </dl>
      <button type="button" class="dmf-btn dmf-btn-ghost dmf-btn-wide" @click="emit('history')">{{ t('dailyReport.viewHistory') }}</button>
    </section>

    <div class="dmf-bar no-print">
      <button type="button" class="dmf-btn dmf-btn-ghost dmf-bar-btn" :disabled="step === 0" @click="goTo(step - 1)">{{ t('dailyReport.mPrev') }}</button>
      <button type="button" class="dmf-btn dmf-btn-ghost dmf-bar-btn" :disabled="step === STEPS.length - 1" @click="goTo(step + 1)">{{ t('dailyReport.mNext') }}</button>
      <button type="button" class="dmf-btn dmf-btn-primary dmf-bar-save" :disabled="readonly || saving || savingSettings" @click="onSave">
        {{ saving ? t('dailyReport.mSaving') : t('dailyReport.submit') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.dmf { display: flex; flex-direction: column; gap: 14px; padding-bottom: 88px; font-size: 16px; color: var(--text-primary); }
.dmf-steps { display: flex; gap: 4px; }
.dmf-step {
  flex: 1 1 0; min-width: 0; min-height: 56px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; background: var(--surface); color: var(--text-secondary); font: inherit; cursor: pointer;
}
.dmf-step-no { font-size: 16px; font-weight: 800; line-height: 1; }
.dmf-step-name { font-size: 14px; font-weight: 700; line-height: 1.1; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dmf-step.is-done { color: var(--text-primary); }
.dmf-step.is-active { background: var(--accent); border-color: var(--accent); color: #fff; }
.dmf-card { display: flex; flex-direction: column; gap: 16px; padding: 18px 16px; background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-soft); }
.dmf-h { margin: 0; font-size: 20px; font-weight: 800; }
.dmf-h3 { margin: 6px 0 0; font-size: 17px; font-weight: 700; color: var(--text-secondary); }
.dmf-note { margin: 0; font-size: 16px; color: var(--text-secondary); }
.dmf-field { display: flex; flex-direction: column; gap: 6px; }
.dmf-label { font-size: 16px; font-weight: 700; }
.dmf-select, .dmf-text {
  width: 100%; box-sizing: border-box; min-height: 56px; padding: 0 14px; font: inherit; font-size: 18px; color: var(--text-primary);
  background: var(--surface); border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; outline: 0;
}
.dmf-select:focus, .dmf-text:focus { border-color: var(--accent); }
.dmf-select:disabled, .dmf-text:disabled { background: var(--surface-alt); }
.dmf-method { display: flex; flex-direction: column; gap: 8px; }
.dmf-method-actions, .dmf-row-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.dmf-btn {
  min-height: 52px; padding: 0 16px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; box-sizing: border-box;
  font: inherit; font-size: 16px; font-weight: 700; border-radius: 12px; border: 2px solid transparent; cursor: pointer;
}
.dmf-btn:disabled { opacity: 0.45; cursor: default; }
.dmf-btn-small { min-height: 48px; }
.dmf-btn-wide { width: 100%; }
.dmf-btn-primary { background: var(--accent); color: #fff; }
.dmf-btn-ghost { background: var(--surface); color: var(--text-primary); border-color: var(--border-strong, #c9cdd1); }
.dmf-btn-danger { background: var(--surface); color: var(--danger); border-color: var(--danger); }
.dmf-denom { display: flex; flex-direction: column; gap: 8px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.dmf-denom-top { display: flex; align-items: baseline; justify-content: space-between; }
.dmf-denom-name { font-size: 18px; }
.dmf-denom-sub { font-size: 18px; font-weight: 700; }
.dmf-denom-default { font-size: 16px; color: var(--text-secondary); }
.dmf-settings { border: 2px dashed var(--border-strong, #c9cdd1); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 14px; }
.dmf-settings summary { min-height: 48px; display: flex; align-items: center; font-weight: 700; cursor: pointer; }
.dmf-sum { margin: 0; display: flex; flex-direction: column; }
.dmf-sum > div { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); font-size: 17px; }
.dmf-sum dt { color: var(--text-secondary); }
.dmf-sum dd { margin: 0; font-weight: 800; text-align: right; }
.dmf-sum .is-strong dd { font-size: 20px; }
.dmf-sum .is-short dd { color: var(--danger); }
.dmf-sum .is-over dd { color: var(--warning); }
.dmf-sum .is-match dd { color: var(--success); }
.dmf-total { margin: 0; font-size: 17px; }
.dmf-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.dmf-chip { min-height: 48px; padding: 0 16px; border-radius: 24px; border: 2px solid var(--accent); background: var(--accent-light); color: var(--accent); font: inherit; font-size: 16px; font-weight: 700; cursor: pointer; }
.dmf-expense { display: flex; flex-direction: column; gap: 14px; padding: 14px; border: 2px solid var(--border); border-radius: 14px; }
.dmf-expense-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.dmf-bar {
  position: fixed; left: 0; right: 0; bottom: var(--mobile-nav-h, 0px); z-index: 70;
  display: grid; grid-template-columns: 1fr 1fr 1.5fr; gap: 8px; padding: 10px 12px;
  background: var(--surface); border-top: 1px solid var(--border); box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.06);
}
.dmf-bar-btn, .dmf-bar-save { min-height: 52px; padding: 0 6px; }
</style>
