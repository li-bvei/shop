<script setup lang="ts">
/**
 * Manager-side attendance: review a month, act on the days that went
 * differently from plan, decide correction requests, and export.
 *
 * The screen is built around the one job a manager actually has here —
 * "which days need me?" — so the exception filter defaults to ON and the
 * pending-request queue sits above the table. On a normal month most days
 * went to plan and need no decision; showing all 300 rows equally is what
 * makes attendance review get skipped.
 *
 * Confirming is deliberately a separate, explicit action rather than
 * something a filter or a page load does implicitly: a confirmed day is
 * what the wage engine pays on (see wages/calculation.py), so it stays a
 * decision a person makes.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Lock, Select, Unlock } from '@element-plus/icons-vue'

import {
  approveAttendanceCorrection, bulkConfirmActualWorkRecords, fetchActualWorkRecords,
  fetchAttendanceChangeLog, fetchAttendanceCorrections, lockActualWorkRecord,
  rejectAttendanceCorrection, unlockActualWorkRecord,
  type ActualWorkRecord, type AttendanceChangeLogEntry, type AttendanceCorrection,
} from '@/api/scheduling'
import { fetchAllStaff, fetchStaffByBranch, type StaffMember } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { useIsMobile } from '@/composables/useIsMobile'
import { branchDisplayName, currentMonthJst, formatMonthKanji } from '@/utils/format'
import { downloadTableExcel } from '@/utils/excelExport'
import { formatHours } from '@/utils/shiftTime'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isMobile = useIsMobile()
const { loading, run } = useDelayedLoading()

const isAdmin = computed(() => auth.role === 'admin')
const selectedBranchId = ref(auth.branchId ?? '')
const month = ref(currentMonthJst())
const employeeFilter = ref('')
/** Defaults to "only what needs attention" — see the component comment. */
const exceptionOnly = ref(true)

const records = ref<ActualWorkRecord[]>([])
const corrections = ref<AttendanceCorrection[]>([])
const staff = ref<StaffMember[]>([])
const selectedIds = ref<string[]>([])

const monthRange = computed(() => {
  const [year, m] = month.value.split('-').map(Number)
  const lastDay = new Date(Date.UTC(year ?? 1970, m ?? 1, 0)).getUTCDate()
  return { from: `${month.value}-01`, to: `${month.value}-${String(lastDay).padStart(2, '0')}` }
})

const effectiveBranchId = computed(() => (isAdmin.value ? selectedBranchId.value : (auth.branchId ?? '')))

function employeeName(id: string) {
  return staff.value.find((s) => s.id === id)?.name ?? id
}

function branchName(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

async function load() {
  await run(async () => {
    const { from, to } = monthRange.value
    const branchId = effectiveBranchId.value || undefined
    const [recordRows, correctionRows, staffRows] = await Promise.all([
      fetchActualWorkRecords({
        branchId, dateFrom: from, dateTo: to,
        employeeId: employeeFilter.value || undefined,
        exception: exceptionOnly.value ? true : undefined,
      }),
      fetchAttendanceCorrections({ branchId, status: 'pending' }),
      branchId ? fetchStaffByBranch(branchId) : fetchAllStaff(),
    ])
    records.value = recordRows
    corrections.value = correctionRows
    staff.value = staffRows
    // A selection made before a filter change can refer to rows that are
    // no longer on screen; confirming those would be an invisible action.
    selectedIds.value = selectedIds.value.filter((id) => recordRows.some((r: ActualWorkRecord) => r.id === id))
  })
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  await load()
})
watch([selectedBranchId, month, employeeFilter, exceptionOnly], load)

// --- Confirm / lock -------------------------------------------------------

const confirmable = computed(() => records.value.filter((r) => r.status === 'pending'))

async function confirmSelected() {
  const ids = selectedIds.value.length
    ? selectedIds.value
    : confirmable.value.map((r) => r.id)
  if (!ids.length) {
    ElMessage.info(t('attendance.nothingToConfirm'))
    return
  }
  await ElMessageBox.confirm(
    t('attendance.confirmPrompt', { count: ids.length }),
    t('attendance.confirmSelected'),
    { type: 'warning' },
  )
  const confirmed = await bulkConfirmActualWorkRecords(ids)
  ElMessage.success(t('attendance.confirmedCount', { count: confirmed }))
  selectedIds.value = []
  await load()
}

async function toggleLock(row: ActualWorkRecord) {
  if (row.status === 'admin_locked') {
    const { value } = await ElMessageBox.prompt(
      t('attendance.unlockReasonPrompt'), t('attendance.unlock'),
      { inputValidator: (v) => !!v?.trim() || t('attendance.unlockReasonRequired') },
    )
    await unlockActualWorkRecord(row.id, value)
  } else {
    await lockActualWorkRecord(row.id)
  }
  await load()
}

// --- Correction requests --------------------------------------------------

async function approve(correction: AttendanceCorrection) {
  await approveAttendanceCorrection(correction.id)
  ElMessage.success(t('attendance.correctionApproved'))
  await load()
}

async function reject(correction: AttendanceCorrection) {
  const { value } = await ElMessageBox.prompt(
    t('attendance.rejectReasonPrompt'), t('attendance.reject'),
    { inputValidator: (v) => !!v?.trim() || t('attendance.rejectReasonRequired') },
  )
  await rejectAttendanceCorrection(correction.id, value)
  ElMessage.success(t('attendance.correctionRejected'))
  await load()
}

// --- Change log -----------------------------------------------------------

const logVisible = ref(false)
const logEntries = ref<AttendanceChangeLogEntry[]>([])
const logTitle = ref('')

async function openLog(row: ActualWorkRecord) {
  logTitle.value = `${employeeName(row.employeeId)}　${row.workDate}`
  logEntries.value = await fetchAttendanceChangeLog({ employeeId: row.employeeId, workDate: row.workDate })
  logVisible.value = true
}

/** Only the fields that actually changed, so an entry reads as "what
 * happened" rather than as a dump of every field on the record. */
function changedFields(entry: AttendanceChangeLogEntry) {
  const before = entry.before ?? {}
  const after = entry.after ?? {}
  const keys = new Set([...Object.keys(before), ...Object.keys(after)])
  return [...keys]
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => ({
      key,
      label: t(`attendance.field.${key}`, key),
      from: before[key] ?? '—',
      to: after[key] ?? '—',
    }))
}

// --- Export ---------------------------------------------------------------

const exporting = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    const branchText = effectiveBranchId.value ? branchName(effectiveBranchId.value) : t('monthlyAnalysis.allBranches')
    await downloadTableExcel(
      `${t('nav.attendance')}-${branchText}-${month.value}`,
      t('nav.attendance'),
      [
        { header: t('scheduling.workDate'), key: 'workDate', width: 14 },
        { header: t('monthlyAnalysis.branch'), key: 'branch', width: 20 },
        { header: t('staff.name'), key: 'employee', width: 18 },
        { header: t('attendance.actualStart'), key: 'start', width: 12 },
        { header: t('attendance.actualEnd'), key: 'end', width: 12 },
        // Minutes are real numbers in the cell so the column can be
        // summed and sorted — the same rule the report exports follow.
        { header: t('attendance.breakMinutes'), key: 'breakMinutes', width: 12, numFmt: '#,##0' },
        { header: t('scheduling.plannedHours'), key: 'plannedHours', width: 12, numFmt: '0.0' },
        { header: t('scheduling.workedHours'), key: 'workedHours', width: 12, numFmt: '0.0' },
        { header: t('attendance.lateMinutes'), key: 'lateMinutes', width: 12, numFmt: '#,##0' },
        { header: t('attendance.earlyLeaveMinutes'), key: 'earlyMinutes', width: 14, numFmt: '#,##0' },
        { header: t('attendance.absent'), key: 'absent', width: 10 },
        { header: t('attendance.sourceColumn'), key: 'source', width: 14 },
        { header: t('common.status'), key: 'status', width: 16 },
        { header: t('attendance.reason'), key: 'reason', width: 30 },
      ],
      records.value.map((r) => ({
        workDate: r.workDate,
        branch: branchName(r.branchId),
        employee: employeeName(r.employeeId),
        start: r.actualStart?.slice(0, 5) ?? '',
        end: r.actualEnd?.slice(0, 5) ?? '',
        breakMinutes: r.actualBreakMinutes,
        plannedHours: r.plannedMinutes === null ? null : r.plannedMinutes / 60,
        workedHours: r.workedMinutes / 60,
        lateMinutes: r.lateMinutes,
        earlyMinutes: r.earlyLeaveMinutes,
        absent: r.absent ? '✓' : '',
        source: t(`attendance.source.${r.source}`),
        status: t(`attendance.recordStatus.${r.status}`),
        reason: r.adjustmentReason,
      })),
      'landscape',
    )
  } finally {
    exporting.value = false
  }
}

function recordStatusTagType(status: string) {
  if (status === 'admin_locked') return 'info'
  if (status === 'manager_confirmed') return 'success'
  return 'warning'
}

const periodLabel = computed(() => formatMonthKanji(month.value))
</script>

<template>
  <div class="attendance-view" v-loading="loading">
    <div class="card filter-card">
      <div class="filter-controls">
        <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" class="filter-field" />
        <el-select v-if="isAdmin" v-model="selectedBranchId" :placeholder="t('monthlyAnalysis.allBranches')" clearable class="filter-field">
          <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
        </el-select>
        <span v-else class="branch-badge">{{ branchName(auth.branchId ?? '') }}</span>
        <el-select v-model="employeeFilter" :placeholder="t('attendance.allEmployees')" clearable class="filter-field">
          <el-option v-for="s in staff" :key="s.id" :value="s.id" :label="s.name" />
        </el-select>
        <el-checkbox v-model="exceptionOnly" border class="exception-toggle">
          {{ t('attendance.exceptionsOnly') }}
        </el-checkbox>
      </div>
      <div class="filter-actions" :class="{ 'is-mobile': isMobile }">
        <el-button :icon="Select" type="primary" plain @click="confirmSelected">
          {{ isMobile ? t('attendance.confirmShort') : t('attendance.confirmSelected') }}
        </el-button>
        <el-button :icon="Download" :loading="exporting" @click="handleExport">
          {{ isMobile ? t('common.downloadExcelShort') : t('common.downloadExcel') }}
        </el-button>
      </div>
    </div>

    <!-- Pending requests sit above the table: they are the only thing here
         that another person is actively waiting on. -->
    <div v-if="corrections.length" class="card pending-card">
      <h3>{{ t('attendance.pendingCorrections', { count: corrections.length }) }}</h3>
      <div v-for="c in corrections" :key="c.id" class="correction-row">
        <div class="correction-main">
          <div class="correction-head">
            <span class="correction-name">{{ c.employeeName }}</span>
            <span class="correction-date">{{ c.workDate }}</span>
          </div>
          <div class="correction-detail">
            <template v-if="c.requestedAbsent">{{ t('attendance.requestAbsent') }}</template>
            <template v-else>{{ c.requestedStart ?? '—' }} – {{ c.requestedEnd ?? '—' }}</template>
          </div>
          <div class="correction-reason">{{ c.reason }}</div>
        </div>
        <div class="correction-actions">
          <el-button size="small" type="success" plain @click="approve(c)">{{ t('attendance.approve') }}</el-button>
          <el-button size="small" type="danger" plain @click="reject(c)">{{ t('attendance.reject') }}</el-button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <h3>{{ periodLabel }}　{{ t('nav.attendance') }}</h3>
        <span class="row-count">{{ t('attendance.rowCount', { count: records.length }) }}</span>
      </div>
      <p class="section-hint">{{ t('attendance.managerHint') }}</p>

      <el-table
        :data="records" class="desktop-table" :empty-text="t('attendance.noRecords')"
        @selection-change="(rows: ActualWorkRecord[]) => selectedIds = rows.map((r) => r.id)"
      >
        <el-table-column type="selection" width="44" :selectable="(row: ActualWorkRecord) => row.status === 'pending'" />
        <el-table-column :label="t('scheduling.workDate')" prop="workDate" width="112" />
        <el-table-column :label="t('staff.name')" min-width="120">
          <template #default="{ row }">{{ employeeName(row.employeeId) }}</template>
        </el-table-column>
        <el-table-column :label="t('attendance.planned')" width="150">
          <template #default="{ row }">
            <span v-if="row.plannedStart">{{ row.plannedStart.slice(0, 5) }}–{{ row.plannedEnd?.slice(0, 5) }}</span>
            <span v-else class="muted">—</span>
            <span v-if="row.plannedMinutes !== null" class="hours">{{ formatHours(row.plannedMinutes) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('attendance.actual')" width="150">
          <template #default="{ row }">
            <span v-if="row.actualStart">{{ row.actualStart.slice(0, 5) }}–{{ row.actualEnd?.slice(0, 5) ?? '?' }}</span>
            <span v-else class="muted">—</span>
            <span v-if="row.actualEnd" class="hours">{{ formatHours(row.workedMinutes) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('attendance.deviation')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.absent" class="deviation absent">{{ t('attendance.absent') }}</span>
            <template v-else>
              <span v-if="row.lateMinutes" class="deviation late">{{ t('attendance.lateBy', { minutes: row.lateMinutes }) }}</span>
              <span v-if="row.earlyLeaveMinutes" class="deviation early">{{ t('attendance.earlyBy', { minutes: row.earlyLeaveMinutes }) }}</span>
              <span v-if="!row.actualEnd" class="deviation late">{{ t('attendance.missingClockOut') }}</span>
              <span v-if="!row.lateMinutes && !row.earlyLeaveMinutes && row.actualEnd" class="muted">—</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column :label="t('attendance.sourceColumn')" width="110">
          <template #default="{ row }">
            <span class="source-chip" :class="`source-${row.source}`">{{ t(`attendance.source.${row.source}`) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="128">
          <template #default="{ row }">
            <el-tag size="small" :type="recordStatusTagType(row.status)">
              {{ t(`attendance.recordStatus.${row.status}`) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column width="170">
          <template #default="{ row }">
            <el-button link type="primary" @click="openLog(row)">{{ t('attendance.history') }}</el-button>
            <el-button
              v-if="isAdmin" link :icon="row.status === 'admin_locked' ? Unlock : Lock"
              @click="toggleLock(row)"
            >
              {{ row.status === 'admin_locked' ? t('attendance.unlock') : t('attendance.lock') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="row in records" :key="row.id" class="record-card">
          <div class="record-card-head">
            <span class="record-name">{{ employeeName(row.employeeId) }}</span>
            <el-tag size="small" :type="recordStatusTagType(row.status)">
              {{ t(`attendance.recordStatus.${row.status}`) }}
            </el-tag>
          </div>
          <div class="record-card-row">
            <span>{{ t('scheduling.workDate') }}</span><span>{{ row.workDate }}</span>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.planned') }}</span>
            <span>
              {{ row.plannedStart ? `${row.plannedStart.slice(0, 5)}–${row.plannedEnd?.slice(0, 5)}` : '—' }}
              <span v-if="row.plannedMinutes !== null" class="hours">{{ formatHours(row.plannedMinutes) }}</span>
            </span>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.actual') }}</span>
            <span>
              {{ row.actualStart ? `${row.actualStart.slice(0, 5)}–${row.actualEnd?.slice(0, 5) ?? '?'}` : '—' }}
              <span v-if="row.actualEnd" class="hours">{{ formatHours(row.workedMinutes) }}</span>
            </span>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.deviation') }}</span>
            <span>
              <span v-if="row.absent" class="deviation absent">{{ t('attendance.absent') }}</span>
              <span v-else-if="row.lateMinutes || row.earlyLeaveMinutes">
                <span v-if="row.lateMinutes" class="deviation late">{{ t('attendance.lateBy', { minutes: row.lateMinutes }) }}</span>
                <span v-if="row.earlyLeaveMinutes" class="deviation early">{{ t('attendance.earlyBy', { minutes: row.earlyLeaveMinutes }) }}</span>
              </span>
              <span v-else class="muted">—</span>
            </span>
          </div>
          <div class="record-card-actions">
            <el-button link type="primary" @click="openLog(row)">{{ t('attendance.history') }}</el-button>
            <el-button v-if="isAdmin" link @click="toggleLock(row)">
              {{ row.status === 'admin_locked' ? t('attendance.unlock') : t('attendance.lock') }}
            </el-button>
          </div>
        </div>
        <p v-if="!records.length" class="empty-hint">{{ t('attendance.noRecords') }}</p>
      </div>
    </div>

    <el-dialog v-model="logVisible" :title="`${t('attendance.history')}　${logTitle}`" class="log-dialog">
      <div v-for="entry in logEntries" :key="entry.id" class="log-entry">
        <div class="log-head">
          <span class="log-source">{{ t(`attendance.changeSource.${entry.source}`) }}</span>
          <span class="log-meta">{{ entry.changedByName || t('attendance.systemActor') }}　{{ new Date(entry.changedAt).toLocaleString() }}</span>
        </div>
        <div v-for="change in changedFields(entry)" :key="change.key" class="log-change">
          <span class="log-field">{{ change.label }}</span>
          <span class="log-from">{{ change.from }}</span>
          <span class="log-arrow">→</span>
          <span class="log-to">{{ change.to }}</span>
        </div>
        <div v-if="entry.reason" class="log-reason">{{ entry.reason }}</div>
      </div>
      <p v-if="!logEntries.length" class="empty-hint">{{ t('attendance.noHistory') }}</p>
    </el-dialog>
  </div>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.card h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.filter-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.filter-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.filter-field {
  width: 170px;
}

.filter-actions {
  display: flex;
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

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.row-count,
.section-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.section-hint {
  margin: 0 0 14px;
}

.pending-card {
  border-left: 3px solid var(--warning, #e6a23c);
}

.correction-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.correction-row:last-child {
  border-bottom: none;
}

.correction-main {
  flex: 1;
  min-width: 0;
}

.correction-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.correction-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.correction-date,
.correction-detail {
  font-size: 13px;
  color: var(--text-secondary);
}

/* Free text an employee wrote — shown in full, wrapped, never ellipsised. */
.correction-reason {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.correction-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.hours {
  margin-left: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.deviation {
  font-size: 12.5px;
  margin-right: 8px;
}

.deviation.late,
.deviation.absent {
  color: var(--danger);
  font-weight: 600;
}

.deviation.early {
  color: var(--warning, #e6a23c);
  font-weight: 600;
}

.muted {
  color: var(--text-tertiary);
}

.source-chip {
  font-size: 11.5px;
  border-radius: 999px;
  padding: 2px 8px;
  background: var(--surface-alt);
  color: var(--text-secondary);
  white-space: nowrap;
}

.source-chip.source-punch {
  color: var(--accent);
}

.empty-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
}

.log-entry {
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.log-entry:last-child {
  border-bottom: none;
}

.log-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.log-source {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.log-meta,
.log-reason {
  font-size: 12px;
  color: var(--text-tertiary);
}

.log-change {
  display: flex;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}

.log-field {
  min-width: 110px;
  color: var(--text-tertiary);
}

.log-to {
  font-weight: 600;
  color: var(--text-primary);
}

.mobile-cards {
  display: none;
}

.record-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
}

.record-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.record-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.record-card-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 13.5px;
  color: var(--text-secondary);
  padding: 2px 0;
}

.record-card-row span:last-child {
  color: var(--text-primary);
  text-align: right;
}

.record-card-actions {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}

@media (max-width: 768px) {
  .card {
    padding: 16px 14px;
  }

  .desktop-table {
    display: none;
  }

  .mobile-cards {
    display: block;
  }

  .filter-controls {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  .filter-field,
  .exception-toggle,
  .branch-badge {
    width: 100%;
    min-width: 0;
  }

  .exception-toggle {
    height: 40px;
    margin-right: 0;
  }

  .filter-actions.is-mobile {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  .filter-actions.is-mobile :deep(.el-button) {
    width: 100%;
    min-width: 0;
    height: 44px;
    margin-left: 0;
  }

  .correction-row {
    flex-direction: column;
  }

  .correction-actions {
    width: 100%;
  }

  .correction-actions :deep(.el-button) {
    flex: 1;
    height: 40px;
  }
}
</style>
