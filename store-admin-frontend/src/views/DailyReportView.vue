<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Clock, Printer, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { usePrintFit } from '@/composables/usePrintFit'
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
import { fetchCashRegisterDefaults } from '@/api/cashRegisterDefaults'
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
import {
  saveDraft, getDraft, clearDraft, listDrafts, isNetworkFailure, type DailyReportDraft,
} from '@/utils/dailyReportDraft'

const { t, locale } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const staffList = ref<StaffMember[]>([])
const paymentMethods = ref<PaymentMethodDef[]>([])
const cashRegisterExpectedTotal = ref(CASH_REGISTER_EXPECTED_TOTAL)
const cashRegisterDenominationDefaults = ref<Record<string, number>>({})
const branchId = ref(auth.branchId ?? 'shinsaibashi')
const reportDate = ref(todayJst())
const reportId = ref<number | null>(null)
const submitting = ref(false)

const reportForm = reactive<DailyReportFormData>(normalizeDailyReportFormData({}))
// The report's server-side updated_at as of the last successful load/save —
// compared against the live server value at sync time to tell whether
// someone else saved a newer version while this device was offline.
const reportUpdatedAt = ref<string | null>(null)
// Whether the form currently on screen came from an unsynced local draft
// rather than the server (see loadReport) — shown so the user knows this
// day still needs to reach the server.
const viewingUnsyncedDraft = ref(false)
const pendingDrafts = ref<DailyReportDraft[]>([])
const syncingDrafts = ref(false)

function refreshPendingDrafts() {
  pendingDrafts.value = listDrafts()
}

const printRoot = ref<HTMLElement>()
const { fitAndPrint } = usePrintFit(printRoot, { marginMm: 10 })

async function handlePrint() {
  const originalTitle = document.title
  document.title = exportFileName.value
  await fitAndPrint()
  document.title = originalTitle
}

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
  const [staff, methods, seed, cashRegisterDefaults] = await Promise.all([
    fetchStaffByBranch(branchId.value),
    fetchPaymentMethods(branchId.value),
    fetchDailyReport(branchId.value, reportDate.value),
    fetchCashRegisterDefaults(branchId.value),
  ])

  staffList.value = staff
  paymentMethods.value = methods
  // Only used for the Excel export — DailyReportForm.vue fetches and owns
  // its own copy for the on-screen comparison/editing.
  cashRegisterExpectedTotal.value = cashRegisterDefaults.expectedTotal
  cashRegisterDenominationDefaults.value = cashRegisterDefaults.denominationDefaults

  reportId.value = seed.id
  reportUpdatedAt.value = seed.updatedAt

  // An unsynced local draft for this exact branch+date wins over whatever
  // the server just returned — that server copy predates the offline edit
  // (or the report doesn't exist there yet), so showing it instead would
  // make the user think their earlier work was lost.
  const draft = getDraft(branchId.value, reportDate.value)
  viewingUnsyncedDraft.value = !!draft
  const source = draft ? draft.data : seed

  reportForm.personInCharge = source.personInCharge
  reportForm.totalRevenue = source.totalRevenue
  reportForm.totalCustomers = source.totalCustomers
  reportForm.groupCount = source.groupCount
  reportForm.morningRevenue = source.morningRevenue
  reportForm.morningCustomers = source.morningCustomers
  reportForm.morningGroupCount = source.morningGroupCount
  reportForm.paymentAmounts = { ...source.paymentAmounts }
  reportForm.expenses = source.expenses.map((e) => ({ ...e }))
  reportForm.cashRegisterCounts = { ...source.cashRegisterCounts }
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
  refreshPendingDrafts()
  // Best-effort: try once at page load (in case connectivity came back while
  // the tab was closed) and again whenever the browser reports the network
  // coming back up. Both are silent unless there's actually a conflict to
  // ask the user about — see syncAllDrafts.
  void syncAllDrafts()
  window.addEventListener('online', syncAllDrafts)
})

onBeforeUnmount(() => {
  window.removeEventListener('online', syncAllDrafts)
})

watch([branchId, reportDate], () => {
  loadReport()
})

async function handleSubmit() {
  submitting.value = true
  try {
    const derived = computeDerived(reportForm, paymentMethods.value)
    const snapshot = JSON.parse(JSON.stringify(reportForm))
    try {
      reportId.value = await saveDailyReport(reportId.value, branchId.value, reportDate.value, snapshot)
      await saveDailyReportHistorySnapshot({
        branchId: branchId.value,
        date: reportDate.value,
        cashRemaining: derived.cashRemaining,
        data: snapshot,
      })
      clearDraft(branchId.value, reportDate.value)
      refreshPendingDrafts()
      viewingUnsyncedDraft.value = false
      const fresh = await fetchDailyReport(branchId.value, reportDate.value)
      reportUpdatedAt.value = fresh.updatedAt
      ElMessage.success(t('dailyReport.savedSuccess'))
    } catch (err) {
      if (!isNetworkFailure(err)) throw err
      // Offline (or the server is unreachable) — keep the entry instead of
      // losing it. `reportUpdatedAt` is the last version we know the server
      // actually has, so syncAllDrafts can tell later whether someone else
      // also saved this day while we were offline.
      saveDraft({
        branchId: branchId.value, date: reportDate.value, data: snapshot,
        baseUpdatedAt: reportUpdatedAt.value, savedLocallyAt: new Date().toISOString(),
      })
      refreshPendingDrafts()
      viewingUnsyncedDraft.value = true
      ElMessage({ type: 'warning', message: t('dailyReport.savedLocallyOffline'), duration: 5000 })
    }
  } finally {
    submitting.value = false
  }
}

/** Pushes one offline draft to the server. Returns whether it synced clean,
 * hit a conflict (the server has a newer save than the draft was based on),
 * or simply failed again (still offline) — the last two both leave the
 * draft in place for a later retry. A real validation error (not a network
 * failure) is left to propagate — silently discarding a draft over that
 * would lose real data instead of protecting it. */
async function syncOneDraft(draft: DailyReportDraft): Promise<'synced' | 'conflict' | 'still-offline'> {
  const current = await fetchDailyReport(draft.branchId, draft.date)
  if (draft.baseUpdatedAt && current.updatedAt && current.updatedAt !== draft.baseUpdatedAt) {
    return 'conflict'
  }
  const methods = await fetchPaymentMethods(draft.branchId)
  const derived = computeDerived(draft.data, methods)
  await saveDailyReport(current.id, draft.branchId, draft.date, draft.data)
  await saveDailyReportHistorySnapshot({
    branchId: draft.branchId, date: draft.date, cashRemaining: derived.cashRemaining, data: draft.data,
  })
  clearDraft(draft.branchId, draft.date)
  return 'synced'
}

async function syncAllDrafts() {
  if (syncingDrafts.value) return
  syncingDrafts.value = true
  try {
    const drafts = listDrafts()
    let syncedAny = false
    for (const draft of drafts) {
      let outcome: 'synced' | 'conflict' | 'still-offline'
      try {
        outcome = await syncOneDraft(draft)
      } catch (err) {
        if (!isNetworkFailure(err)) throw err
        outcome = 'still-offline'
      }
      if (outcome === 'synced') syncedAny = true
      else if (outcome === 'conflict') await resolveDraftConflict(draft)
    }
    refreshPendingDrafts()
    if (syncedAny) {
      ElMessage.success(t('dailyReport.draftSyncSuccess'))
      if (!getDraft(branchId.value, reportDate.value)) await loadReport()
    }
  } finally {
    syncingDrafts.value = false
  }
}

/** The server has a save newer than what this draft was based on — ask
 * which one should win rather than guessing. "Use local" force-pushes the
 * draft over it; "use server" just discards the draft. Leaving the dialog
 * without choosing (Escape/backdrop) keeps the draft pending — it'll be
 * asked about again on the next sync attempt, nothing is lost either way. */
async function resolveDraftConflict(draft: DailyReportDraft) {
  try {
    await ElMessageBox.confirm(
      t('dailyReport.draftConflictMessage', { date: draft.date }),
      t('dailyReport.draftConflictTitle'),
      {
        type: 'warning',
        confirmButtonText: t('dailyReport.draftConflictUseLocal'),
        cancelButtonText: t('dailyReport.draftConflictUseServer'),
        distinguishCancelAndClose: true,
      },
    )
    const current = await fetchDailyReport(draft.branchId, draft.date)
    const methods = await fetchPaymentMethods(draft.branchId)
    const derived = computeDerived(draft.data, methods)
    await saveDailyReport(current.id, draft.branchId, draft.date, draft.data)
    await saveDailyReportHistorySnapshot({
      branchId: draft.branchId, date: draft.date, cashRemaining: derived.cashRemaining, data: draft.data,
    })
    clearDraft(draft.branchId, draft.date)
  } catch (action) {
    if (action === 'cancel') clearDraft(draft.branchId, draft.date)
    // 'close' (Escape/backdrop): leave the draft pending, decide next time.
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
      const rawQuantity = reportForm.cashRegisterCounts[String(denomination)]
      const defaultQuantity = rawQuantity != null ? (cashRegisterDenominationDefaults.value[String(denomination)] ?? 0) : 0
      ws.addRow([denomination, rawQuantity ?? 0, denomination * ((rawQuantity ?? 0) + defaultQuantity)])
    }
    const cashRegisterTotal = computeCashRegisterTotal(reportForm.cashRegisterCounts, cashRegisterDenominationDefaults.value)
    ws.addRow([t('dailyReport.cashRegisterExpected'), cashRegisterExpectedTotal.value])
    ws.addRow([t('dailyReport.cashRegisterActual'), cashRegisterTotal])
    ws.addRow([t('dailyReport.cashRegisterDifference'), cashRegisterTotal - cashRegisterExpectedTotal.value])
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
        <div class="no-print form-header-actions">
          <el-button :icon="Printer" @click="handlePrint">{{ t('common.print') }}</el-button>
          <el-button :icon="Download" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
        </div>
      </div>

      <div v-if="pendingDrafts.length" class="no-print draft-banner">
        <el-icon><WarningFilled /></el-icon>
        <span>
          {{ viewingUnsyncedDraft ? t('dailyReport.viewingUnsyncedDraft') : '' }}
          {{ t('dailyReport.pendingDraftsCount', { count: pendingDrafts.length }) }}
        </span>
        <el-button size="small" :icon="Refresh" :loading="syncingDrafts" @click="syncAllDrafts">
          {{ t('dailyReport.syncNow') }}
        </el-button>
      </div>

      <div ref="printRoot">
        <DailyReportForm v-model:data="reportForm" :branch-id="branchId" allow-cash-register-default-edits />
      </div>

      <div class="submit-row no-print">
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

.form-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.draft-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--warning-light, #fdf3e2);
  border: 1px solid var(--warning, #b7791f);
  color: var(--warning, #b7791f);
  border-radius: var(--radius-sm);
  padding: 8px 14px;
  margin-bottom: 16px;
  font-size: 12.5px;
}

.draft-banner span {
  flex: 1;
}

@media print {
  @page {
    size: A4 portrait;
    margin: 10mm;
  }
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
