import { http, ApiError } from './http'

// ---- Branch schedule settings (shift-time template) -------------------

export interface BranchScheduleSetting {
  branchId: string
  morningStart: string
  morningEnd: string
  afternoonStart: string
  afternoonEnd: string
  fullDayStart: string
  fullDayEnd: string
  fullDayBreakStart: string
  fullDayBreakEnd: string
  active: boolean
}

interface BranchScheduleSettingDto {
  branch: string
  morning_start: string
  morning_end: string
  afternoon_start: string
  afternoon_end: string
  full_day_start: string
  full_day_end: string
  full_day_break_start: string
  full_day_break_end: string
  active: boolean
}

function fromScheduleSettingDto(dto: BranchScheduleSettingDto): BranchScheduleSetting {
  return {
    branchId: dto.branch,
    morningStart: dto.morning_start.slice(0, 5),
    morningEnd: dto.morning_end.slice(0, 5),
    afternoonStart: dto.afternoon_start.slice(0, 5),
    afternoonEnd: dto.afternoon_end.slice(0, 5),
    fullDayStart: dto.full_day_start.slice(0, 5),
    fullDayEnd: dto.full_day_end.slice(0, 5),
    fullDayBreakStart: dto.full_day_break_start.slice(0, 5),
    fullDayBreakEnd: dto.full_day_break_end.slice(0, 5),
    active: dto.active,
  }
}

export async function fetchBranchScheduleSetting(branchId: string): Promise<BranchScheduleSetting> {
  const dto = await http.get<BranchScheduleSettingDto>(`/branch-schedule-settings/${branchId}/`)
  return fromScheduleSettingDto(dto)
}

// ---- Schedule periods -------------------------------------------------

export type SchedulePeriodStatus = 'collecting' | 'drafting' | 'published' | 'closed'

export interface SchedulePeriod {
  id: string
  branchId: string
  /** Always the 1st of the month for a current (non-legacy) period; null
   * for a legacy period created before the monthly-grid redesign. */
  month: string | null
  startDate: string
  endDate: string
  status: SchedulePeriodStatus
  publishedAt: string | null
  version: number
  note: string
}

interface SchedulePeriodDto {
  id: number
  branch: string
  month: string | null
  start_date: string
  end_date: string
  status: SchedulePeriodStatus
  published_at: string | null
  version: number
  note: string
}

function fromPeriodDto(dto: SchedulePeriodDto): SchedulePeriod {
  return {
    id: String(dto.id),
    branchId: dto.branch,
    month: dto.month,
    startDate: dto.start_date,
    endDate: dto.end_date,
    status: dto.status,
    publishedAt: dto.published_at,
    version: dto.version,
    note: dto.note,
  }
}

export async function fetchSchedulePeriods(params: { branchId?: string; status?: string } = {}): Promise<SchedulePeriod[]> {
  const query = new URLSearchParams()
  if (params.branchId) query.set('branch', params.branchId)
  if (params.status) query.set('status', params.status)
  const rows = await http.get<SchedulePeriodDto[]>(`/schedule-periods/?${query.toString()}`)
  return rows.map(fromPeriodDto)
}

/** `month` must be the 1st of the target month, e.g. '2026-06-01' — the
 * backend always computes the full calendar month's start/end dates from
 * it; manual date-range entry no longer exists. */
export async function createSchedulePeriod(payload: {
  branchId: string
  month: string
  note?: string
}): Promise<SchedulePeriod> {
  const dto = await http.post<SchedulePeriodDto>('/schedule-periods/', {
    branch: payload.branchId, month: payload.month, note: payload.note ?? '',
  })
  return fromPeriodDto(dto)
}

export async function deleteSchedulePeriod(id: string): Promise<void> {
  await http.delete(`/schedule-periods/${id}/`)
}

export async function publishSchedulePeriod(id: string): Promise<SchedulePeriod> {
  const dto = await http.post<SchedulePeriodDto>(`/schedule-periods/${id}/publish/`)
  return fromPeriodDto(dto)
}

export async function generateActualRecords(periodId: string): Promise<{ created: number; totalShifts: number }> {
  const result = await http.post<{ created: number; total_shifts: number }>(
    `/schedule-periods/${periodId}/generate_actual_records/`,
  )
  return { created: result.created, totalShifts: result.total_shifts }
}

// ---- Availability requests ---------------------------------------------

export type Availability = 'available' | 'day_off'

export interface AvailabilityRequestRecord {
  id: string
  periodId: string
  employeeId: string
  workDate: string
  availability: Availability
  startTime: string | null
  endTime: string | null
  crossesMidnight: boolean
  note: string
}

interface AvailabilityDto {
  id: number
  period: number
  employee: number
  work_date: string
  availability: Availability
  start_time: string | null
  end_time: string | null
  crosses_midnight: boolean
  note: string
}

function fromAvailabilityDto(dto: AvailabilityDto): AvailabilityRequestRecord {
  return {
    id: String(dto.id),
    periodId: String(dto.period),
    employeeId: String(dto.employee),
    workDate: dto.work_date,
    availability: dto.availability,
    startTime: dto.start_time,
    endTime: dto.end_time,
    crossesMidnight: dto.crosses_midnight,
    note: dto.note,
  }
}

function availabilityToDto(payload: Omit<AvailabilityRequestRecord, 'id'>) {
  return {
    period: Number(payload.periodId),
    employee: Number(payload.employeeId),
    work_date: payload.workDate,
    availability: payload.availability,
    start_time: payload.startTime,
    end_time: payload.endTime,
    crosses_midnight: payload.crossesMidnight,
    note: payload.note,
  }
}

export async function fetchAvailabilityRequests(params: { periodId?: string; employeeId?: string }): Promise<AvailabilityRequestRecord[]> {
  const query = new URLSearchParams()
  if (params.periodId) query.set('period', params.periodId)
  if (params.employeeId) query.set('employee', params.employeeId)
  const rows = await http.get<AvailabilityDto[]>(`/availability-requests/?${query.toString()}`)
  return rows.map(fromAvailabilityDto)
}

export async function saveAvailabilityRequest(
  id: string | null,
  payload: Omit<AvailabilityRequestRecord, 'id'>,
): Promise<AvailabilityRequestRecord> {
  const dto = id
    ? await http.patch<AvailabilityDto>(`/availability-requests/${id}/`, availabilityToDto(payload))
    : await http.post<AvailabilityDto>('/availability-requests/', availabilityToDto(payload))
  return fromAvailabilityDto(dto)
}

export async function deleteAvailabilityRequest(id: string): Promise<void> {
  await http.delete(`/availability-requests/${id}/`)
}

// ---- Shifts --------------------------------------------------------------

export interface ShiftWarning {
  code: 'requires-override'
  warnings: string[]
}

export interface ShiftConflict {
  code: 'shift-conflict'
  errors: string[]
}

export interface ShiftRecord {
  id: string
  periodId: string
  branchId: string
  employeeId: string
  workDate: string
  plannedStart: string
  plannedEnd: string
  crossesMidnight: boolean
  plannedBreakMinutes: number
  position: string
  note: string
  override: boolean
  overrideReason: string
}

interface ShiftDto {
  id: number
  period: number
  branch: string
  employee: number
  work_date: string
  planned_start: string
  planned_end: string
  crosses_midnight: boolean
  planned_break_minutes: number
  position: string
  note: string
  override: boolean
  override_reason: string
}

function fromShiftDto(dto: ShiftDto): ShiftRecord {
  return {
    id: String(dto.id),
    periodId: String(dto.period),
    branchId: dto.branch,
    employeeId: String(dto.employee),
    workDate: dto.work_date,
    plannedStart: dto.planned_start,
    plannedEnd: dto.planned_end,
    crossesMidnight: dto.crosses_midnight,
    plannedBreakMinutes: dto.planned_break_minutes,
    position: dto.position,
    note: dto.note,
    override: dto.override,
    overrideReason: dto.override_reason,
  }
}

function shiftToDto(payload: Omit<ShiftRecord, 'id'>) {
  return {
    period: Number(payload.periodId),
    branch: payload.branchId,
    employee: Number(payload.employeeId),
    work_date: payload.workDate,
    planned_start: payload.plannedStart,
    planned_end: payload.plannedEnd,
    crosses_midnight: payload.crossesMidnight,
    planned_break_minutes: payload.plannedBreakMinutes,
    position: payload.position,
    note: payload.note,
    override: payload.override,
    override_reason: payload.overrideReason,
  }
}

export async function fetchShifts(params: { periodId?: string; branchId?: string; employeeId?: string } = {}): Promise<ShiftRecord[]> {
  const query = new URLSearchParams()
  if (params.periodId) query.set('period', params.periodId)
  if (params.branchId) query.set('branch', params.branchId)
  if (params.employeeId) query.set('employee', params.employeeId)
  const rows = await http.get<ShiftDto[]>(`/shifts/?${query.toString()}`)
  return rows.map(fromShiftDto)
}

/** Throws Error('requires-override') with `.warnings` attached when the
 * shift is a soft conflict (day-off request / outside availability) and
 * `override` wasn't set — the caller should re-submit with
 * `override: true` and a reason once the manager confirms. */
export class ShiftOverrideRequiredError extends Error {
  warnings: string[]
  constructor(warnings: string[]) {
    super('requires-override')
    this.warnings = warnings
  }
}

async function saveShift(id: string | null, payload: Omit<ShiftRecord, 'id'>): Promise<ShiftRecord> {
  try {
    const dto = id
      ? await http.patch<ShiftDto>(`/shifts/${id}/`, shiftToDto(payload))
      : await http.post<ShiftDto>('/shifts/', shiftToDto(payload))
    return fromShiftDto(dto)
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      const body = err.body as { code?: string; warnings?: string[] } | undefined
      if (body?.code === 'requires-override') throw new ShiftOverrideRequiredError(body.warnings ?? [])
    }
    throw err
  }
}

export async function createShift(payload: Omit<ShiftRecord, 'id'>): Promise<ShiftRecord> {
  return saveShift(null, payload)
}

export async function updateShift(id: string, payload: Omit<ShiftRecord, 'id'>): Promise<ShiftRecord> {
  return saveShift(id, payload)
}

export async function deleteShift(id: string): Promise<void> {
  await http.delete(`/shifts/${id}/`)
}

// ---- Actual work records ---------------------------------------------

export type ActualWorkStatus = 'pending' | 'manager_confirmed' | 'admin_locked'

export interface ActualWorkRecord {
  id: string
  shiftId: string | null
  branchId: string
  employeeId: string
  workDate: string
  actualStart: string | null
  actualEnd: string | null
  crossesMidnight: boolean
  actualBreakMinutes: number
  absent: boolean
  statutoryHoliday: boolean
  adjustmentReason: string
  status: ActualWorkStatus
  /** What the shift template said — null when this record has no linked
   * shift (e.g. an ad hoc walk-in entry). Read-only, for on-screen
   * comparison against the actual-time fields above only. */
  plannedStart: string | null
  plannedEnd: string | null
  plannedBreakMinutes: number | null
  plannedCrossesMidnight: boolean | null
}

interface ActualWorkRecordDto {
  id: number
  shift: number | null
  branch: string
  employee: number
  work_date: string
  actual_start: string | null
  actual_end: string | null
  crosses_midnight: boolean
  actual_break_minutes: number
  absent: boolean
  statutory_holiday: boolean
  adjustment_reason: string
  status: ActualWorkStatus
  planned_start: string | null
  planned_end: string | null
  planned_break_minutes: number | null
  planned_crosses_midnight: boolean | null
}

function fromActualWorkDto(dto: ActualWorkRecordDto): ActualWorkRecord {
  return {
    id: String(dto.id),
    shiftId: dto.shift != null ? String(dto.shift) : null,
    branchId: dto.branch,
    employeeId: String(dto.employee),
    workDate: dto.work_date,
    actualStart: dto.actual_start,
    actualEnd: dto.actual_end,
    crossesMidnight: dto.crosses_midnight,
    actualBreakMinutes: dto.actual_break_minutes,
    absent: dto.absent,
    statutoryHoliday: dto.statutory_holiday,
    adjustmentReason: dto.adjustment_reason,
    status: dto.status,
    plannedStart: dto.planned_start,
    plannedEnd: dto.planned_end,
    plannedBreakMinutes: dto.planned_break_minutes,
    plannedCrossesMidnight: dto.planned_crosses_midnight,
  }
}

export async function fetchActualWorkRecords(params: {
  branchId?: string; employeeId?: string; workDate?: string; status?: string
  dateFrom?: string; dateTo?: string
} = {}): Promise<ActualWorkRecord[]> {
  const query = new URLSearchParams()
  if (params.branchId) query.set('branch', params.branchId)
  if (params.employeeId) query.set('employee', params.employeeId)
  if (params.workDate) query.set('work_date', params.workDate)
  if (params.status) query.set('status', params.status)
  if (params.dateFrom) query.set('date_from', params.dateFrom)
  if (params.dateTo) query.set('date_to', params.dateTo)
  const rows = await http.get<ActualWorkRecordDto[]>(`/actual-work-records/?${query.toString()}`)
  return rows.map(fromActualWorkDto)
}

export async function updateActualWorkRecord(id: string, payload: {
  actualStart: string | null
  actualEnd: string | null
  crossesMidnight: boolean
  actualBreakMinutes: number
  absent: boolean
  statutoryHoliday: boolean
  adjustmentReason: string
}): Promise<ActualWorkRecord> {
  const dto = await http.patch<ActualWorkRecordDto>(`/actual-work-records/${id}/`, {
    actual_start: payload.actualStart,
    actual_end: payload.actualEnd,
    crosses_midnight: payload.crossesMidnight,
    actual_break_minutes: payload.actualBreakMinutes,
    absent: payload.absent,
    statutory_holiday: payload.statutoryHoliday,
    adjustment_reason: payload.adjustmentReason,
  })
  return fromActualWorkDto(dto)
}

export async function deleteActualWorkRecord(id: string): Promise<void> {
  await http.delete(`/actual-work-records/${id}/`)
}

export async function bulkConfirmActualWorkRecords(ids: string[]): Promise<number> {
  const result = await http.post<{ confirmed: number }>('/actual-work-records/bulk_confirm/', { ids: ids.map(Number) })
  return result.confirmed
}

export async function lockActualWorkRecord(id: string): Promise<ActualWorkRecord> {
  const dto = await http.post<ActualWorkRecordDto>(`/actual-work-records/${id}/lock/`)
  return fromActualWorkDto(dto)
}

export async function unlockActualWorkRecord(id: string, reason: string): Promise<ActualWorkRecord> {
  const dto = await http.post<ActualWorkRecordDto>(`/actual-work-records/${id}/unlock/`, { reason })
  return fromActualWorkDto(dto)
}
