<script lang="ts">
export interface ExpenseRow {
  itemName: string
  amount: number
  purpose: string
}

export interface DailyReportFormData {
  personInCharge: string
  totalRevenue: number
  totalCustomers: number
  groupCount: number
  morningRevenue: number
  morningCustomers: number
  morningGroupCount: number
  paymentAmounts: Record<string, number>
  expenses: ExpenseRow[]
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
  const afternoonRevenue = data.totalRevenue - data.morningRevenue
  const afternoonCustomers = data.totalCustomers - data.morningCustomers
  const afternoonGroupCount = data.groupCount - data.morningGroupCount
  const expenseTotal = data.expenses.reduce((sum, row) => sum + (row.amount || 0), 0)
  const nonCashSum = paymentMethods.reduce(
    (sum, m) => (m.protected ? sum : sum + (data.paymentAmounts[String(m.id)] || 0)),
    0,
  )
  const cashAmount = data.totalRevenue - nonCashSum
  const cashRemaining = cashAmount - expenseTotal
  return { afternoonRevenue, afternoonCustomers, afternoonGroupCount, expenseTotal, cashAmount, cashRemaining }
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Plus, Close, Wallet, EditPen, User, CreditCard, Tickets } from '@element-plus/icons-vue'
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
    if (!(key in data.value.paymentAmounts)) data.value.paymentAmounts[key] = 0
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
  data.value.expenses.push({ itemName: '', amount: 0, purpose: '' })
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
  const target = emptyRow ?? { itemName: '', amount: 0, purpose: '' }
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

      <section class="report-section col">
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
