<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Clock } from '@element-plus/icons-vue'
import { fetchPaymentMethods, type PaymentMethodDef } from '@/api/masterData'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import {
  fetchDailyReport,
  saveDailyReport,
  saveDailyReportHistorySnapshot,
  fetchDailyReportHistory,
  type DailyReportHistoryEntry,
} from '@/api/dailyReport'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import DailyReportForm, {
  CASH_REGISTER_DENOMINATIONS,
  CASH_REGISTER_EXPECTED_TOTAL,
  computeCashRegisterTotal,
  computeDerived,
  normalizeDailyReportFormData,
  type DailyReportFormData,
} from '@/components/DailyReportForm.vue'
import { formatCurrency, branchDisplayName, todayJst } from '@/utils/format'
import { downloadCustomExcel } from '@/utils/excelExport'

const { t, locale } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const staffList = ref<StaffMember[]>([])
const paymentMethods = ref<PaymentMethodDef[]>([])
const branchId = ref(auth.branchId ?? 'shinsaibashi')
const reportDate = ref(todayJst())
const reportId = ref<number | null>(null)
const submitting = ref(false)

const reportForm = reactive<DailyReportFormData>(normalizeDailyReportFormData({}))

const historyDialogVisible = ref(false)
const historyLoading = ref(false)
const historyEntries = ref<DailyReportHistoryEntry[]>([])
// Browsing history by business date (independent of whatever date the main
// form happens to have loaded) — otherwise a day edited many times just
// shows as an undifferentiated pile of timestamps with no way to jump to
// a different date without leaving the dialog.
const historyFilterDate = ref('')
const historyEditDialogVisible = ref(false)
const historyEditSubmitting = ref(false)
const historyEditForm = ref<DailyReportFormData | null>(null)
const historyEditDate = ref('')

function staffName(id: string) {
  return staffList.value.find((s) => s.id === id)?.name ?? id
}

function branchLabel(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

function formatDateTime(iso: string) {
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function loadReport() {
  const [staff, methods, seed] = await Promise.all([
    fetchStaffByBranch(branchId.value),
    fetchPaymentMethods(branchId.value),
    fetchDailyReport(branchId.value, reportDate.value),
  ])

  staffList.value = staff
  paymentMethods.value = methods

  reportId.value = seed.id
  reportForm.personInCharge = seed.personInCharge
  reportForm.totalRevenue = seed.totalRevenue
  reportForm.totalCustomers = seed.totalCustomers
  reportForm.groupCount = seed.groupCount
  reportForm.morningRevenue = seed.morningRevenue
  reportForm.morningCustomers = seed.morningCustomers
  reportForm.morningGroupCount = seed.morningGroupCount
  reportForm.paymentAmounts = { ...seed.paymentAmounts }
  reportForm.expenses = seed.expenses.map((e) => ({ ...e }))
  reportForm.cashRegisterCounts = { ...seed.cashRegisterCounts }
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  if (!isAdmin.value) {
    branchId.value = auth.branchId ?? branchId.value
  } else if (typeof route.query.branch === 'string' && route.query.branch) {
    branchId.value = route.query.branch
  }
  if (typeof route.query.date === 'string' && route.query.date) {
    reportDate.value = route.query.date
  }
  await loadReport()
})

watch([branchId, reportDate], () => {
  loadReport()
})

async function handleSubmit() {
  submitting.value = true
  try {
    const derived = computeDerived(reportForm, paymentMethods.value)
    const snapshot = JSON.parse(JSON.stringify(reportForm))
    reportId.value = await saveDailyReport(reportId.value, branchId.value, reportDate.value, snapshot)
    await saveDailyReportHistorySnapshot({
      branchId: branchId.value,
      date: reportDate.value,
      cashRemaining: derived.cashRemaining,
      data: snapshot,
    })
    ElMessage.success(t('dailyReport.savedSuccess'))
  } finally {
    submitting.value = false
  }
}

async function refreshHistoryList() {
  historyLoading.value = true
  try {
    historyEntries.value = await fetchDailyReportHistory(branchId.value, historyFilterDate.value)
  } finally {
    historyLoading.value = false
  }
}

async function openHistory() {
  historyFilterDate.value = reportDate.value
  historyDialogVisible.value = true
  await refreshHistoryList()
}

watch(historyFilterDate, () => {
  if (historyDialogVisible.value) refreshHistoryList()
})

function openHistoryEdit(entry: DailyReportHistoryEntry) {
  historyEditForm.value = JSON.parse(JSON.stringify(entry.data)) as DailyReportFormData
  historyEditDate.value = entry.date
  historyEditDialogVisible.value = true
}

async function handleSaveHistoryEdit() {
  if (!historyEditForm.value) return
  historyEditSubmitting.value = true
  try {
    const derived = computeDerived(historyEditForm.value, paymentMethods.value)
    const snapshot = JSON.parse(JSON.stringify(historyEditForm.value))
    // Always the snapshot's own business date — historyFilterDate can
    // differ from the main form's reportDate, and saving under the wrong
    // one would silently file the edit under the wrong day. Re-fetch to
    // find whether a live report already exists for that date so we
    // update it instead of violating the branch+date unique constraint.
    const existing = await fetchDailyReport(branchId.value, historyEditDate.value)
    const savedId = await saveDailyReport(existing.id, branchId.value, historyEditDate.value, snapshot)
    if (historyEditDate.value === reportDate.value) reportId.value = savedId
    await saveDailyReportHistorySnapshot({
      branchId: branchId.value,
      date: historyEditDate.value,
      cashRemaining: derived.cashRemaining,
      data: snapshot,
    })
    ElMessage.success(t('dailyReport.savedSuccess'))
    historyEditDialogVisible.value = false
    await refreshHistoryList()
    if (historyEditDate.value === reportDate.value) await loadReport()
  } finally {
    historyEditSubmitting.value = false
  }
}

// e.g. "心斋桥-20260816-日报表" — trailing 店/店 dropped per the naming
// convention asked for, so it reads as a short branch name, not "XX店店".
const exportFileName = computed(() => {
  const branch = branchStore.list.find((b) => b.id === branchId.value)
  const shortName = branchDisplayName(branch, locale.value, branchId.value).replace(/店$/, '')
  const compactDate = reportDate.value.replace(/-/g, '')
  return `${shortName}-${compactDate}-${t('dailyReport.exportFileSuffix')}`
})

function paymentMethodLabel(method: PaymentMethodDef) {
  return method.customName || (method.i18nKey ? t(method.i18nKey) : '')
}

function paymentMethodAmount(method: PaymentMethodDef, derived: ReturnType<typeof computeDerived>) {
  return method.protected ? derived.cashAmount : (reportForm.paymentAmounts[String(method.id)] ?? 0)
}

async function handleDownload() {
  const derived = computeDerived(reportForm, paymentMethods.value)
  await downloadCustomExcel(exportFileName.value, t('dailyReport.pageTitle'), (ws) => {
    ws.addRow([branchLabel(branchId.value), reportDate.value, t('dailyReport.personInCharge'), staffName(reportForm.personInCharge)])
    ws.getRow(1).font = { bold: true }
    ws.addRow([])

    ws.addRow([t('dailyReport.totalRevenue'), t('dailyReport.totalCustomers'), t('dailyReport.groupCount')]).font = { bold: true }
    ws.addRow([reportForm.totalRevenue, reportForm.totalCustomers, reportForm.groupCount])
    ws.addRow([t('dailyReport.morningRevenue'), t('dailyReport.morningCustomers'), t('dailyReport.morningGroupCount')]).font = { bold: true }
    ws.addRow([reportForm.morningRevenue, reportForm.morningCustomers, reportForm.morningGroupCount])
    ws.addRow([t('dailyReport.afternoonRevenueAuto'), t('dailyReport.afternoonCustomersAuto'), t('dailyReport.afternoonGroupCountAuto')]).font = { bold: true }
    ws.addRow([derived.afternoonRevenue, derived.afternoonCustomers, derived.afternoonGroupCount])
    ws.addRow([])

    ws.addRow([t('dailyReport.paymentMethodsTitle')]).font = { bold: true }
    for (const method of paymentMethods.value) {
      ws.addRow([paymentMethodLabel(method), paymentMethodAmount(method, derived)])
    }
    ws.addRow([])

    ws.addRow([t('dailyReport.expenseTitle'), null, null, `${t('dailyReport.expenseTotal')} ${derived.expenseTotal}`]).font = { bold: true }
    for (const expense of reportForm.expenses) {
      ws.addRow([expense.itemName, expense.amount, expense.purpose])
    }
    ws.addRow([])

    ws.addRow([t('dailyReport.cashRemaining'), derived.cashRemaining]).font = { bold: true }
    ws.addRow([])
    ws.addRow([t('dailyReport.cashRegisterTitle')]).font = { bold: true }
    ws.addRow([
      t('dailyReport.cashRegisterDenomination'),
      t('dailyReport.cashRegisterQuantity'),
      t('dailyReport.cashRegisterSubtotal'),
    ]).font = { bold: true }
    for (const denomination of CASH_REGISTER_DENOMINATIONS) {
      const quantity = reportForm.cashRegisterCounts[String(denomination)] ?? 0
      ws.addRow([denomination, quantity, denomination * quantity])
    }
    const cashRegisterTotal = computeCashRegisterTotal(reportForm.cashRegisterCounts)
    ws.addRow([t('dailyReport.cashRegisterExpected'), CASH_REGISTER_EXPECTED_TOTAL])
    ws.addRow([t('dailyReport.cashRegisterActual'), cashRegisterTotal])
    ws.addRow([t('dailyReport.cashRegisterDifference'), cashRegisterTotal - CASH_REGISTER_EXPECTED_TOTAL])
    ws.columns.forEach((col) => { col.width = 18 })
  })
}
</script>

<template>
  <div class="daily-report-view">
    <div class="card form-card">
      <div class="form-header">
        <div class="form-header-controls">
          <el-date-picker v-model="reportDate" type="date" size="default" :clearable="false" value-format="YYYY-MM-DD" />
          <el-select v-if="isAdmin" v-model="branchId" size="default" style="width: 140px">
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
          <span v-else class="branch-badge">{{ branchLabel(branchId) }}</span>
        </div>
        <el-button :icon="Download" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
      </div>

      <DailyReportForm v-model:data="reportForm" :branch-id="branchId" />

      <div class="submit-row">
        <el-button :icon="Clock" @click="openHistory">{{ t('dailyReport.viewHistory') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">{{ t('dailyReport.submit') }}</el-button>
      </div>
    </div>

    <el-dialog v-model="historyDialogVisible" :title="t('dailyReport.historyTitle')" width="640px">
      <div class="history-filter">
        <el-date-picker v-model="historyFilterDate" type="date" :clearable="false" value-format="YYYY-MM-DD" />
        <span class="history-count-hint" :class="{ 'is-empty': !historyEntries.length }">
          {{
            historyEntries.length
              ? t('dailyReport.historyCountHint', { date: historyFilterDate, count: historyEntries.length })
              : t('dailyReport.historyCountEmpty', { date: historyFilterDate })
          }}
        </span>
      </div>
      <el-table
        :data="historyEntries"
        v-loading="historyLoading"
        :empty-text="t('dailyReport.historyEmpty')"
        class="history-table"
        @row-click="openHistoryEdit"
      >
        <el-table-column :label="t('dailyReport.historySavedAt')" min-width="150">
          <template #default="{ row }">{{ formatDateTime(row.savedAt) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.historyEditedBy')" width="100">
          <template #default="{ row }">{{ row.editedBy }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.personInCharge')" width="100">
          <template #default="{ row }">{{ staffName(row.personInCharge) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.totalRevenue')" width="110">
          <template #default="{ row }">{{ formatCurrency(row.totalRevenue) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.cashRemaining')" min-width="110">
          <template #default="{ row }">{{ formatCurrency(row.cashRemaining) }}</template>
        </el-table-column>
      </el-table>
      <p v-if="historyEntries.length" class="history-hint">{{ t('dailyReport.historyRowHint') }}</p>
    </el-dialog>

    <el-dialog
      v-model="historyEditDialogVisible"
      :title="t('dailyReport.editHistoryTitle')"
      width="960px"
      class="history-edit-dialog"
      append-to-body
    >
      <DailyReportForm v-if="historyEditForm" v-model:data="historyEditForm" :branch-id="branchId" />
      <template #footer>
        <el-button @click="historyEditDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="historyEditSubmitting" @click="handleSaveHistoryEdit">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<style scoped>
.daily-report-view {
  display: flex;
}

.form-card {
  width: 100%;
  max-width: 960px;
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
}

.form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.form-header-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.branch-badge {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 14px;
  height: 32px;
  display: inline-flex;
  align-items: center;
}

.submit-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.history-table :deep(.el-table__row) {
  cursor: pointer;
}

.history-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 10px 2px 0;
}

.history-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.history-count-hint {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}

.history-count-hint.is-empty {
  font-weight: 400;
  color: var(--text-tertiary);
}

</style>
