<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Printer, Download, Plus } from '@element-plus/icons-vue'
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
  updateBranchScheduleSetting,
  fetchShiftTemplates,
  createShiftTemplate,
  updateShiftTemplate,
  deleteShiftTemplate,
  SHIFT_TEMPLATE_COLORS,
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
  type ShiftTemplate,
  type ShiftTemplateInput,
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
import { endsNextDay, formatHours, paidMinutes, shiftTimesError, type ShiftTimes } from '@/utils/shiftTime'

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
//
// Time-based: a cell holds a real shift time — start, end, break — not one
// of a fixed set of slots. Templates only fill those times in quickly; the
// shift keeps its own copy (see ShiftTemplate on the backend), so retiming a
// template never moves a day that is already planned.

interface CellShift extends ShiftTimes {
  templateId: string | null
}
interface GridCell {
  shift: CellShift | null
  shiftId: string | null
  dirty: boolean
}
interface GridDay {
  date: string
  day: number
  weekdayIdx: number
}

const gridMonth = ref(currentMonthJst())
const { loading: gridLoading, run: runGridLoad } = useDelayedLoading()
const gridSaving = ref(false)
const gridPeriod = ref<SchedulePeriod | null>(null)
const gridDays = ref<GridDay[]>([])
const gridAvailability = ref<AvailabilityRequestRecord[]>([])
const scheduleSetting = ref<BranchScheduleSetting | null>(null)
const templates = ref<ShiftTemplate[]>([])
const activeTemplates = computed(() => templates.value.filter((tpl) => tpl.active))
const templateById = computed(() => new Map(templates.value.map((tpl) => [tpl.id, tpl])))
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

function timeRangeLabel(start: string, end: string, crossesMidnight: boolean) {
  return `${start}–${crossesMidnight ? t('scheduling.nextDayPrefix') : ''}${end}`
}

function templateLabel(tpl: ShiftTemplate) {
  return tpl.name || timeRangeLabel(tpl.startTime, tpl.endTime, tpl.crossesMidnight)
}

function shiftFromTemplate(tpl: ShiftTemplate): CellShift {
  return {
    start: tpl.startTime, end: tpl.endTime, breakMinutes: tpl.breakMinutes,
    crossesMidnight: tpl.crossesMidnight, templateId: tpl.id,
  }
}

function shiftFromRecord(s: ShiftRecord): CellShift {
  return {
    start: s.plannedStart.slice(0, 5), end: s.plannedEnd.slice(0, 5), breakMinutes: s.plannedBreakMinutes,
    crossesMidnight: s.crossesMidnight, templateId: s.templateId,
  }
}

function sameShift(a: CellShift | null, b: CellShift | null) {
  if (!a || !b) return a === b
  return a.start === b.start && a.end === b.end && a.breakMinutes === b.breakMinutes
    && a.crossesMidnight === b.crossesMidnight && a.templateId === b.templateId
}

let suppressMonthWatch = false

function getCell(employeeId: string, date: string): GridCell {
  return grid[employeeId]?.[date] ?? { shift: null, shiftId: null, dirty: false }
}

function setCell(employeeId: string, date: string, shift: CellShift | null) {
  const row = grid[employeeId]
  if (!row) return
  const existing = row[date]
  row[date] = { shift, shiftId: existing?.shiftId ?? null, dirty: true }
}

function cellTemplate(cell: GridCell): ShiftTemplate | null {
  const id = cell.shift?.templateId
  return id ? templateById.value.get(id) ?? null : null
}

// The cell's main line: a named template shows its name, anything else its
// times. The times are always reachable — as the second line under a name,
// and in the tooltip.
function cellLabel(cell: GridCell) {
  if (!cell.shift) return t('scheduling.cellOff')
  const tpl = cellTemplate(cell)
  return tpl?.name || timeRangeLabel(cell.shift.start, cell.shift.end, cell.shift.crossesMidnight)
}

function cellSubLabel(cell: GridCell) {
  if (!cell.shift || !cellTemplate(cell)?.name) return ''
  return timeRangeLabel(cell.shift.start, cell.shift.end, cell.shift.crossesMidnight)
}

function cellClass(cell: GridCell) {
  if (!cell.shift) return 'cell-off'
  const tpl = cellTemplate(cell)
  return tpl ? `cell-color-${tpl.color}` : 'cell-custom'
}

function cellTooltip(employeeId: string, date: string) {
  const cell = getCell(employeeId, date)
  const parts: string[] = []
  if (cell.shift) {
    parts.push(timeRangeLabel(cell.shift.start, cell.shift.end, cell.shift.crossesMidnight))
    parts.push(t('scheduling.breakShort', { minutes: cell.shift.breakMinutes }))
    parts.push(formatHours(paidMinutes(cell.shift)))
  }
  if (hasAvailabilityConflict(employeeId, date)) parts.push(t('scheduling.availabilityConflictHint'))
  return parts.join(' · ') || t('scheduling.cellClickHint')
}

async function loadGrid() {
  if (!activeBranchId.value) return
  await runGridLoad(async () => {
    const [setting, branchTemplates] = await Promise.all([
      fetchBranchScheduleSetting(activeBranchId.value),
      fetchShiftTemplates(activeBranchId.value),
    ])
    scheduleSetting.value = setting
    templates.value = branchTemplates
    if (brush.value !== 'edit' && brush.value !== 'off' && !templateById.value.get(brush.value)?.active) {
      brush.value = 'edit'
    }
    const monthStart = monthFirstDay(gridMonth.value)
    const allPeriods = await fetchSchedulePeriods({ branchId: activeBranchId.value })
    gridPeriod.value = allPeriods.find((p) => p.month === monthStart) ?? null
    gridDays.value = buildDays(gridMonth.value)

    for (const emp of staffList.value) {
      const row: Record<string, GridCell> = {}
      for (const d of gridDays.value) row[d.date] = { shift: null, shiftId: null, dirty: false }
      grid[emp.id] = row
    }

    if (gridPeriod.value) {
      const periodId = gridPeriod.value.id
      const [shifts, availability] = await Promise.all([
        fetchShifts({ periodId }),
        fetchAvailabilityRequests({ periodId }),
      ])
      gridAvailability.value = availability
      for (const s of shifts) {
        const row = grid[s.employeeId]
        if (!row) continue
        row[s.workDate] = { shift: shiftFromRecord(s), shiftId: s.id, dirty: false }
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

// What a click on a cell does. 'edit' opens the editor, where any time can
// be typed; a template id or 'off' paints that straight onto the cell, so
// filling in a month is still one click per day.
type Brush = 'edit' | 'off' | string
const brush = ref<Brush>('edit')

function handleCellClick(employeeId: string, date: string) {
  if (brush.value === 'edit') {
    openCellEditor(employeeId, date)
    return
  }
  if (brush.value === 'off') {
    setCell(employeeId, date, null)
    return
  }
  const tpl = templateById.value.get(brush.value)
  if (tpl) setCell(employeeId, date, shiftFromTemplate(tpl))
}

// A typed time that happens to equal a template's is shown as that
// template, so the grid does not fill up with look-alike "custom" cells.
function matchTemplate(shift: ShiftTimes): string | null {
  const hit = activeTemplates.value.find((tpl) => (
    tpl.startTime === shift.start && tpl.endTime === shift.end && tpl.breakMinutes === shift.breakMinutes
  ))
  return hit?.id ?? null
}

function customShift(start: string, end: string, breakMinutes: number): CellShift {
  const times = { start, end, breakMinutes: Number(breakMinutes) || 0, crossesMidnight: endsNextDay(start, end) }
  return { ...times, templateId: matchTemplate(times) }
}

const cellEditor = reactive({
  visible: false, employeeId: '', date: '', start: '10:00', end: '15:00', breakMinutes: 0,
})

function openCellEditor(employeeId: string, date: string) {
  const current = getCell(employeeId, date).shift
  const fallback = activeTemplates.value[0]
  cellEditor.employeeId = employeeId
  cellEditor.date = date
  cellEditor.start = current?.start ?? fallback?.startTime ?? '10:00'
  cellEditor.end = current?.end ?? fallback?.endTime ?? '15:00'
  cellEditor.breakMinutes = current?.breakMinutes ?? fallback?.breakMinutes ?? 0
  cellEditor.visible = true
}

const cellEditorShift = computed(() => customShift(cellEditor.start, cellEditor.end, cellEditor.breakMinutes))
const cellEditorError = computed(() => shiftTimesError(cellEditorShift.value))

function applyEditorTemplate(tpl: ShiftTemplate) {
  setCell(cellEditor.employeeId, cellEditor.date, shiftFromTemplate(tpl))
  cellEditor.visible = false
}

function applyEditorOff() {
  setCell(cellEditor.employeeId, cellEditor.date, null)
  cellEditor.visible = false
}

function applyEditorCustom() {
  if (cellEditorError.value) return
  setCell(cellEditor.employeeId, cellEditor.date, cellEditorShift.value)
  cellEditor.visible = false
}

function hasAvailabilityConflict(employeeId: string, date: string): boolean {
  const cell = getCell(employeeId, date)
  if (!cell.shift) return false
  const avail = gridAvailability.value.find((a) => a.employeeId === employeeId && a.workDate === date)
  return !!avail && avail.availability === 'day_off'
}

const kitchenStaff = computed(() => staffList.value.filter((employee) => employee.workArea === 'kitchen'))
const hallStaff = computed(() => staffList.value.filter((employee) => employee.workArea === 'hall'))

// Headcount and paid hours for one area on one day — the two numbers a
// time-based schedule is judged by, rather than a count per fixed slot.
function areaDayTotals(date: string, employees: StaffMember[]) {
  let count = 0
  let minutes = 0
  for (const employee of employees) {
    const shift = getCell(employee.id, date).shift
    if (!shift) continue
    count += 1
    minutes += paidMinutes(shift)
  }
  return { count, minutes }
}

function employeeMonthMinutes(employeeId: string) {
  let minutes = 0
  for (const d of gridDays.value) {
    const shift = getCell(employeeId, d.date).shift
    if (shift) minutes += paidMinutes(shift)
  }
  return minutes
}

function areaMonthMinutes(employees: StaffMember[]) {
  return employees.reduce((sum, employee) => sum + employeeMonthMinutes(employee.id), 0)
}

// ---- Batch operations -------------------------------------------------

const batchDialogVisible = ref(false)
// choice: 'off', 'custom', or a template id.
const batchApply = reactive({
  employeeId: '', rangeStart: '', rangeEnd: '', choice: 'off' as string,
  start: '10:00', end: '15:00', breakMinutes: 0,
})
const batchCustomShift = computed(() => customShift(batchApply.start, batchApply.end, batchApply.breakMinutes))
const batchCustomError = computed(() => (batchApply.choice === 'custom' ? shiftTimesError(batchCustomShift.value) : null))

function openBatchApply() {
  batchApply.employeeId = staffList.value[0]?.id ?? ''
  batchApply.rangeStart = gridDays.value[0]?.date ?? ''
  batchApply.rangeEnd = gridDays.value[gridDays.value.length - 1]?.date ?? ''
  batchApply.choice = activeTemplates.value[0]?.id ?? 'custom'
  batchDialogVisible.value = true
}

function applyBatchRange() {
  if (!batchApply.employeeId || !batchApply.rangeStart || !batchApply.rangeEnd || batchCustomError.value) return
  let shift: CellShift | null = null
  if (batchApply.choice === 'custom') {
    shift = batchCustomShift.value
  } else if (batchApply.choice !== 'off') {
    const tpl = templateById.value.get(batchApply.choice)
    if (!tpl) return
    shift = shiftFromTemplate(tpl)
  }
  for (const d of gridDays.value) {
    if (d.date >= batchApply.rangeStart && d.date <= batchApply.rangeEnd) {
      setCell(batchApply.employeeId, d.date, shift ? { ...shift } : null)
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
  for (const emp of staffList.value) {
    for (const d of gridDays.value) {
      const prevShift = bySlot.get(`${emp.id}:${d.date.slice(8, 10)}`)
      // The exact times are copied, not re-derived from a template, so a
      // day typed by hand last month comes across exactly as it was.
      const next = prevShift ? shiftFromRecord(prevShift) : null
      if (!sameShift(getCell(emp.id, d.date).shift, next)) setCell(emp.id, d.date, next)
    }
  }
  ElMessage.success(t('common.savedSuccess'))
}

// ---- Save / publish ----------------------------------------------------

async function saveSingleCell(periodId: string, employeeId: string, date: string, cell: GridCell, override: boolean, overrideReason = ''): Promise<string | null> {
  if (!cell.shift) {
    if (cell.shiftId) await deleteShift(cell.shiftId)
    return null
  }
  const payload = {
    periodId, branchId: activeBranchId.value, employeeId, workDate: date,
    plannedStart: cell.shift.start, plannedEnd: cell.shift.end, crossesMidnight: cell.shift.crossesMidnight,
    plannedBreakMinutes: cell.shift.breakMinutes, templateId: cell.shift.templateId,
    position: '', note: '', override, overrideReason,
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
      // Real numbers (hours), so the column can be summed in Excel.
      { header: t('scheduling.plannedHours'), key: 'plannedHours', width: 12, numFmt: '0.0' },
      { header: t('scheduling.workedHours'), key: 'workedHours', width: 12, numFmt: '0.0' },
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
      plannedHours: row.plannedMinutes === null ? null : row.plannedMinutes / 60,
      workedHours: row.workedMinutes / 60,
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

// ---- Shift templates & attendance rules -------------------------------------

const templateDialogVisible = ref(false)
const templateForm = reactive<{ id: string } & ShiftTemplateInput>({
  id: '', branchId: '', name: '', startTime: '10:00', endTime: '15:00', breakMinutes: 0,
  color: 'blue', sortOrder: 0, active: true,
})
const templateFormShift = computed<ShiftTimes>(() => ({
  start: templateForm.startTime, end: templateForm.endTime, breakMinutes: Number(templateForm.breakMinutes) || 0,
  crossesMidnight: endsNextDay(templateForm.startTime, templateForm.endTime),
}))
const templateFormError = computed(() => shiftTimesError(templateFormShift.value))

async function reloadTemplates() {
  templates.value = await fetchShiftTemplates(activeBranchId.value)
}

function openTemplateDialog(tpl?: ShiftTemplate) {
  Object.assign(templateForm, tpl
    ? { ...tpl }
    : {
        id: '', branchId: activeBranchId.value, name: '', startTime: '10:00', endTime: '15:00', breakMinutes: 0,
        color: SHIFT_TEMPLATE_COLORS[templates.value.length % SHIFT_TEMPLATE_COLORS.length] ?? 'blue',
        sortOrder: templates.value.length + 1, active: true,
      })
  templateDialogVisible.value = true
}

async function saveTemplate() {
  if (templateFormError.value) return
  const payload: ShiftTemplateInput = {
    branchId: activeBranchId.value, name: templateForm.name.trim(), startTime: templateForm.startTime,
    endTime: templateForm.endTime, breakMinutes: Number(templateForm.breakMinutes) || 0,
    color: templateForm.color, sortOrder: templateForm.sortOrder, active: templateForm.active,
  }
  if (templateForm.id) await updateShiftTemplate(templateForm.id, payload)
  else await createShiftTemplate(payload)
  templateDialogVisible.value = false
  ElMessage.success(t('common.savedSuccess'))
  await reloadTemplates()
}

async function setTemplateActive(tpl: ShiftTemplate, active: boolean) {
  await updateShiftTemplate(tpl.id, { ...tpl, active })
  await reloadTemplates()
}

async function handleDeleteTemplate(tpl: ShiftTemplate) {
  try {
    await ElMessageBox.confirm(t('scheduling.deleteTemplateConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
    })
  } catch { return }
  await deleteShiftTemplate(tpl.id)
  if (brush.value === tpl.id) brush.value = 'edit'
  ElMessage.success(t('common.savedSuccess'))
  await reloadTemplates()
}

// Attendance rules are head-office policy: the server lets only admin
// change them, and the form is read-only for a branch account to match.
const rulesForm = reactive({
  lateGraceMinutes: 0, earlyLeaveGraceMinutes: 0, attendanceDayCutoverHour: 5, selfPunchEnabled: true,
})
const rulesSaving = ref(false)

watch(scheduleSetting, (setting) => {
  if (!setting) return
  rulesForm.lateGraceMinutes = setting.lateGraceMinutes
  rulesForm.earlyLeaveGraceMinutes = setting.earlyLeaveGraceMinutes
  rulesForm.attendanceDayCutoverHour = setting.attendanceDayCutoverHour
  rulesForm.selfPunchEnabled = setting.selfPunchEnabled
})

async function saveRules() {
  rulesSaving.value = true
  try {
    scheduleSetting.value = await updateBranchScheduleSetting(activeBranchId.value, { ...rulesForm })
    ElMessage.success(t('common.savedSuccess'))
  } finally {
    rulesSaving.value = false
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
          <div class="brush-bar no-print" role="radiogroup" :aria-label="t('scheduling.brushLabel')">
            <span class="brush-bar-label">{{ t('scheduling.brushLabel') }}</span>
            <button
              type="button" class="brush brush-inline" :class="{ active: brush === 'edit' }" role="radio"
              :aria-checked="brush === 'edit'" @click="brush = 'edit'"
            >
              <el-icon><Edit /></el-icon>{{ t('scheduling.brushEdit') }}
            </button>
            <button
              type="button" class="brush cell-off" :class="{ active: brush === 'off' }" role="radio"
              :aria-checked="brush === 'off'" @click="brush = 'off'"
            >
              {{ t('scheduling.cellOff') }}
            </button>
            <button
              v-for="tpl in activeTemplates" :key="tpl.id" type="button" class="brush"
              :class="[`cell-color-${tpl.color}`, { active: brush === tpl.id }]" role="radio"
              :aria-checked="brush === tpl.id" @click="brush = tpl.id"
            >
              <span class="brush-name">{{ templateLabel(tpl) }}</span>
              <span v-if="tpl.name" class="brush-times">{{ timeRangeLabel(tpl.startTime, tpl.endTime, tpl.crossesMidnight) }}</span>
            </button>
            <el-button v-if="!activeTemplates.length" size="small" text type="primary" @click="activeTab = 'templates'">
              {{ t('scheduling.noTemplatesYet') }}
            </el-button>
          </div>
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
                      <th class="col-count">{{ t('scheduling.headcount') }}</th>
                      <th class="col-count">{{ t('scheduling.dayHours') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="d in gridDays" :key="d.date">
                      <td class="col-date">{{ gridMonth.slice(5) }}/{{ d.day }}</td>
                      <td class="col-weekday">{{ weekdayShortNames[d.weekdayIdx] }}</td>
                      <td
                        v-for="emp in area.staff" :key="emp.id" class="col-person cell"
                        :class="[cellClass(getCell(emp.id, d.date)), {
                          'cell-conflict': hasAvailabilityConflict(emp.id, d.date),
                          'cell-dirty': getCell(emp.id, d.date).dirty,
                        }]"
                        :title="cellTooltip(emp.id, d.date)"
                        tabindex="0" role="button"
                        @click="handleCellClick(emp.id, d.date)"
                        @keydown.enter.prevent="handleCellClick(emp.id, d.date)"
                      >
                        <span class="cell-label">{{ cellLabel(getCell(emp.id, d.date)) }}</span>
                        <span v-if="cellSubLabel(getCell(emp.id, d.date))" class="cell-sub">{{ cellSubLabel(getCell(emp.id, d.date)) }}</span>
                      </td>
                      <td class="col-count count-cell total">{{ areaDayTotals(d.date, area.staff).count }}</td>
                      <td class="col-count count-cell">{{ formatHours(areaDayTotals(d.date, area.staff).minutes) }}</td>
                    </tr>
                  </tbody>
                  <tfoot>
                    <tr>
                      <th class="col-date" colspan="2">{{ t('scheduling.monthHours') }}</th>
                      <td v-for="emp in area.staff" :key="emp.id" class="col-person count-cell total">
                        {{ formatHours(employeeMonthMinutes(emp.id)) }}
                      </td>
                      <td class="col-count count-cell" />
                      <td class="col-count count-cell total">{{ formatHours(areaMonthMinutes(area.staff)) }}</td>
                    </tr>
                  </tfoot>
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
            <el-table-column :label="t('scheduling.plannedHours')" width="90" align="right">
              <template #default="{ row }">{{ row.plannedMinutes === null ? '—' : formatHours(row.plannedMinutes) }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.workedHours')" width="90" align="right">
              <template #default="{ row }">
                <span :class="{ 'actual-deviates': row.plannedMinutes !== null && row.workedMinutes !== row.plannedMinutes }">
                  {{ formatHours(row.workedMinutes) }}
                </span>
              </template>
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

        <el-tab-pane :label="t('scheduling.templatesTab')" name="templates">
          <el-alert type="info" :closable="false" show-icon class="notice-alert">
            {{ t('scheduling.templatesHint') }}
          </el-alert>
          <div class="tab-header">
            <div class="grid-toolbar-spacer" />
            <el-button type="primary" :icon="Plus" @click="openTemplateDialog()">{{ t('scheduling.addTemplate') }}</el-button>
          </div>
          <el-table :data="templates" :empty-text="t('scheduling.noTemplates')">
            <el-table-column :label="t('scheduling.templateName')" min-width="160">
              <template #default="{ row }">
                <span class="template-swatch" :class="`cell-color-${row.color}`" aria-hidden="true" />
                {{ row.name || t('scheduling.templateUnnamed') }}
              </template>
            </el-table-column>
            <el-table-column :label="t('scheduling.templateTime')" min-width="140">
              <template #default="{ row }">{{ timeRangeLabel(row.startTime, row.endTime, row.crossesMidnight) }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.plannedBreakMinutes')" width="110" align="right">
              <template #default="{ row }">{{ row.breakMinutes }}</template>
            </el-table-column>
            <el-table-column :label="t('scheduling.paidHours')" width="100" align="right">
              <template #default="{ row }">
                {{ formatHours(paidMinutes({ start: row.startTime, end: row.endTime, breakMinutes: row.breakMinutes, crossesMidnight: row.crossesMidnight })) }}
              </template>
            </el-table-column>
            <el-table-column :label="t('scheduling.templateActive')" width="100">
              <template #default="{ row }">
                <el-switch :model-value="row.active" @change="(v: string | number | boolean) => setTemplateActive(row, Boolean(v))" />
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="110">
              <template #default="{ row }">
                <el-button circle text :icon="Edit" size="small" :aria-label="t('common.edit')" @click="openTemplateDialog(row)" />
                <el-button circle text :icon="Delete" size="small" :aria-label="t('common.delete')" @click="handleDeleteTemplate(row)" />
              </template>
            </el-table-column>
          </el-table>

          <section class="rules-section">
            <h4>{{ t('scheduling.attendanceRules') }}</h4>
            <p class="rules-hint">{{ isAdmin ? t('scheduling.attendanceRulesHint') : t('scheduling.attendanceRulesAdminOnly') }}</p>
            <el-form label-position="top" class="rules-form" :disabled="!isAdmin">
              <el-form-item :label="t('scheduling.lateGraceMinutes')">
                <el-input-number v-model="rulesForm.lateGraceMinutes" :min="0" :max="240" />
              </el-form-item>
              <el-form-item :label="t('scheduling.earlyLeaveGraceMinutes')">
                <el-input-number v-model="rulesForm.earlyLeaveGraceMinutes" :min="0" :max="240" />
              </el-form-item>
              <el-form-item :label="t('scheduling.cutoverHour')">
                <el-input-number v-model="rulesForm.attendanceDayCutoverHour" :min="0" :max="23" />
                <div class="field-hint">{{ t('scheduling.cutoverHourHint', { hour: rulesForm.attendanceDayCutoverHour }) }}</div>
              </el-form-item>
              <el-form-item :label="t('scheduling.selfPunchEnabled')">
                <el-switch v-model="rulesForm.selfPunchEnabled" />
              </el-form-item>
            </el-form>
            <el-button v-if="isAdmin" type="primary" :loading="rulesSaving" @click="saveRules">{{ t('common.save') }}</el-button>
          </section>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog
      v-model="cellEditor.visible" width="420px"
      :title="t('scheduling.cellEditorTitle', { name: employeeName(cellEditor.employeeId), date: cellEditor.date })"
    >
      <div v-if="activeTemplates.length" class="editor-templates">
        <button
          v-for="tpl in activeTemplates" :key="tpl.id" type="button" class="brush"
          :class="`cell-color-${tpl.color}`" @click="applyEditorTemplate(tpl)"
        >
          <span class="brush-name">{{ templateLabel(tpl) }}</span>
          <span v-if="tpl.name" class="brush-times">{{ timeRangeLabel(tpl.startTime, tpl.endTime, tpl.crossesMidnight) }}</span>
        </button>
        <button type="button" class="brush cell-off" @click="applyEditorOff">{{ t('scheduling.cellOff') }}</button>
      </div>
      <h5 class="editor-subtitle">{{ t('scheduling.customTime') }}</h5>
      <el-form label-position="top">
        <div class="form-grid-2">
          <el-form-item :label="t('scheduling.startTime')">
            <el-time-picker v-model="cellEditor.start" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('scheduling.endTime')">
            <el-time-picker v-model="cellEditor.end" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item :label="t('scheduling.plannedBreakMinutes')">
          <el-input-number v-model="cellEditor.breakMinutes" :min="0" :step="15" />
        </el-form-item>
      </el-form>
      <p class="editor-summary" :class="{ error: cellEditorError }">
        <template v-if="cellEditorError">{{ t(`scheduling.conflicts.${cellEditorError}`) }}</template>
        <template v-else>
          {{ timeRangeLabel(cellEditorShift.start, cellEditorShift.end, cellEditorShift.crossesMidnight) }}
          · {{ formatHours(paidMinutes(cellEditorShift)) }}
        </template>
      </p>
      <template #footer>
        <el-button @click="cellEditor.visible = false">{{ t('common.cancel') }}</el-button>
        <el-button v-if="getCell(cellEditor.employeeId, cellEditor.date).shift" @click="applyEditorOff">
          {{ t('scheduling.clearCell') }}
        </el-button>
        <el-button type="primary" :disabled="!!cellEditorError" @click="applyEditorCustom">{{ t('scheduling.applyCustom') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="templateDialogVisible" width="420px" :title="templateForm.id ? t('scheduling.editTemplate') : t('scheduling.addTemplate')">
      <el-form label-position="top">
        <el-form-item :label="t('scheduling.templateName')">
          <el-input v-model="templateForm.name" maxlength="40" :placeholder="t('scheduling.templateNamePlaceholder')" />
        </el-form-item>
        <div class="form-grid-2">
          <el-form-item :label="t('scheduling.startTime')">
            <el-time-picker v-model="templateForm.startTime" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('scheduling.endTime')">
            <el-time-picker v-model="templateForm.endTime" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item :label="t('scheduling.plannedBreakMinutes')">
          <el-input-number v-model="templateForm.breakMinutes" :min="0" :step="15" />
        </el-form-item>
        <el-form-item :label="t('scheduling.templateColor')">
          <div class="color-choices" role="radiogroup">
            <button
              v-for="color in SHIFT_TEMPLATE_COLORS" :key="color" type="button" class="color-choice"
              :class="[`cell-color-${color}`, { active: templateForm.color === color }]" role="radio"
              :aria-checked="templateForm.color === color" :aria-label="t(`scheduling.colors.${color}`)"
              @click="templateForm.color = color"
            />
          </div>
        </el-form-item>
      </el-form>
      <p class="editor-summary" :class="{ error: templateFormError }">
        <template v-if="templateFormError">{{ t(`scheduling.conflicts.${templateFormError}`) }}</template>
        <template v-else>
          {{ timeRangeLabel(templateFormShift.start, templateFormShift.end, templateFormShift.crossesMidnight) }}
          · {{ formatHours(paidMinutes(templateFormShift)) }}
        </template>
      </p>
      <template #footer>
        <el-button @click="templateDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!!templateFormError" @click="saveTemplate">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

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
          <el-select v-model="batchApply.choice" style="width: 100%">
            <el-option v-for="tpl in activeTemplates" :key="tpl.id" :value="tpl.id" :label="templateLabel(tpl)" />
            <el-option value="custom" :label="t('scheduling.customTime')" />
            <el-option value="off" :label="t('scheduling.cellOff')" />
          </el-select>
        </el-form-item>
        <template v-if="batchApply.choice === 'custom'">
          <div class="form-grid-2">
            <el-form-item :label="t('scheduling.startTime')">
              <el-time-picker v-model="batchApply.start" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
            </el-form-item>
            <el-form-item :label="t('scheduling.endTime')">
              <el-time-picker v-model="batchApply.end" value-format="HH:mm" format="HH:mm" :clearable="false" style="width: 100%" />
            </el-form-item>
          </div>
          <el-form-item :label="t('scheduling.plannedBreakMinutes')">
            <el-input-number v-model="batchApply.breakMinutes" :min="0" :step="15" />
          </el-form-item>
          <p v-if="batchCustomError" class="editor-summary error">{{ t(`scheduling.conflicts.${batchCustomError}`) }}</p>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!!batchCustomError" @click="applyBatchRange">{{ t('scheduling.batchApplyButton') }}</el-button>
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

.cell-label,
.cell-sub {
  display: block;
  line-height: 1.25;
}

.cell-sub {
  font-size: 10.5px;
  opacity: 0.8;
}

/* A time typed by hand rather than placed from a template. */
.cell-custom {
  background: var(--surface-alt);
  color: var(--text-primary);
  box-shadow: inset 0 0 0 1px var(--border-strong, var(--border));
}

/* Template colours — shared by grid cells, the brush bar and the swatches. */
.cell-color-blue { background: rgba(0, 113, 227, 0.12); color: #0058b0; }
.cell-color-green { background: rgba(30, 166, 114, 0.15); color: #137a52; }
.cell-color-orange { background: rgba(255, 159, 10, 0.18); color: #9a5a00; }
.cell-color-purple { background: rgba(137, 80, 220, 0.14); color: #6a36b8; }
.cell-color-red { background: rgba(224, 57, 62, 0.12); color: #b3262b; }
.cell-color-teal { background: rgba(0, 150, 160, 0.14); color: #00707a; }
.cell-color-gray { background: rgba(120, 120, 128, 0.15); color: #55555c; }

/* Same hues, lighter text, so the labels stay readable on a dark surface. */
html[data-theme='dark'] .cell-color-blue { background: rgba(10, 132, 255, 0.22); color: #7cb8ff; }
html[data-theme='dark'] .cell-color-green { background: rgba(48, 209, 88, 0.2); color: #6fe08f; }
html[data-theme='dark'] .cell-color-orange { background: rgba(255, 159, 10, 0.22); color: #ffc261; }
html[data-theme='dark'] .cell-color-purple { background: rgba(191, 90, 242, 0.22); color: #d49bf7; }
html[data-theme='dark'] .cell-color-red { background: rgba(255, 69, 58, 0.2); color: #ff8c84; }
html[data-theme='dark'] .cell-color-teal { background: rgba(64, 200, 224, 0.2); color: #7fdcea; }
html[data-theme='dark'] .cell-color-gray { background: rgba(152, 152, 157, 0.2); color: #c7c7cc; }

.cell-dirty {
  outline: 2px dashed var(--accent);
  outline-offset: -3px;
}

.cell:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.brush-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.brush-bar-label {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-right: 2px;
}

.brush {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 1px;
  min-height: 36px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-primary);
  font-size: 12.5px;
  line-height: 1.2;
  cursor: pointer;
}

.brush .el-icon {
  margin-right: 4px;
}

.brush.brush-inline {
  flex-direction: row;
  align-items: center;
}

.brush.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent);
}

.brush-name {
  font-weight: 600;
}

.brush-times {
  font-size: 11px;
  opacity: 0.85;
}

.editor-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.editor-subtitle {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.editor-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.editor-summary.error {
  color: var(--danger);
}

.template-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  margin-right: 6px;
  vertical-align: -1px;
}

.color-choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.color-choice {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border);
  cursor: pointer;
}

.color-choice.active {
  box-shadow: 0 0 0 2px var(--accent);
}

/* Swatches show the template colour at full strength (its text colour),
   not the pale cell background, so the hues are easy to tell apart. */
.template-swatch[class*='cell-color-'],
.color-choice[class*='cell-color-'],
html[data-theme='dark'] .template-swatch[class*='cell-color-'],
html[data-theme='dark'] .color-choice[class*='cell-color-'] {
  background: currentColor;
}

.rules-section {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.rules-section h4 {
  margin: 0 0 4px;
}

.rules-hint,
.field-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0 0 10px;
  line-height: 1.5;
}

.field-hint {
  margin: 4px 0 0;
  width: 100%;
}

.rules-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0 16px;
  max-width: 900px;
}

.schedule-grid tfoot th,
.schedule-grid tfoot td {
  background: var(--surface-alt);
  font-weight: 600;
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
