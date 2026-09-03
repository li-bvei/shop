<script lang="ts">
export interface ExpenseRow {
  itemName: string
  amount: number | null
  purpose: string
}

export const CASH_REGISTER_DENOMINATIONS = [10000, 5000, 1000, 500, 100, 50, 10, 5, 1] as const
export const CASH_REGISTER_EXPECTED_TOTAL = 130000

export interface DailyReportFormData {
  personInCharge: string
  totalRevenue: number | null
  totalCustomers: number | null
  groupCount: number | null
  morningRevenue: number | null
  morningCustomers: number | null
  morningGroupCount: number | null
  paymentAmounts: Record<string, number | null>
  expenses: ExpenseRow[]
  cashRegisterCounts: Record<string, number | null>
}

export function createEmptyCashRegisterCounts(): Record<string, number | null> {
  return Object.fromEntries(CASH_REGISTER_DENOMINATIONS.map((denomination) => [String(denomination), null]))
}

/** Makes old history snapshots and pre-feature API responses safe to edit. */
export function normalizeDailyReportFormData(data: Partial<DailyReportFormData>): DailyReportFormData {
  return {
    personInCharge: data.personInCharge ?? '',
    totalRevenue: data.totalRevenue ?? null,
    totalCustomers: data.totalCustomers ?? null,
    groupCount: data.groupCount ?? null,
    morningRevenue: data.morningRevenue ?? null,
    morningCustomers: data.morningCustomers ?? null,
    morningGroupCount: data.morningGroupCount ?? null,
    paymentAmounts: { ...data.paymentAmounts },
    expenses: (data.expenses ?? []).map((row) => ({ ...row, amount: row.amount ?? null })),
    cashRegisterCounts: {
      ...createEmptyCashRegisterCounts(),
      ...data.cashRegisterCounts,
    },
  }
}

/**
 * Every value the save/export/history flows need but that isn't stored
 * directly on the form. `paymentMethods` is the source of truth for which
 * ids currently count as "non-cash" — summing over every key already in
 * `data.paymentAmounts` instead is wrong, because that record can carry
 * stale ids left over from a previous set of payment methods (e.g. after
 * renaming/re-seeding), which would get silently counted as non-cash and
 * drag the auto-calculated cash amount negative even though nothing on
 * screen shows where the money went.
 */
export function computeDerived(
  data: DailyReportFormData,
  paymentMethods: { id: number; protected: boolean }[],
) {
  const totalRevenue = data.totalRevenue ?? 0
  const morningRevenue = data.morningRevenue ?? 0
  const totalCustomers = data.totalCustomers ?? 0
  const morningCustomers = data.morningCustomers ?? 0
  const groupCount = data.groupCount ?? 0
  const morningGroupCount = data.morningGroupCount ?? 0
  const afternoonRevenue = totalRevenue - morningRevenue
  const afternoonCustomers = totalCustomers - morningCustomers
  const afternoonGroupCount = groupCount - morningGroupCount
  const expenseTotal = data.expenses.reduce((sum, row) => sum + (row.amount ?? 0), 0)
  const nonCashSum = paymentMethods.reduce(
    (sum, m) => (m.protected ? sum : sum + (data.paymentAmounts[String(m.id)] ?? 0)),
    0,
  )
  const cashAmount = totalRevenue - nonCashSum
  const cashRemaining = cashAmount - expenseTotal
  return { afternoonRevenue, afternoonCustomers, afternoonGroupCount, expenseTotal, cashAmount, cashRemaining }
}

export function computeCashRegisterTotal(counts: Record<string, number | null | undefined>) {
  return CASH_REGISTER_DENOMINATIONS.reduce(
    (sum, denomination) => sum + denomination * (counts[String(denomination)] ?? 0),
    0,
  )
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import {
  Plus, Close, Wallet, EditPen, User, CreditCard, Tickets,
  CircleCheckFilled, WarningFilled, CircleCloseFilled,
} from '@element-plus/icons-vue'
import {
  fetchPaymentMethods,
  renamePaymentMethod,
  deletePaymentMethod,
  addPaymentMethod,
  fetchExpenseSuggestions,
  type ExpenseSuggestion,
} from '@/api/masterData'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import type { PaymentMethodDef } from '@/api/masterData'
import { formatCurrency } from '@/utils/format'

const props = defineProps<{ branchId: string }>()
const data = defineModel<DailyReportFormData>('data', { required: true })

const { t } = useI18n()

interface SuggestionOption extends ExpenseSuggestion {
  value: string
}

const staffList = ref<StaffMember[]>([])
const paymentMethods = ref<PaymentMethodDef[]>([])
const topSuggestions = ref<SuggestionOption[]>([])

const derived = computed(() => computeDerived(data.value, paymentMethods.value))
const cashRegister = computed(() => {
  const actual = computeCashRegisterTotal(data.value.cashRegisterCounts)
  const difference = actual - CASH_REGISTER_EXPECTED_TOTAL
  const hasInput = CASH_REGISTER_DENOMINATIONS.some(
    (denomination) => data.value.cashRegisterCounts[String(denomination)] != null,
  )
  return {
    actual,
    difference,
    status: !hasInput ? 'empty' : difference === 0 ? 'match' : difference > 0 ? 'over' : 'short',
  } as const
})

// Only hall (front-of-house) staff can be recorded as the person in charge
// of the daily report — kitchen staff aren't customer/cash-facing, so
// listing them here would just invite the wrong person being picked.
const hallStaff = computed(() => staffList.value.filter((s) => s.workArea === 'hall'))

function paymentMethodLabel(method: PaymentMethodDef) {
  return method.customName || (method.i18nKey ? t(method.i18nKey) : '')
}

// Drop any paymentAmounts keys that aren't one of the branch's current
// method ids (e.g. left over from before a rename/re-seed) and backfill
// zeroes for newly-added methods — keeps the record exactly matching what's
// on screen, which is what computeDerived's non-cash sum relies on. Keyed
// by id (not code) since code is only unique within one branch.
function syncPaymentAmountKeys(methods: PaymentMethodDef[]) {
  const validKeys = new Set(methods.map((m) => String(m.id)))
  for (const key of Object.keys(data.value.paymentAmounts)) {
    if (!validKeys.has(key)) delete data.value.paymentAmounts[key]
  }
  for (const method of methods) {
    const key = String(method.id)
    if (!(key in data.value.paymentAmounts)) data.value.paymentAmounts[key] = null
  }
}

async function refreshPaymentMethods() {
  const methods = await fetchPaymentMethods(props.branchId)
  paymentMethods.value = methods
  syncPaymentAmountKeys(methods)
}

async function loadReferenceData() {
  const [methods, staff, suggestions] = await Promise.all([
    fetchPaymentMethods(props.branchId),
    fetchStaffByBranch(props.branchId),
    fetchExpenseSuggestions(props.branchId),
  ])
  paymentMethods.value = methods
  syncPaymentAmountKeys(methods)
  staffList.value = staff
  topSuggestions.value = suggestions.slice(0, 3).map((s) => ({ ...s, value: s.itemName }))
}

onMounted(loadReferenceData)
watch(() => props.branchId, loadReferenceData)

function addExpenseRow() {
  data.value.expenses.push({ itemName: '', amount: null, purpose: '' })
}

function removeExpenseRow(index: number) {
  data.value.expenses.splice(index, 1)
}

async function querySuggestions(queryString: string, cb: (results: SuggestionOption[]) => void) {
  const results = await fetchExpenseSuggestions(props.branchId, queryString)
  cb(results.map((s) => ({ ...s, value: s.itemName })))
}

function handleSelectSuggestion(row: ExpenseRow, suggestion: SuggestionOption) {
  row.itemName = suggestion.itemName
  row.amount = suggestion.lastAmount
  row.purpose = suggestion.lastPurpose
}

function applyQuickSuggestion(suggestion: SuggestionOption) {
  const emptyRow = data.value.expenses.find((r) => !r.itemName)
  const target = emptyRow ?? { itemName: '', amount: null, purpose: '' }
  target.itemName = suggestion.itemName
  target.amount = suggestion.lastAmount
  target.purpose = suggestion.lastPurpose
  if (!emptyRow) data.value.expenses.push(target)
}

async function handleRenamePaymentMethod(method: PaymentMethodDef) {
  try {
    const { value } = await ElMessageBox.prompt(
      t('dailyReport.addPaymentMethodPlaceholder'),
      t('dailyReport.renamePaymentMethod'),
      {
        inputValue: paymentMethodLabel(method),
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        inputValidator: (value: string) => !!value?.trim(),
      },
    )
    await renamePaymentMethod(method.id, value.trim())
    await refreshPaymentMethods()
  } catch {
    // cancelled
  }
}

async function handleDeletePaymentMethod(method: PaymentMethodDef) {
  try {
    await ElMessageBox.confirm(t('dailyReport.deletePaymentMethodConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deletePaymentMethod(method.id)
    await refreshPaymentMethods()
  } catch {
    // cancelled
  }
}

async function handleAddPaymentMethod() {
  try {
    const { value } = await ElMessageBox.prompt(
      t('dailyReport.addPaymentMethodPlaceholder'),
      t('dailyReport.addPaymentMethod'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        inputValidator: (value: string) => !!value?.trim(),
      },
    )
    await addPaymentMethod(props.branchId, value.trim())
    await refreshPaymentMethods()
  } catch {
    // cancelled
  }
}
</script>

<template>
  <div class="daily-report-form">
    <section class="report-section">
      <div class="form-field standalone person-field">
        <label><el-icon class="field-icon"><User /></el-icon>{{ t('dailyReport.personInCharge') }}</label>
        <el-select
          v-model="data.personInCharge"
          style="width: 200px"
          :placeholder="t('dailyReport.personInChargePlaceholder')"
        >
          <el-option v-for="s in hallStaff" :key="s.id" :value="s.id" :label="s.name" />
        </el-select>
      </div>

      <div class="stat-grid">
        <div class="stat-tile">
          <label>{{ t('dailyReport.totalRevenue') }}</label>
          <el-input v-model.number="data.totalRevenue" type="number">
            <template #prefix>¥</template>
          </el-input>
        </div>
        <div class="stat-tile">
          <label>{{ t('dailyReport.totalCustomers') }}</label>
          <el-input v-model.number="data.totalCustomers" type="number" />
        </div>
        <div class="stat-tile">
          <label>{{ t('dailyReport.groupCount') }}</label>
          <el-input v-model.number="data.groupCount" type="number" />
        </div>
      </div>

      <div class="section-title">{{ t('dailyReport.splitLabel') }}</div>
      <div class="stat-grid">
        <div class="stat-tile">
          <label>{{ t('dailyReport.morningRevenue') }}</label>
          <el-input v-model.number="data.morningRevenue" type="number">
            <template #prefix>¥</template>
          </el-input>
        </div>
        <div class="stat-tile">
          <label>{{ t('dailyReport.morningCustomers') }}</label>
          <el-input v-model.number="data.morningCustomers" type="number" />
        </div>
        <div class="stat-tile">
          <label>{{ t('dailyReport.morningGroupCount') }}</label>
          <el-input v-model.number="data.morningGroupCount" type="number" />
        </div>
      </div>
      <div class="stat-grid">
        <div class="stat-tile auto">
          <label>{{ t('dailyReport.afternoonRevenueAuto') }}</label>
          <el-input :model-value="derived.afternoonRevenue" disabled>
            <template #prefix>¥</template>
          </el-input>
        </div>
        <div class="stat-tile auto">
          <label>{{ t('dailyReport.afternoonCustomersAuto') }}</label>
          <el-input :model-value="derived.afternoonCustomers" disabled />
        </div>
        <div class="stat-tile auto">
          <label>{{ t('dailyReport.afternoonGroupCountAuto') }}</label>
          <el-input :model-value="derived.afternoonGroupCount" disabled />
        </div>
      </div>
    </section>

    <div class="two-col-section">
      <section class="report-section col">
        <div class="section-title"><el-icon class="field-icon"><CreditCard /></el-icon>{{ t('dailyReport.paymentMethodsTitle') }}</div>
        <div class="list-rows">
          <div v-for="method in paymentMethods" :key="method.id" class="pm-row">
            <span class="pm-name"><span class="pm-dot" />{{ paymentMethodLabel(method) }}</span>
            <div class="pm-controls">
              <el-input
                v-if="method.protected"
                :model-value="derived.cashAmount"
                type="number"
                class="pm-input auto"
                disabled
              />
              <el-input
                v-else
                v-model.number="data.paymentAmounts[String(method.id)]"
                type="number"
                class="pm-input"
              />
              <div class="pm-actions no-print" :class="{ 'is-hidden': method.protected }">
                <el-button circle text :icon="EditPen" size="small" @click="handleRenamePaymentMethod(method)" />
                <el-button circle text :icon="Close" size="small" @click="handleDeletePaymentMethod(method)" />
              </div>
            </div>
          </div>
        </div>
        <span class="add-row-btn no-print" @click="handleAddPaymentMethod">
          <el-icon><Plus /></el-icon>{{ t('dailyReport.addPaymentMethod') }}
        </span>
      </section>

      <div class="cash-expense-col">
        <section class="report-section col cash-register-section">
          <div class="section-title">
            <el-icon class="field-icon"><Wallet /></el-icon>{{ t('dailyReport.cashRegisterTitle') }}
          </div>
          <p class="cash-register-hint">{{ t('dailyReport.cashRegisterHint') }}</p>
          <div class="cash-register-layout">
            <div class="cash-register-table">
              <div class="cash-register-row cash-register-header">
                <span>{{ t('dailyReport.cashRegisterDenomination') }}</span>
                <span>{{ t('dailyReport.cashRegisterQuantity') }}</span>
                <span>{{ t('dailyReport.cashRegisterSubtotal') }}</span>
              </div>
              <div v-for="denomination in CASH_REGISTER_DENOMINATIONS" :key="denomination" class="cash-register-row">
                <strong>{{ formatCurrency(denomination) }}</strong>
                <el-input
                  v-model.number="data.cashRegisterCounts[String(denomination)]"
                  type="number"
                  min="0"
                  step="1"
                  class="cash-register-quantity"
                />
                <span class="cash-register-subtotal">{{ formatCurrency(denomination * (data.cashRegisterCounts[String(denomination)] ?? 0)) }}</span>
              </div>
            </div>
            <div class="cash-register-summary">
              <div class="cash-register-summary-row">
                <span>{{ t('dailyReport.cashRegisterExpected') }}</span>
                <strong>{{ formatCurrency(CASH_REGISTER_EXPECTED_TOTAL) }}</strong>
              </div>
              <div class="cash-register-summary-row actual">
                <span>{{ t('dailyReport.cashRegisterActual') }}</span>
                <strong>{{ formatCurrency(cashRegister.actual) }}</strong>
              </div>
              <div class="cash-register-status" :class="`is-${cashRegister.status}`">
                <el-icon v-if="cashRegister.status === 'match'"><CircleCheckFilled /></el-icon>
                <el-icon v-else-if="cashRegister.status === 'over'"><WarningFilled /></el-icon>
                <el-icon v-else-if="cashRegister.status === 'short'"><CircleCloseFilled /></el-icon>
                <el-icon v-else><Wallet /></el-icon>
                <span v-if="cashRegister.status === 'match'">{{ t('dailyReport.cashRegisterMatch') }}</span>
                <span v-else-if="cashRegister.status === 'over'">{{ t('dailyReport.cashRegisterOver', { amount: formatCurrency(cashRegister.difference) }) }}</span>
                <span v-else-if="cashRegister.status === 'short'">{{ t('dailyReport.cashRegisterShort', { amount: formatCurrency(Math.abs(cashRegister.difference)) }) }}</span>
                <span v-else>{{ t('dailyReport.cashRegisterEmpty') }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="report-section col expense-section">
          <div class="section-title expense-label-row">
            <span><el-icon class="field-icon"><Tickets /></el-icon>{{ t('dailyReport.expenseTitle') }}</span>
            <span class="expense-total">{{ t('dailyReport.expenseTotal') }} {{ formatCurrency(derived.expenseTotal) }}</span>
          </div>
          <div v-for="(row, index) in data.expenses" :key="index" class="expense-row">
            <div class="i1">
              <el-autocomplete
                v-model="row.itemName"
                :placeholder="t('dailyReport.itemNamePlaceholder')"
                :fetch-suggestions="querySuggestions"
                @select="(s: SuggestionOption) => handleSelectSuggestion(row, s)"
              >
                <template #default="{ item }">
                  <div class="suggestion-item">
                    <span>{{ item.itemName }}</span>
                    <span class="suggestion-meta">{{ formatCurrency(item.lastAmount) }}</span>
                  </div>
                </template>
              </el-autocomplete>
            </div>
            <el-input v-model.number="row.amount" class="i2" type="number">
              <template #prefix>¥</template>
            </el-input>
            <el-input v-model="row.purpose" class="i3" :placeholder="t('dailyReport.purposePlaceholder')" />
            <el-button circle text :icon="Close" class="no-print" @click="removeExpenseRow(index)" />
          </div>

          <div class="expense-actions no-print">
            <span class="add-row-btn" @click="addExpenseRow"><el-icon><Plus /></el-icon>{{ t('dailyReport.addExpenseRow') }}</span>
            <span
              v-for="s in topSuggestions"
              :key="s.itemName"
              class="suggest-tag"
              @click="applyQuickSuggestion(s)"
            >{{ s.itemName }}</span>
          </div>
        </section>
      </div>
    </div>

    <div class="cash-stat">
      <div class="left">
        <el-icon :size="19"><Wallet /></el-icon>
        <span class="label">{{ t('dailyReport.cashRemaining') }}</span>
      </div>
      <span class="value">{{ formatCurrency(derived.cashRemaining) }}</span>
    </div>
  </div>
</template>

<style scoped>
.top-fields {
  max-width: 620px;
}

.report-section {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 16px;
}

.field-icon {
  color: var(--text-tertiary);
  margin-right: 5px;
  vertical-align: -2px;
}

.person-field {
  margin-bottom: 18px;
}

.person-field label {
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.form-field.standalone {
  margin-bottom: 18px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 6px;
}

.stat-tile {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px 12px;
}

.stat-tile.auto {
  background: var(--track-bg);
}

.stat-tile label {
  font-size: 12px;
  color: var(--text-secondary);
  display: block;
  margin-bottom: 6px;
}

.stat-tile :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  background: var(--surface);
  box-shadow: none;
}

.stat-tile.auto :deep(.el-input__wrapper) {
  background: transparent;
}

.section-title {
  display: flex;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 20px 0 12px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.report-section > .section-title:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}

.two-col-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}

.cash-expense-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.cash-expense-col > .expense-section {
  order: -1;
}

.cash-expense-col > .report-section {
  margin-bottom: 0;
}

@media (max-width: 760px) {
  .two-col-section {
    grid-template-columns: 1fr;
  }
}

.list-rows {
  border-top: 1px solid var(--border);
}

.pm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 2px;
  border-bottom: 1px solid var(--border);
  gap: 10px;
}

.pm-name {
  font-size: 13.5px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
  min-width: 0;
}

.pm-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
  flex-shrink: 0;
}

.pm-controls {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.pm-input {
  width: 110px;
}

.pm-input :deep(.el-input__inner) {
  text-align: right;
}

.pm-input.auto :deep(.el-input__wrapper) {
  background: var(--track-bg);
}

.pm-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  /* Reserved even when empty so every row's amount input lines up in the
     same column — the protected cash row has no rename/delete actions,
     but hiding them via visibility (not v-if) keeps their width in the
     layout instead of letting the row narrow and shift left. */
  width: 56px;
  flex-shrink: 0;
}

.pm-actions.is-hidden {
  visibility: hidden;
  pointer-events: none;
}

.expense-label-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.expense-total {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 600;
  white-space: nowrap;
}

.expense-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.expense-row > * {
  min-width: 0;
}

.expense-row .i1 {
  flex: 1.4 1.4 0;
}

.expense-row .i1 :deep(.el-autocomplete),
.expense-row .i1 :deep(.el-input) {
  width: 100%;
}

.expense-row .i2 {
  flex: 0.8 0.8 0;
}

.expense-row .i3 {
  flex: 1.6 1.6 0;
}

.expense-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.add-row-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--accent);
  cursor: pointer;
  font-weight: 600;
  transition: transform 120ms ease-out;
}

.add-row-btn:active {
  transform: scale(0.97);
}

.suggest-tag {
  display: inline-flex;
  align-items: center;
  font-size: 11.5px;
  color: var(--accent);
  background: var(--accent-light);
  padding: 4px 10px;
  border-radius: 20px;
  cursor: pointer;
  transition: transform 120ms ease-out;
}

.suggest-tag:active {
  transform: scale(0.95);
}

.suggestion-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.suggestion-meta {
  color: var(--text-tertiary);
  font-size: 12px;
}

.cash-stat {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  margin-top: 20px;
}

.cash-stat .left {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
}

.cash-stat .label {
  font-size: 13px;
}

.cash-stat .value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.cash-register-hint {
  margin: -2px 0 8px;
  color: var(--text-secondary);
  font-size: 11px;
}

.cash-register-section {
  padding: 14px 16px;
  min-width: 0;
  overflow: hidden;
}

.cash-register-section .section-title {
  margin-bottom: 8px;
}

.cash-register-layout {
  display: block;
}

.cash-register-table {
  border-top: 1px solid var(--border);
}

.cash-register-row {
  display: grid;
  grid-template-columns: 82px 84px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 34px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
  font-size: 12px;
}

.cash-register-header {
  min-height: 26px;
  color: var(--text-tertiary);
  font-size: 10px;
}

.cash-register-row > * {
  min-width: 0;
}

.cash-register-row > :last-child {
  text-align: right;
}

.cash-register-quantity {
  width: 84px;
}

.cash-register-quantity :deep(.el-input__inner) {
  text-align: right;
}

.cash-register-subtotal {
  color: var(--text-secondary);
  white-space: nowrap;
}

.cash-register-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
  margin-top: 10px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
}

.cash-register-summary-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  color: var(--text-secondary);
  font-size: 11px;
}

.cash-register-summary-row strong {
  color: var(--text-primary);
}

.cash-register-summary-row.actual strong {
  font-size: 14px;
}

.cash-register-status {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 4px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
}

.cash-register-status.is-match {
  color: var(--success, #26966f);
}

.cash-register-status.is-over {
  color: var(--warning, #b7791f);
}

.cash-register-status.is-short {
  color: var(--danger, #d14f5a);
}

.cash-register-status.is-empty {
  color: var(--text-secondary);
}

@media (max-width: 680px) {
  .cash-register-row {
    grid-template-columns: minmax(58px, 1fr) 76px minmax(60px, 1fr);
  }

  .cash-register-quantity {
    width: 76px;
  }
}

@media (max-width: 520px) {
  .expense-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 34px;
    gap: 8px;
  }

  .expense-row .i1,
  .expense-row .i2,
  .expense-row .i3 {
    grid-column: 1 / -1;
  }

  .expense-row > .no-print {
    grid-column: 2;
    grid-row: 2 / span 2;
    align-self: center;
  }
}

@media print {
  .report-section,
  .cash-stat {
    box-shadow: none;
    border: 1px solid #ccc;
  }

  .stat-tile {
    background: none;
  }

  :deep(.el-input.is-disabled .el-input__wrapper) {
    background: none;
  }
}
</style>
