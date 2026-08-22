<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Printer, Download } from '@element-plus/icons-vue'
import {
  fetchSchedulePeriods,
  createSchedulePeriod,
  publishSchedulePeriod,
  generateActualRecords,
  fetchShifts,
  createShift,
  updateShift,
  deleteShift,
  ShiftOverrideRequiredError,
  fetchAvailabilityRequests,
  fetchBranchScheduleSetting,
  fetchActualWorkRecords,
  updateActualWorkRecord,
  deleteActualWorkRecord,
  bulkConfirmActualWorkRecords,
  lockActualWorkRecord,
  unlockActualWorkRecord,
  type SchedulePeriod,
  type ShiftRecord,
  type AvailabilityRequestRecord,
  type BranchScheduleSetting,
  type ActualWorkRecord,
} from '@/api/scheduling'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName, currentMonthJst } from '@/utils/format'
import { reconcileScheduleSave, type ScheduleSaveOutcome } from '@/utils/scheduleSaveResults'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { usePrintFit } from '@/composables/usePrintFit'
import { downloadTableExcel } from '@/utils/excelExport'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const activeBranchId = ref(auth.branchId ?? '')
const activeTab = ref('grid')
const staffList = ref<StaffMember[]>([])

function branchLabel(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

function employeeName(id: string) {
  return staffList.value.find((s) => s.id === id)?.name ?? id
}

async function loadStaff() {
  if (!activeBranchId.value) return
  staffList.value = await fetchStaffByBranch(activeBranchId.value)
}

async function handleGenerateActualRecords(period: SchedulePeriod) {
  const result = await generateActualRecords(period.id)
  ElMessage.success(t('scheduling.generateActualRecordsResult', { created: result.created, total: result.totalShifts }))
  await loadActualRecords()
}

// ---- Monthly grid ----------------------------------------------------------

type CellState = 'off' | 'morning' | 'afternoon' | 'full_day' | 'custom'
interface GridCell {
  state: CellState
  shiftId: string | null
  dirty: boolean
}
interface GridDay {
  date: string
  day: number
  weekdayIdx: number
}

const cycleOrder: CellState[] = ['off', 'morning', 'afternoon', 'full_day']

const gridMonth = ref(currentMonthJst())
const { loading: gridLoading, run: runGridLoad } = useDelayedLoading()
const gridSaving = ref(false)
const gridPeriod = ref<SchedulePeriod | null>(null)
const gridDays = ref<GridDay[]>([])
const gridAvailability = ref<AvailabilityRequestRecord[]>([])
const scheduleSetting = ref<BranchScheduleSetting | null>(null)
const grid = reactive<Record<string, Record<string, GridCell>>>({})
const weekdayShortNames = computed(() => t('common.weekdayShort').split(','))

function monthFirstDay(monthStr: string) {
  return `${monthStr}-01`
}

function monthLastDay(monthStr: string) {
  const [y, m] = parseYearMonth(monthStr)
  return `${monthStr}-${String(new Date(y, m, 0).getDate()).padStart(2, '0')}`
}

function parseYearMonth(monthStr: string): [number, number] {
  const parts = monthStr.split('-')
  return [Number(parts[0]), Number(parts[1])]
}

function shiftMonth(monthStr: string, delta: number): string {
  const [y, m] = parseYearMonth(monthStr)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function buildDays(monthStr: string): GridDay[] {
  const [y, m] = parseYearMonth(monthStr)
  const count = new Date(y, m, 0).getDate()
  const result: GridDay[] = []
  for (let day = 1; day <= count; day++) {
    const date = new Date(y, m - 1, day)
    result.push({
      date: `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      day, weekdayIdx: date.getDay(),
    })
  }
  return result
}

function classifyShift(shift: ShiftRecord, setting: BranchScheduleSetting): CellState {
  const start = shift.plannedStart.slice(0, 5)
  const end = shift.plannedEnd.slice(0, 5)
  if (start === setting.morningStart && end === setting.morningEnd) return 'morning'
  if (start === setting.afternoonStart && end === setting.afternoonEnd) return 'afternoon'
  if (start === setting.fullDayStart && end === setting.fullDayEnd) return 'full_day'
  return 'custom'
}

function minutesBetween(a: string, b: string) {
  const aParts = a.split(':')
  const bParts = b.split(':')
  const ah = Number(aParts[0]); const am = Number(aParts[1])
  const bh = Number(bParts[0]); const bm = Number(bParts[1])
  return (bh * 60 + bm) - (ah * 60 + am)
}

function stateToTimes(state: 'morning' | 'afternoon' | 'full_day', setting: BranchScheduleSetting) {
  if (state === 'morning') return { start: setting.morningStart, end: setting.morningEnd, breakMinutes: 0 }
  if (state === 'afternoon') return { start: setting.afternoonStart, end: setting.afternoonEnd, breakMinutes: 0 }
  return {
    start: setting.fullDayStart, end: setting.fullDayEnd,
    breakMinutes: minutesBetween(setting.fullDayBreakStart, setting.fullDayBreakEnd),
  }
}

let suppressMonthWatch = false

function getCell(employeeId: string, date: string): GridCell {
  return grid[employeeId]?.[date] ?? { state: 'off', shiftId: null, dirty: false }
}

function setCellState(employeeId: string, date: string, state: CellState) {
  const row = grid[employeeId]
  if (!row) return
  const existing = row[date]
  row[date] = { state, shiftId: existing?.shiftId ?? null, dirty: true }
}

async function loadGrid() {
  if (!activeBranchId.value) return
  await runGridLoad(async () => {
    scheduleSetting.value = await fetchBranchScheduleSetting(activeBranchId.value)
    const monthStart = monthFirstDay(gridMonth.value)
    const allPeriods = await fetchSchedulePeriods({ branchId: activeBranchId.value })
    gridPeriod.value = allPeriods.find((p) => p.month === monthStart) ?? null
    gridDays.value = buildDays(gridMonth.value)

    for (const emp of staffList.value) {
      const row: Record<string, GridCell> = {}
      for (const d of gridDays.value) row[d.date] = { state: 'off', shiftId: null, dirty: false }
      grid[emp.id] = row
    }

    if (gridPeriod.value) {
      const periodId = gridPeriod.value.id
      const [shifts, availability] = await Promise.all([
        fetchShifts({ periodId }),
        fetchAvailabilityRequests({ periodId }),
      ])
      gridAvailability.value = availability
      const setting = scheduleSetting.value
      if (setting) {
        for (const s of shifts) {
          const row = grid[s.employeeId]
          if (!row) continue
          row[s.workDate] = { state: classifyShift(s, setting), shiftId: s.id, dirty: false }
        }
      }
    } else {
      gridAvailability.value = []
    }
  })
}

watch(gridMonth, async (_newVal, oldVal) => {
  if (suppressMonthWatch) { suppressMonthWatch = false; return }
  if (dirtyCount.value > 0) {
    try {
      await ElMessageBox.confirm(t('scheduling.switchMonthConfirm'), t('common.confirm'), {
        type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
      })
    } catch {
      suppressMonthWatch = true
      gridMonth.value = oldVal
      return
    }
  }
  await Promise.all([loadGrid(), loadActualRecords()])
})

const dirtyCount = computed(() => {
  let n = 0
  for (const emp of staffList.value) {
    const row = grid[emp.id]
    if (!row) continue
    for (const d of gridDays.value) if (row[d.date]?.dirty) n++
  }
  return n
})

function cellStateLabel(state: CellState) {
  return t(`scheduling.cell${state.charAt(0).toUpperCase()}${state.slice(1).replace('_d', 'D')}`)
}

function cycleCell(employeeId: string, date: string) {
  const cell = getCell(employeeId, date)
  const idx = cycleOrder.indexOf(cell.state)
  const next = cycleOrder[(idx === -1 ? 0 : idx + 1) % cycleOrder.length] ?? 'off'
  setCellState(employeeId, date, next)
}

// Right-click cycles the other direction so any state — including
// full_day, last in cycleOrder — is reachable in a single click instead
// of clicking forward through the whole list every time.
function reverseCycleCell(employeeId: string, date: string) {
  const cell = getCell(employeeId, date)
  const idx = cycleOrder.indexOf(cell.state)
  const prev = cycleOrder[(idx <= 0 ? cycleOrder.length - 1 : idx - 1)] ?? 'off'
  setCellState(employeeId, date, prev)
}

function hasAvailabilityConflict(employeeId: string, date: string): boolean {
  const cell = getCell(employeeId, date)
  if (cell.state === 'off') return false
  const avail = gridAvailability.value.find((a) => a.employeeId === employeeId && a.workDate === date)
  return !!avail && avail.availability === 'day_off'
}

const kitchenStaff = computed(() => staffList.value.filter((employee) => employee.workArea === 'kitchen'))
const hallStaff = computed(() => staffList.value.filter((employee) => employee.workArea === 'hall'))

function areaDayCount(date: string, employees: StaffMember[]) {
  return employees.filter((employee) => getCell(employee.id, date).state !== 'off').length
}

// ---- Batch operations -------------------------------------------------

const batchDialogVisible = ref(false)
const batchApply = reactive({ employeeId: '', rangeStart: '', rangeEnd: '', state: 'morning' as CellState })

function openBatchApply() {
  batchApply.employeeId = staffList.value[0]?.id ?? ''
  batchApply.rangeStart = gridDays.value[0]?.date ?? ''
  batchApply.rangeEnd = gridDays.value[gridDays.value.length - 1]?.date ?? ''
  batchApply.state = 'morning'
  batchDialogVisible.value = true
}

function applyBatchRange() {
  if (!batchApply.employeeId || !batchApply.rangeStart || !batchApply.rangeEnd) return
  for (const d of gridDays.value) {
    if (d.date >= batchApply.rangeStart && d.date <= batchApply.rangeEnd) {
      setCellState(batchApply.employeeId, d.date, batchApply.state)
    }
  }
  batchDialogVisible.value = false
  ElMessage.success(t('common.savedSuccess'))
}

async function copyPreviousMonth() {
  if (dirtyCount.value > 0) {
    try {
      await ElMessageBox.confirm(t('scheduling.copyPreviousMonthConfirm'), t('common.confirm'), {
        type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
      })
    } catch { return }
  }
  const prevMonthStart = `${shiftMonth(gridMonth.value, -1)}-01`
  const allPeriods = await fetchSchedulePeriods({ branchId: activeBranchId.value })
  const prevPeriod = allPeriods.find((p) => p.month === prevMonthStart)
  if (!prevPeriod) {
    ElMessage.warning(t('scheduling.noPreviousMonth'))
    return
  }
  const prevShifts = await fetchShifts({ periodId: prevPeriod.id })
  const bySlot = new Map<string, ShiftRecord>()
  for (const s of prevShifts) bySlot.set(`${s.employeeId}:${s.workDate.slice(8, 10)}`, s)
  const setting = scheduleSetting.value
  for (const emp of staffList.value) {
    for (const d of gridDays.value) {
      const day = d.date.slice(8, 10)
      const prevShift = bySlot.get(`${emp.id}:${day}`)
      const newState: CellState = prevShift && setting ? classifyShift(prevShift, setting) : 'off'
      if (getCell(emp.id, d.date).state !== newState) setCellState(emp.id, d.date, newState)
    }
  }
  ElMessage.success(t('common.savedSuccess'))
}

// ---- Save / publish ----------------------------------------------------

async function saveSingleCell(periodId: string, employeeId: string, date: string, cell: GridCell, override: boolean, overrideReason = ''): Promise<string | null> {
  if (cell.state === 'off' || cell.state === 'custom') {
    if (cell.shiftId && cell.state === 'off') await deleteShift(cell.shiftId)
    return cell.state === 'off' ? null : cell.shiftId
  }
  const times = stateToTimes(cell.state, scheduleSetting.value!)
  const payload = {
    periodId, branchId: activeBranchId.value, employeeId, workDate: date,
    plannedStart: times.start, plannedEnd: times.end, crossesMidnight: false,
    plannedBreakMinutes: times.breakMinutes, position: '', note: '',
    override, overrideReason,
  }
  if (cell.shiftId) {
    const saved = await updateShift(cell.shiftId, payload)
    return saved.id
  }
  const saved = await createShift(payload)
  return saved.id
}

async function saveDraft() {
  if (dirtyCount.value === 0) return
  gridSaving.value = true
  try {
    if (!gridPeriod.value) {
      gridPeriod.value = await createSchedulePeriod({ branchId: activeBranchId.value, month: monthFirstDay(gridMonth.value) })
    }
    const periodId = gridPeriod.value.id

    const dirtyCells: { employeeId: string; date: string; cell: GridCell }[] = []
    for (const emp of staffList.value) {
      for (const d of gridDays.value) {
        const cell = grid[emp.id]?.[d.date]
        if (cell && cell.dirty) dirtyCells.push({ employeeId: emp.id, date: d.date, cell })
      }
    }

    const results = await Promise.allSettled(
      dirtyCells.map(({ employeeId, date, cell }) => saveSingleCell(periodId, employeeId, date, cell, false)),
    )

    const outcomes: ScheduleSaveOutcome[] = []
    const needOverride: typeof dirtyCells = []
    const failed: { item: typeof dirtyCells[number]; message: string }[] = []
    results.forEach((r, i) => {
      const item = dirtyCells[i]
      if (!item) return
      const key = `${item.employeeId}:${item.date}`
      if (r.status === 'fulfilled') {
        outcomes.push({ key, ok: true, shiftId: r.value })
        return
      }
      const err = r.reason
      if (err instanceof ShiftOverrideRequiredError) needOverride.push(item)
      else failed.push({ item, message: err instanceof Error ? err.message : String(err) })
    })

    if (needOverride.length) {
      try {
        const { value: reason } = await ElMessageBox.prompt(
          t('scheduling.batchSaveOverrideHint'), t('scheduling.batchSaveOverrideTitle'),
          { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputValidator: (v: string) => !!v?.trim() },
        )
        const retryResults = await Promise.allSettled(
          needOverride.map(({ employeeId, date, cell }) => saveSingleCell(periodId, employeeId, date, cell, true, reason)),
        )
        retryResults.forEach((r, i) => {
          const item = needOverride[i]
          if (!item) return
          if (r.status === 'fulfilled') outcomes.push({ key: `${item.employeeId}:${item.date}`, ok: true, shiftId: r.value })
          else failed.push({ item, message: r.reason instanceof Error ? r.reason.message : String(r.reason) })
        })
      } catch {
        for (const item of needOverride) {
          failed.push({ item, message: t('scheduling.overrideDeclined') })
        }
      }
    }

    for (const entry of failed) {
      outcomes.push({ key: `${entry.item.employeeId}:${entry.item.date}`, ok: false, reason: entry.message })
    }
    const cellMap: Record<string, GridCell> = {}
    for (const item of dirtyCells) cellMap[`${item.employeeId}:${item.date}`] = item.cell
    const reconciled = reconcileScheduleSave(cellMap, outcomes)
    for (const [key, cell] of Object.entries(reconciled.cells)) {
      const [employeeId, date] = key.split(':')
      if (employeeId && date && grid[employeeId]) grid[employeeId][date] = cell
    }

    // Keep 实际工作确认 in sync with every save, not just after publish —
    // idempotent (only fills in shifts that don't have a record yet), so
    // this never touches a row a manager has already adjusted.
    if (reconciled.succeeded > 0) {
      await generateActualRecords(periodId)
      await loadActualRecords()
    }

    if (failed.length) {
      const lines = failed.map((f) => `${employeeName(f.item.employeeId)} ${f.item.date}: ${f.message}`).join('\n')
      ElMessageBox.alert(
        `${t('scheduling.saveSummary', { success: reconciled.succeeded, failed: failed.length })}\n${lines}`,
        t('scheduling.batchSaveFailedTitle'), { type: 'error' },
      )
    } else {
      ElMessage.success(t('scheduling.saveSummary', { success: reconciled.succeeded, failed: 0 }))
    }
  } finally {
    gridSaving.value = false
  }
}

async function handlePublishMonth() {
  if (dirtyCount.value > 0) {
    ElMessage.warning(t('scheduling.savePendingBeforePublishHint'))
    return
  }
  if (!gridPeriod.value) {
    ElMessage.warning(t('scheduling.savePendingBeforePublishHint'))
    return
  }
  const isRepublish = gridPeriod.value.status === 'published'
  try {
    await ElMessageBox.confirm(
      isRepublish ? t('scheduling.republishMonthConfirm') : t('scheduling.publishMonthConfirm'),
      t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
    )
  } catch { return }
  gridPeriod.value = await publishSchedulePeriod(gridPeriod.value.id)
  // Publishing and seeding the actual-work baseline are one step from the
  // user's perspective — generate_actual_records is idempotent (keyed on
  // employee+work_date), so calling it here is always safe, whether this is
  // the first publish or a republish after adding more shifts.
  const result = await generateActualRecords(gridPeriod.value.id)
  await loadActualRecords()
  ElMessage.success(t('scheduling.publishAndGenerateResult', { created: result.created }))
}

const printRoot = ref<HTMLElement>()
// Landscape, and floored at 0.6 rather than forced to exactly one page — a
// full month's schedule for many staff is long enough that squeezing it
// onto a single page would make it illegible; beyond that floor it's
// allowed to legitimately continue onto further (non-blank) pages.
const { fitAndPrint } = usePrintFit(printRoot, {
  marginMm: 8, pageWidthMm: 297, pageHeightMm: 210, minScale: 0.6,
})

// e.g. "心斋桥店-2026年08月-排班表"
async function printGrid() {
  const [year, month] = gridMonth.value.split('-')
  const originalTitle = document.title
  document.title = `${branchLabel(activeBranchId.value)}-${year}年${month}月-排班表`
  await fitAndPrint()
  document.title = originalTitle
}

// ---- Actual work -----------------------------------------------------------

const actualRecords = ref<ActualWorkRecord[]>([])
const { loading: actualLoading, run: runActualLoad } = useDelayedLoading()
const selectedActualIds = ref<string[]>([])
const actualEditDialogVisible = ref(false)
const actualEditingPlanned = ref<ActualWorkRecord | null>(null)
const actualEditForm = reactive({
  id: '', actualStart: '09:00', actualEnd: '18:00', crossesMidnight: false,
  actualBreakMinutes: 60, absent: false, statutoryHoliday: false, adjustmentReason: '',
})

function plannedLabel(row: ActualWorkRecord): string {
  if (row.plannedStart === null || row.plannedEnd === null) return t('scheduling.noShiftLinked')
  return `${row.plannedStart.slice(0, 5)}-${row.plannedEnd.slice(0, 5)}`
}

function actualDiffersFromPlanned(row: ActualWorkRecord): boolean {
  if (row.plannedStart === null) return false
  if (row.absent) return true
  return row.actualStart !== row.plannedStart || row.actualEnd !== row.plannedEnd
    || row.actualBreakMinutes !== row.plannedBreakMinutes
}

// A record generated straight from a published shift, with no deviation,
// is already pre-confirmed server-side (see generate_actual_records) — the
// manager only needs to look at the ones that still need a decision: never
// linked to a shift (walk-in), still pending, or edited away from plan.
function needsAttention(row: ActualWorkRecord): boolean {
  return row.shiftId === null || row.status === 'pending' || actualDiffersFromPlanned(row)
}

const showOnlyExceptions = ref(true)
const visibleActualRecords = computed(() => (
  showOnlyExceptions.value ? actualRecords.value.filter(needsAttention) : actualRecords.value
))
const exceptionCount = computed(() => actualRecords.value.filter(needsAttention).length)

async function handleDownloadActual() {
  await downloadTableExcel(
    `出勤表-${branchLabel(activeBranchId.value)}-${gridMonth.value}`,
    t('scheduling.actualWorkTab'),
    [
      { header: t('scheduling.workDate'), key: 'date', width: 14 },
      { header: t('scheduling.employee'), key: 'employee', width: 14 },
      { header: t('scheduling.plannedTime'), key: 'planned', width: 16 },
      { header: t('scheduling.actualStart'), key: 'actualStart', width: 12 },
      { header: t('scheduling.actualEnd'), key: 'actualEnd', width: 12 },
      { header: t('scheduling.actualBreakMinutes'), key: 'breakMinutes', width: 12 },
      { header: t('scheduling.absent'), key: 'absent', width: 10 },
      { header: t('scheduling.statutoryHoliday'), key: 'statutoryHoliday', width: 10 },
      { header: t('common.status'), key: 'status', width: 14 },
    ],
    actualRecords.value.map((row) => ({
      date: row.workDate,
      employee: employeeName(row.employeeId),
      planned: plannedLabel(row),
      actualStart: row.actualStart ?? '—',
      actualEnd: row.actualEnd ?? '—',
      breakMinutes: row.actualBreakMinutes,
      absent: row.absent ? '✓' : '',
      statutoryHoliday: row.statutoryHoliday ? '✓' : '',
      status: t(`scheduling.actualStatus.${row.status}`),
    })),
    'landscape',
  )
}

async function loadActualRecords() {
  if (!activeBranchId.value) return
  await runActualLoad(async () => {
    actualRecords.value = await fetchActualWorkRecords({
      branchId: activeBranchId.value,
      dateFrom: monthFirstDay(gridMonth.value),
      dateTo: monthLastDay(gridMonth.value),
    })
  })
}

function openEditActual(row: ActualWorkRecord) {
  actualEditingPlanned.value = row
  actualEditForm.id = row.id
  actualEditForm.actualStart = row.actualStart ?? '09:00'
  actualEditForm.actualEnd = row.actualEnd ?? '18:00'
  actualEditForm.crossesMidnight = row.crossesMidnight
  actualEditForm.actualBreakMinutes = row.actualBreakMinutes
  actualEditForm.absent = row.absent
  actualEditForm.statutoryHoliday = row.statutoryHoliday
  actualEditForm.adjustmentReason = row.adjustmentReason
  actualEditDialogVisible.value = true
}

async function handleSaveActual() {
  try {
    await updateActualWorkRecord(actualEditForm.id, {
      actualStart: actualEditForm.absent ? null : actualEditForm.actualStart,
      actualEnd: actualEditForm.absent ? null : actualEditForm.actualEnd,
      crossesMidnight: actualEditForm.crossesMidnight,
      actualBreakMinutes: actualEditForm.actualBreakMinutes,
      absent: actualEditForm.absent,
      statutoryHoliday: actualEditForm.statutoryHoliday,
      adjustmentReason: actualEditForm.adjustmentReason,
    })
  } catch (err) {
    if (err instanceof ApiError && err.messages().some((m) => m.toLowerCase().includes('adjustment_reason') || m.includes('differ from the scheduled shift'))) {
      ElMessage.error(t('scheduling.validateAdjustmentReason'))
      return
    }
    throw err
  }
  ElMessage.success(t('common.savedSuccess'))
  actualEditDialogVisible.value = false
  await loadActualRecords()
}

async function handleDeleteActual(row: ActualWorkRecord) {
  // A record still linked to a shift gets regenerated by
  // generate_actual_records on the next draft save (it only fills in gaps,
  // keyed by employee+date), so a hard delete would silently reappear.
  // Marking it absent instead is stable — get_or_create never touches an
  // existing row — and already excludes it from wage calculation.
  const linked = row.plannedStart !== null
  try {
    await ElMessageBox.confirm(
      t(linked ? 'scheduling.markAbsentConfirm' : 'scheduling.deleteActualConfirm'),
      t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
    )
  } catch {
    return
  }
  if (linked) {
    await updateActualWorkRecord(row.id, {
      actualStart: null, actualEnd: null, crossesMidnight: false, actualBreakMinutes: 0,
      absent: true, statutoryHoliday: row.statutoryHoliday, adjustmentReason: row.adjustmentReason,
    })
  } else {
    await deleteActualWorkRecord(row.id)
  }
  ElMessage.success(t('common.savedSuccess'))
  await loadActualRecords()
}

async function handleBulkConfirm() {
  if (!selectedActualIds.value.length) return
  const count = await bulkConfirmActualWorkRecords(selectedActualIds.value)
  ElMessage.success(t('scheduling.bulkConfirmResult', { count }))
  selectedActualIds.value = []
  await loadActualRecords()
}

function handleActualSelectionChange(rows: ActualWorkRecord[]) {
  selectedActualIds.value = rows.map((r) => r.id)
}

async function handleLockActual(row: ActualWorkRecord) {
  await lockActualWorkRecord(row.id)
  ElMessage.success(t('common.savedSuccess'))
  await loadActualRecords()
}

async function handleUnlockActual(row: ActualWorkRecord) {
  try {
    const { value } = await ElMessageBox.prompt(t('scheduling.unlockReason'), t('scheduling.unlock'), {
      confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
      inputValidator: (v: string) => !!v?.trim() || t('scheduling.validateUnlockReason'),
    })
    await unlockActualWorkRecord(row.id, value.trim())
    ElMessage.success(t('common.savedSuccess'))
    await loadActualRecords()
  } catch {
    // cancelled
  }
}

// ---- Boot -------------------------------------------------------------------

async function loadAll() {
  await loadStaff()
  await Promise.all([loadActualRecords(), loadGrid()])
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  if (!isAdmin.value) activeBranchId.value = auth.branchId ?? activeBranchId.value
  else if (!activeBranchId.value) activeBranchId.value = branchStore.list[0]?.id ?? ''
  await loadAll()
})

watch(activeBranchId, loadAll)
</script>

<template>
  <div class="scheduling-view">
    <div class="card">
      <div class="form-header no-print">
        <el-select v-if="isAdmin" v-model="activeBranchId" style="width: 160px">
          <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
        </el-select>
        <span v-else class="branch-badge">{{ branchLabel(activeBranchId) }}</span>
        <el-date-picker v-model="gridMonth" type="month" value-format="YYYY-MM" style="width: 150px" :clearable="false" />
      </div>

      <el-tabs v-model="activeTab">
        <el-tab-pane :label="t('scheduling.shiftsTab')" name="grid">
          <div class="grid-toolbar no-print">
            <el-button size="small" @click="copyPreviousMonth">{{ t('scheduling.copyPreviousMonth') }}</el-button>
            <el-button size="small" @click="openBatchApply">{{ t('scheduling.batchApplyTitle') }}</el-button>
            <span class="cell-click-hint">{{ t('scheduling.cellClickHint') }}</span>
            <span v-if="dirtyCount > 0" class="dirty-indicator">{{ t('scheduling.unsavedChanges', { count: dirtyCount }) }}</span>
            <div class="grid-toolbar-spacer" />
            <el-button :icon="Printer" @click="printGrid">{{ t('common.print') }}</el-button>
            <el-button type="primary" :loading="gridSaving" :disabled="dirtyCount === 0" @click="saveDraft">
              {{ t('scheduling.saveDraft') }}
            </el-button>
            <el-button type="success" @click="handlePublishMonth">{{ t('scheduling.publishMonth') }}</el-button>
            <el-tooltip v-if="gridPeriod?.status === 'published'" :content="t('scheduling.generateActualRecordsHint')" placement="top">
              <el-button text @click="handleGenerateActualRecords(gridPeriod)">
                {{ t('scheduling.generateActualRecords') }}
              </el-button>
            </el-tooltip>
          </div>

          <el-alert v-if="!gridPeriod" type="info" :closable="false" show-icon class="notice-alert no-print">
            {{ t('scheduling.monthNotCreatedYet') }}
          </el-alert>
          <el-alert v-else-if="gridPeriod.status === 'published'" type="success" :closable="false" show-icon class="notice-alert no-print">
            {{ t('scheduling.status.published') }}（v{{ gridPeriod.version }}）
          </el-alert>

          <div id="print-area" ref="printRoot">
            <div class="print-only print-header">
              <h3>{{ branchLabel(activeBranchId) }} — {{ gridMonth }} {{ t('scheduling.shiftsTab') }}</h3>
            </div>

            <section
              v-for="area in [{ key: 'hall', staff: hallStaff }, { key: 'kitchen', staff: kitchenStaff }]"
              :key="area.key" class="area-section"
            >
              <h4>{{ t(`staff.workArea${area.key === 'kitchen' ? 'Kitchen' : 'Hall'}`) }}</h4>
              <div v-loading="gridLoading" class="grid-scroll area-grid-scroll">
                <table class="schedule-grid transposed-grid">
                  <thead>
                    <tr>
                      <th class="col-date">{{ t('scheduling.workDate') }}</th>
                      <th class="col-weekday">{{ t('scheduling.weekday') }}</th>
                      <th v-for="emp in area.staff" :key="emp.id" class="col-person">{{ emp.name }}</th>
                      <th class="col-count">{{ t('scheduling.totalCount') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="d in gridDays" :key="d.date">
                      <td class="col-date">{{ gridMonth.slice(5) }}/{{ d.day }}</td>
                      <td class="col-weekday">{{ weekdayShortNames[d.weekdayIdx] }}</td>
                      <td
                        v-for="emp in area.staff" :key="emp.id" class="col-person cell"
                        :class="[`cell-${getCell(emp.id, d.date).state}`, { 'cell-conflict': hasAvailabilityConflict(emp.id, d.date) }]"
                        :title="hasAvailabilityConflict(emp.id, d.date) ? t('scheduling.availabilityConflictHint') : t('scheduling.cellClickHint')"
                        @click="cycleCell(emp.id, d.date)"
                        @contextmenu.prevent="reverseCycleCell(emp.id, d.date)"
                      >
                        {{ cellStateLabel(getCell(emp.id, d.date).state) }}
                      </td>
                      <td class="col-count count-cell total">{{ areaDayCount(d.date, area.staff) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="t('scheduling.actualWorkTab')" name="actual">
          <el-alert type="info" :closable="false" show-icon class="notice-alert">
            {{ t('scheduling.noteNoTimeClock') }} {{ t('scheduling.autoConfirmedHint') }}
          </el-alert>
          <div class="tab-header">
            <el-switch v-model="showOnlyExceptions" />
            <span class="exception-toggle-label">{{ t('scheduling.showOnlyExceptions', { count: exceptionCount }) }}</span>
            <div class="grid-toolbar-spacer" />
            <el-button :disabled="!selectedActualIds.length" @click="handleBulkConfirm">
              {{ t('scheduling.bulkConfirm') }}
            </el-button>
            <el-button :icon="Download" @click="handleDownloadActual">{{ t('common.downloadExcel') }}</el-button>
          </div>
          <el-table :data="visibleActualRecords" v-loading="actualLoading" :empty-text="t('scheduling.noExceptions')" @selection-change="handleActualSelectionChange">
            <el-table-column type="selection" width="45" />
            <el-table-column :label="t('scheduling.workDate')" prop="workDate" width="110" />
            <el-table-column :label="t('scheduling.employee')" width="110">
              <template #default="{ row }">{{ employeeName(row.employeeId) }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.plannedTime')" width="110">
              <template #default="{ row }">
                <span class="planned-time">{{ plannedLabel(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('scheduling.actualStart')" width="100">
              <template #default="{ row }">
                <span :class="{ 'actual-deviates': actualDiffersFromPlanned(row) }">{{ row.actualStart ?? '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('scheduling.actualEnd')" width="100">
              <template #default="{ row }">
                <span :class="{ 'actual-deviates': actualDiffersFromPlanned(row) }">{{ row.actualEnd ?? '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('scheduling.actualBreakMinutes')" width="100">
              <template #default="{ row }">{{ row.actualBreakMinutes }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.absent')" width="70">
              <template #default="{ row }">{{ row.absent ? '✓' : '' }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.statutoryHoliday')" width="90">
              <template #default="{ row }">{{ row.statutoryHoliday ? '✓' : '' }}</template>
            </el-table-column>
            <el-table-column :label="t('common.status')" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'admin_locked' ? 'success' : 'info'" round>
                  {{ t(`scheduling.actualStatus.${row.status}`) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="190">
              <template #default="{ row }">
                <el-button
                  circle text :icon="Edit" size="small" :disabled="row.status === 'admin_locked' && !isAdmin"
                  @click="openEditActual(row)"
                />
                <el-button
                  circle text :icon="Delete" size="small" :disabled="row.status === 'admin_locked' && !isAdmin"
                  :title="row.plannedStart !== null ? t('scheduling.markAbsent') : t('common.delete')"
                  @click="handleDeleteActual(row)"
                />
                <el-button v-if="isAdmin && row.status !== 'admin_locked'" size="small" @click="handleLockActual(row)">
                  {{ t('scheduling.lock') }}
                </el-button>
                <el-button v-if="isAdmin && row.status === 'admin_locked'" size="small" @click="handleUnlockActual(row)">
                  {{ t('scheduling.unlock') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="batchDialogVisible" :title="t('scheduling.batchApplyTitle')" width="420px">
      <el-form label-position="top">
        <el-form-item :label="t('scheduling.batchApplyEmployee')">
          <el-select v-model="batchApply.employeeId" style="width: 100%">
            <el-option v-for="s in staffList" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
        </el-form-item>
        <div class="form-grid-2">
          <el-form-item :label="t('scheduling.batchApplyRangeStart')">
            <el-date-picker v-model="batchApply.rangeStart" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('scheduling.batchApplyRangeEnd')">
            <el-date-picker v-model="batchApply.rangeEnd" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item :label="t('scheduling.batchApplyState')">
          <el-radio-group v-model="batchApply.state">
            <el-radio value="off">{{ t('scheduling.cellOff') }}</el-radio>
            <el-radio value="morning">{{ t('scheduling.cellMorning') }}</el-radio>
            <el-radio value="afternoon">{{ t('scheduling.cellAfternoon') }}</el-radio>
            <el-radio value="full_day">{{ t('scheduling.cellFullDay') }}</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="applyBatchRange">{{ t('scheduling.batchApplyButton') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="actualEditDialogVisible" :title="t('scheduling.actualWorkTab')" width="440px">
      <p v-if="actualEditingPlanned" class="planned-reference">
        {{ t('scheduling.plannedTime') }}：{{ plannedLabel(actualEditingPlanned) }}
        <span v-if="actualEditingPlanned.plannedBreakMinutes !== null">
          （{{ t('scheduling.actualBreakMinutes') }} {{ actualEditingPlanned.plannedBreakMinutes }}）
        </span>
      </p>
      <el-form label-position="top">
        <el-form-item :label="t('scheduling.absent')">
          <el-switch v-model="actualEditForm.absent" />
        </el-form-item>
        <template v-if="!actualEditForm.absent">
          <div class="form-grid-2">
            <el-form-item :label="t('scheduling.actualStart')">
              <el-time-picker v-model="actualEditForm.actualStart" value-format="HH:mm" format="HH:mm" style="width: 100%" />
            </el-form-item>
            <el-form-item :label="t('scheduling.actualEnd')">
              <el-time-picker v-model="actualEditForm.actualEnd" value-format="HH:mm" format="HH:mm" style="width: 100%" />
            </el-form-item>
          </div>
          <el-form-item :label="t('scheduling.crossesMidnight')">
            <el-checkbox v-model="actualEditForm.crossesMidnight" />
          </el-form-item>
          <el-form-item :label="t('scheduling.actualBreakMinutes')">
            <el-input v-model.number="actualEditForm.actualBreakMinutes" type="number" />
          </el-form-item>
        </template>
        <el-form-item :label="t('scheduling.statutoryHoliday')">
          <el-switch v-model="actualEditForm.statutoryHoliday" />
        </el-form-item>
        <el-form-item :label="t('scheduling.adjustmentReason')">
          <el-input v-model="actualEditForm.adjustmentReason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="actualEditDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSaveActual">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.form-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
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

.tab-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.exception-toggle-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.notice-alert {
  margin-bottom: 14px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.grid-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.grid-toolbar-spacer {
  flex: 1;
}

.cell-click-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.dirty-indicator {
  font-size: 12.5px;
  color: var(--danger);
  font-weight: 600;
}

.planned-time {
  color: var(--text-tertiary);
}

.actual-deviates {
  color: var(--danger);
  font-weight: 600;
}

.planned-reference {
  margin: -4px 0 12px;
  font-size: 12.5px;
  color: var(--text-secondary);
  background: var(--surface-alt);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

.grid-scroll {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.area-section + .area-section {
  margin-top: 20px;
}

.area-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
}

.transposed-grid {
  min-width: 100%;
}

.col-date,
.col-weekday {
  position: sticky;
  background: var(--surface);
  z-index: 1;
}

.col-date {
  left: 0;
  min-width: 66px;
}

.col-weekday {
  left: 66px;
  min-width: 52px;
}

.schedule-grid thead .col-date,
.schedule-grid thead .col-weekday {
  z-index: 3;
  background: var(--surface-alt);
}

.col-person {
  min-width: 92px;
}

.col-count {
  min-width: 72px;
}

.schedule-grid {
  border-collapse: collapse;
  font-size: 12.5px;
  white-space: nowrap;
}

.schedule-grid th,
.schedule-grid td {
  border: 1px solid var(--border);
  padding: 4px 6px;
  text-align: center;
}

.schedule-grid thead th {
  background: var(--surface-alt);
  position: sticky;
  top: 0;
  z-index: 2;
}

.col-employee {
  position: sticky;
  left: 0;
  background: var(--surface);
  z-index: 1;
  min-width: 150px;
  text-align: left;
}

.schedule-grid thead .col-employee {
  z-index: 3;
  background: var(--surface-alt);
}

.employee-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.employee-cell-actions {
  display: flex;
  gap: 2px;
}

.col-day {
  min-width: 46px;
}

.weekday {
  font-size: 10.5px;
  color: var(--text-tertiary);
}

.cell {
  cursor: pointer;
  user-select: none;
  transition: background-color 0.1s;
}

.cell-off {
  color: var(--text-tertiary);
}

.cell-morning {
  background: var(--accent-soft, rgba(0, 113, 227, 0.1));
  color: var(--accent);
}

.cell-afternoon {
  background: rgba(255, 159, 10, 0.15);
  color: #b06a00;
}

.cell-full_day {
  background: rgba(30, 166, 114, 0.15);
  color: var(--success);
  font-weight: 600;
}

.cell-custom {
  background: rgba(224, 57, 62, 0.1);
  color: var(--danger);
}

.cell-conflict {
  box-shadow: inset 0 0 0 2px var(--danger);
}

.count-cell {
  color: var(--text-secondary);
  font-size: 11.5px;
}

.count-cell.total {
  font-weight: 700;
  color: var(--text-primary);
}

.print-only {
  display: none;
}

.print-header {
  margin-bottom: 10px;
}

.print-header h3 {
  margin: 0;
  font-size: 15px;
}

@media print {
  @page {
    size: A4 landscape;
    margin: 8mm;
  }

  .no-print,
  .form-header,
  :deep(.el-tabs__header) {
    display: none !important;
  }

  .print-only {
    display: block;
  }

  .card {
    box-shadow: none;
    border: 0;
    padding: 0;
  }

  .area-section {
    page-break-inside: avoid;
  }

  .grid-scroll {
    overflow: visible;
    border: none;
  }

  .schedule-grid {
    width: 100%;
    table-layout: fixed;
    font-size: 8.5px;
  }

  .schedule-grid th,
  .schedule-grid td {
    padding: 2px 3px;
    border: 1px solid #999;
    color: #000;
    background: #fff !important;
  }

  .col-date,
  .col-weekday,
  .schedule-grid thead .col-date,
  .schedule-grid thead .col-weekday,
  .schedule-grid thead th {
    position: static;
  }
}
</style>
