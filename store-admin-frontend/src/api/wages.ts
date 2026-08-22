import { http, ApiError } from './http'

// ---- Wage rules (admin/branch only — never exposed to the employee) ----

export type TransportationType = 'none' | 'per_attendance' | 'monthly'

export interface WageRuleRecord {
  id: string
  employeeId: string
  effectiveFrom: string
  effectiveTo: string | null
  hourlyRate: number
  nightPremiumRate: number
  overtimePremiumRate: number
  statutoryHolidayPremiumRate: number
  transportationType: TransportationType
  transportationAmount: number
  note: string
}

interface WageRuleDto {
  id: number
  employee: number
  effective_from: string
  effective_to: string | null
  hourly_rate: string | number
  night_premium_rate: string | number
  overtime_premium_rate: string | number
  statutory_holiday_premium_rate: string | number
  transportation_type: TransportationType
  transportation_amount: string | number
  note: string
}

function fromWageRuleDto(dto: WageRuleDto): WageRuleRecord {
  return {
    id: String(dto.id),
    employeeId: String(dto.employee),
    effectiveFrom: dto.effective_from,
    effectiveTo: dto.effective_to,
    hourlyRate: Number(dto.hourly_rate),
    nightPremiumRate: Number(dto.night_premium_rate),
    overtimePremiumRate: Number(dto.overtime_premium_rate),
    statutoryHolidayPremiumRate: Number(dto.statutory_holiday_premium_rate),
    transportationType: dto.transportation_type,
    transportationAmount: Number(dto.transportation_amount),
    note: dto.note,
  }
}

function wageRuleToDto(payload: Omit<WageRuleRecord, 'id'>) {
  return {
    employee: Number(payload.employeeId),
    effective_from: payload.effectiveFrom,
    effective_to: payload.effectiveTo,
    hourly_rate: payload.hourlyRate,
    night_premium_rate: payload.nightPremiumRate,
    overtime_premium_rate: payload.overtimePremiumRate,
    statutory_holiday_premium_rate: payload.statutoryHolidayPremiumRate,
    transportation_type: payload.transportationType,
    transportation_amount: payload.transportationAmount,
    note: payload.note,
  }
}

export async function fetchWageRules(employeeId?: string): Promise<WageRuleRecord[]> {
  const query = employeeId ? `?employee=${employeeId}` : ''
  const rows = await http.get<WageRuleDto[]>(`/wage-rules/${query}`)
  return rows.map(fromWageRuleDto)
}

async function saveWageRule(id: string | null, payload: Omit<WageRuleRecord, 'id'>): Promise<WageRuleRecord> {
  try {
    const dto = id
      ? await http.patch<WageRuleDto>(`/wage-rules/${id}/`, wageRuleToDto(payload))
      : await http.post<WageRuleDto>('/wage-rules/', wageRuleToDto(payload))
    return fromWageRuleDto(dto)
  } catch (err) {
    if (err instanceof ApiError) {
      const msgs = err.messages()
      if (msgs.some((m) => m.includes('wage-rule-period-overlap'))) throw new Error('wage-rule-period-overlap')
      if (msgs.some((m) => m.includes('wage-rule-referenced-by-locked-month'))) throw new Error('wage-rule-locked')
    }
    throw err
  }
}

export async function createWageRule(payload: Omit<WageRuleRecord, 'id'>): Promise<WageRuleRecord> {
  return saveWageRule(null, payload)
}

export async function updateWageRule(id: string, payload: Omit<WageRuleRecord, 'id'>): Promise<WageRuleRecord> {
  return saveWageRule(id, payload)
}

export async function deleteWageRule(id: string): Promise<void> {
  try {
    await http.delete(`/wage-rules/${id}/`)
  } catch (err) {
    if (err instanceof ApiError && err.messages().some((m) => m.includes('wage-rule-referenced-by-locked-month'))) {
      throw new Error('wage-rule-locked')
    }
    throw err
  }
}

// ---- Monthly wage closings + per-employee results ------------------------

export type WageClosingStatus = 'draft' | 'confirmed' | 'locked'

export interface WageDailyDetailRecord {
  id: string
  workDate: string
  actualStart: string | null
  actualEnd: string | null
  actualBreakMinutes: number | null
  totalMinutes: number
  hourlyRate: number | null
  regularMinutes: number
  nightMinutes: number
  overtimeMinutes: number
  statutoryHolidayMinutes: number
  baseAmount: number
  nightPremium: number
  overtimePremium: number
  holidayPremium: number
  transportationAmount: number
}

export interface WageEmployeeResultRecord {
  id: string
  closingId: string
  closingMonth: string
  closingStatus: WageClosingStatus
  closingBranchId: string
  closingBranchName: string
  employeeId: string
  employeeName: string
  employmentType: string
  attendanceDays: number
  totalMinutes: number
  /** The effective hourly rate for this result — null when the employee
   * has no wage rule covering the period (e.g. never set up), in which
   * case baseAmount stays 0. Always check for null before formatting. */
  hourlyRate: number | null
  regularMinutes: number
  nightMinutes: number
  overtimeMinutes: number
  statutoryHolidayMinutes: number
  baseAmount: number
  nightPremium: number
  overtimePremium: number
  holidayPremium: number
  transportationAmount: number
  manualAddition: number
  manualDeduction: number
  adjustmentReason: string
  /** null = use ruleTransportationAmount (the WageRule-derived default,
   * always kept current by the server); non-null = this employee's
   * transportation for this month was manually overridden. */
  monthlyTransportationOverride: number | null
  ruleTransportationAmount: number
  transportationOverrideReason: string
  bonusAmount: number
  bonusNote: string
  /** Both null unless an admin/branch has set a special calculation
   * window for this employee this month (e.g. a mid-month departure) —
   * see api docs on the backend for the automatic leave_date default. */
  calculationPeriodStart: string | null
  calculationPeriodEnd: string | null
  estimatedTotal: number
  calculationVersion: string
  dailyDetails: WageDailyDetailRecord[]
}

interface WageDailyDetailDto {
  id: number
  work_date: string
  actual_start: string | null
  actual_end: string | null
  actual_break_minutes: number | null
  total_minutes: number
  hourly_rate: string | number | null
  regular_minutes: number
  night_minutes: number
  overtime_minutes: number
  statutory_holiday_minutes: number
  base_amount: string | number
  night_premium: string | number
  overtime_premium: string | number
  holiday_premium: string | number
  transportation_amount: string | number
}

interface WageEmployeeResultDto {
  id: number
  closing: number
  closing_month: string
  closing_status: WageClosingStatus
  closing_branch_id: string
  closing_branch_name: string
  employee: number
  employee_name: string
  employment_type: string
  attendance_days: number
  total_minutes: number
  hourly_rate: string | number | null
  regular_minutes: number
  night_minutes: number
  overtime_minutes: number
  statutory_holiday_minutes: number
  base_amount: string | number
  night_premium: string | number
  overtime_premium: string | number
  holiday_premium: string | number
  transportation_amount: string | number
  manual_addition: string | number
  manual_deduction: string | number
  adjustment_reason: string
  monthly_transportation_override: string | number | null
  rule_transportation_amount: string | number
  transportation_override_reason: string
  bonus_amount: string | number
  bonus_note: string
  calculation_period_start: string | null
  calculation_period_end: string | null
  estimated_total: string | number
  calculation_version: string
  daily_details: WageDailyDetailDto[]
}

function fromDailyDetailDto(dto: WageDailyDetailDto): WageDailyDetailRecord {
  return {
    id: String(dto.id),
    workDate: dto.work_date,
    actualStart: dto.actual_start,
    actualEnd: dto.actual_end,
    actualBreakMinutes: dto.actual_break_minutes,
    totalMinutes: dto.total_minutes,
    hourlyRate: dto.hourly_rate !== null ? Number(dto.hourly_rate) : null,
    regularMinutes: dto.regular_minutes,
    nightMinutes: dto.night_minutes,
    overtimeMinutes: dto.overtime_minutes,
    statutoryHolidayMinutes: dto.statutory_holiday_minutes,
    baseAmount: Number(dto.base_amount),
    nightPremium: Number(dto.night_premium),
    overtimePremium: Number(dto.overtime_premium),
    holidayPremium: Number(dto.holiday_premium),
    transportationAmount: Number(dto.transportation_amount),
  }
}

function fromResultDto(dto: WageEmployeeResultDto): WageEmployeeResultRecord {
  return {
    id: String(dto.id),
    closingId: String(dto.closing),
    closingMonth: dto.closing_month,
    closingStatus: dto.closing_status,
    closingBranchId: dto.closing_branch_id,
    closingBranchName: dto.closing_branch_name,
    employeeId: String(dto.employee),
    employeeName: dto.employee_name,
    employmentType: dto.employment_type,
    attendanceDays: dto.attendance_days,
    totalMinutes: dto.total_minutes,
    hourlyRate: dto.hourly_rate !== null ? Number(dto.hourly_rate) : null,
    regularMinutes: dto.regular_minutes,
    nightMinutes: dto.night_minutes,
    overtimeMinutes: dto.overtime_minutes,
    statutoryHolidayMinutes: dto.statutory_holiday_minutes,
    baseAmount: Number(dto.base_amount),
    nightPremium: Number(dto.night_premium),
    overtimePremium: Number(dto.overtime_premium),
    holidayPremium: Number(dto.holiday_premium),
    transportationAmount: Number(dto.transportation_amount),
    manualAddition: Number(dto.manual_addition),
    manualDeduction: Number(dto.manual_deduction),
    adjustmentReason: dto.adjustment_reason,
    monthlyTransportationOverride: dto.monthly_transportation_override !== null
      ? Number(dto.monthly_transportation_override) : null,
    ruleTransportationAmount: Number(dto.rule_transportation_amount),
    transportationOverrideReason: dto.transportation_override_reason,
    bonusAmount: Number(dto.bonus_amount),
    bonusNote: dto.bonus_note,
    calculationPeriodStart: dto.calculation_period_start,
    calculationPeriodEnd: dto.calculation_period_end,
    estimatedTotal: Number(dto.estimated_total),
    calculationVersion: dto.calculation_version,
    dailyDetails: (dto.daily_details ?? []).map(fromDailyDetailDto),
  }
}

export interface WageMonthlyClosingRecord {
  id: string
  branchId: string
  branchName: string
  month: string
  status: WageClosingStatus
  confirmedAt: string | null
  lockedAt: string | null
  unlockedAt: string | null
  unlockReason: string
  version: number
  employeeResults: WageEmployeeResultRecord[]
}

interface WageMonthlyClosingDto {
  id: number
  branch: string
  branch_name: string
  month: string
  status: WageClosingStatus
  confirmed_at: string | null
  locked_at: string | null
  unlocked_at: string | null
  unlock_reason: string
  version: number
  employee_results: WageEmployeeResultDto[]
}

function fromClosingDto(dto: WageMonthlyClosingDto): WageMonthlyClosingRecord {
  return {
    id: String(dto.id),
    branchId: dto.branch,
    branchName: dto.branch_name,
    month: dto.month,
    status: dto.status,
    confirmedAt: dto.confirmed_at,
    lockedAt: dto.locked_at,
    unlockedAt: dto.unlocked_at,
    unlockReason: dto.unlock_reason,
    version: dto.version,
    employeeResults: (dto.employee_results ?? []).map(fromResultDto),
  }
}

export async function fetchWageMonthlyClosings(params: { branchId?: string; status?: string } = {}): Promise<WageMonthlyClosingRecord[]> {
  const query = new URLSearchParams()
  if (params.branchId) query.set('branch', params.branchId)
  if (params.status) query.set('status', params.status)
  const rows = await http.get<WageMonthlyClosingDto[]>(`/wage-monthly-closings/?${query.toString()}`)
  return rows.map(fromClosingDto)
}

/** month must be the 1st of the target month, e.g. '2026-08-01'. */
export async function createWageMonthlyClosing(branchId: string, month: string): Promise<WageMonthlyClosingRecord> {
  const dto = await http.post<WageMonthlyClosingDto>('/wage-monthly-closings/', { branch: branchId, month })
  return fromClosingDto(dto)
}

export async function generateWageResults(closingId: string): Promise<WageMonthlyClosingRecord> {
  const dto = await http.post<WageMonthlyClosingDto>(`/wage-monthly-closings/${closingId}/generate/`)
  return fromClosingDto(dto)
}

export interface MissingWageRuleError {
  code: 'missing-wage-rule'
  missing: { employee: string; date: string }[]
}

/** Returned by `confirm` when results were never generated, or when an
 * ActualWorkRecord/WageRule changed after the last `generate` — the caller
 * must re-run `generate` before it can confirm. */
export type ConfirmStaleCode = 'not-generated' | 'stale-actual-records' | 'stale-wage-rule'

export async function confirmWageMonthlyClosing(closingId: string): Promise<WageMonthlyClosingRecord> {
  try {
    const dto = await http.post<WageMonthlyClosingDto>(`/wage-monthly-closings/${closingId}/confirm/`)
    return fromClosingDto(dto)
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      const body = err.body as (MissingWageRuleError | { code: ConfirmStaleCode }) | undefined
      if (body?.code === 'missing-wage-rule') {
        const error = new Error('missing-wage-rule') as Error & { missing: MissingWageRuleError['missing'] }
        error.missing = (body as MissingWageRuleError).missing
        throw error
      }
      if (body?.code === 'not-generated' || body?.code === 'stale-actual-records' || body?.code === 'stale-wage-rule') {
        throw new Error(body.code)
      }
    }
    throw err
  }
}

export async function lockWageMonthlyClosing(closingId: string): Promise<WageMonthlyClosingRecord> {
  const dto = await http.post<WageMonthlyClosingDto>(`/wage-monthly-closings/${closingId}/lock/`)
  return fromClosingDto(dto)
}

export async function unlockWageMonthlyClosing(closingId: string, reason: string): Promise<WageMonthlyClosingRecord> {
  const dto = await http.post<WageMonthlyClosingDto>(`/wage-monthly-closings/${closingId}/unlock/`, { reason })
  return fromClosingDto(dto)
}

export async function unconfirmWageMonthlyClosing(closingId: string, reason: string): Promise<WageMonthlyClosingRecord> {
  const dto = await http.post<WageMonthlyClosingDto>(`/wage-monthly-closings/${closingId}/unconfirm/`, { reason })
  return fromClosingDto(dto)
}

export async function fetchWageEmployeeResults(params: { closingId?: string; employeeId?: string } = {}): Promise<WageEmployeeResultRecord[]> {
  const query = new URLSearchParams()
  if (params.closingId) query.set('closing', params.closingId)
  if (params.employeeId) query.set('employee', params.employeeId)
  const rows = await http.get<WageEmployeeResultDto[]>(`/wage-employee-results/?${query.toString()}`)
  return rows.map(fromResultDto)
}

export async function updateWageEmployeeResultBonus(id: string, payload: {
  bonusAmount: number
  bonusNote: string
}): Promise<WageEmployeeResultRecord> {
  const dto = await http.patch<WageEmployeeResultDto>(`/wage-employee-results/${id}/`, {
    bonus_amount: payload.bonusAmount, bonus_note: payload.bonusNote,
  })
  return fromResultDto(dto)
}

/** Pass `override: null` to clear the override and revert to the rule's
 * default transportation amount. */
export async function updateWageEmployeeResultTransportation(id: string, payload: {
  override: number | null
  reason: string
}): Promise<WageEmployeeResultRecord> {
  const dto = await http.patch<WageEmployeeResultDto>(`/wage-employee-results/${id}/`, {
    monthly_transportation_override: payload.override, transportation_override_reason: payload.reason,
  })
  return fromResultDto(dto)
}

/** Pass both as null to clear the special period and fall back to the
 * automatic default (the full month, capped at the employee's leave_date
 * if it falls mid-month). Both dates must fall inside the closing's own
 * month or the server rejects the request. */
export async function updateWageEmployeeResultCalculationPeriod(id: string, payload: {
  start: string | null
  end: string | null
}): Promise<WageEmployeeResultRecord> {
  const dto = await http.patch<WageEmployeeResultDto>(`/wage-employee-results/${id}/`, {
    calculation_period_start: payload.start, calculation_period_end: payload.end,
  })
  return fromResultDto(dto)
}

export const WAGE_CALCULATION_DISCLAIMER =
  '临时工／时薪员工工资计算资料，不包含所得税、住民税、社会保险、雇用保险等法定扣除，不属于最终工资申报结果。'
