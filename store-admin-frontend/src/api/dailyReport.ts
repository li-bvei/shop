import { http } from './http'
import {
  createEmptyCashRegisterCounts,
  normalizeDailyReportFormData,
  type DailyReportFormData,
} from '@/components/DailyReportForm.vue'

export interface DailyReportSeed extends DailyReportFormData {
  /** null when no report has ever been saved for this branch+date yet. */
  id: number | null
}

const EMPTY_SEED: DailyReportFormData = normalizeDailyReportFormData({
  cashRegisterCounts: createEmptyCashRegisterCounts(),
})

interface DailyReportDto {
  id: number
  branch: string
  date: string
  person_in_charge: number | null
  total_revenue: string | number
  total_customers: number
  group_count: number
  morning_revenue: string | number
  morning_customers: number
  morning_group_count: number
  payment_amounts: Record<string, number>
  expenses: DailyReportFormData['expenses']
  cash_register_counts?: Record<string, number>
}

function fromDto(dto: DailyReportDto): DailyReportSeed {
  return {
    id: dto.id,
    ...normalizeDailyReportFormData({
      personInCharge: dto.person_in_charge != null ? String(dto.person_in_charge) : '',
      totalRevenue: Number(dto.total_revenue),
      totalCustomers: dto.total_customers,
      groupCount: dto.group_count,
      morningRevenue: Number(dto.morning_revenue),
      morningCustomers: dto.morning_customers,
      morningGroupCount: dto.morning_group_count,
      paymentAmounts: dto.payment_amounts,
      expenses: dto.expenses,
      cashRegisterCounts: dto.cash_register_counts,
    }),
  }
}

function numericOrZero(value: number | null) {
  return value ?? 0
}

function toDto(branchId: string, date: string, data: DailyReportFormData) {
  return {
    date,
    // Branch-role accounts omit this on create — BranchScopedQuerysetMixin
    // fills it in server-side; on update it's implied by the row's own id.
    ...(branchId ? { branch: branchId } : {}),
    person_in_charge: data.personInCharge ? Number(data.personInCharge) : null,
    total_revenue: numericOrZero(data.totalRevenue),
    total_customers: numericOrZero(data.totalCustomers),
    group_count: numericOrZero(data.groupCount),
    morning_revenue: numericOrZero(data.morningRevenue),
    morning_customers: numericOrZero(data.morningCustomers),
    morning_group_count: numericOrZero(data.morningGroupCount),
    payment_amounts: Object.fromEntries(
      Object.entries(data.paymentAmounts).map(([key, value]) => [key, numericOrZero(value)]),
    ),
    expenses: data.expenses.map((expense) => ({ ...expense, amount: numericOrZero(expense.amount) })),
    cash_register_counts: Object.fromEntries(
      Object.entries({ ...createEmptyCashRegisterCounts(), ...data.cashRegisterCounts })
        .map(([key, value]) => [key, numericOrZero(value)]),
    ),
  }
}

export async function fetchDailyReport(branchId: string, date: string): Promise<DailyReportSeed> {
  const params = new URLSearchParams({ branch: branchId, date })
  const rows = await http.get<DailyReportDto[]>(`/daily-reports/?${params.toString()}`)
  return rows[0] ? fromDto(rows[0]) : { ...EMPTY_SEED, id: null }
}

/** Upserts the branch+date's live report; returns its id (new or existing). */
export async function saveDailyReport(
  id: number | null,
  branchId: string,
  date: string,
  data: DailyReportFormData,
): Promise<number> {
  if (id) {
    await http.patch(`/daily-reports/${id}/`, toDto(branchId, date, data))
    return id
  }
  const created = await http.post<DailyReportDto>('/daily-reports/', toDto(branchId, date, data))
  return created.id
}

export interface DailyReportHistoryEntry {
  id: string
  branchId: string
  date: string
  savedAt: string
  editedBy: string
  personInCharge: string
  totalRevenue: number
  cashRemaining: number
  data: DailyReportFormData
}

interface HistoryDto {
  id: number
  branch: string
  date: string
  saved_at: string
  edited_by_name: string
  person_in_charge: number | null
  total_revenue: string | number
  cash_remaining: string | number
  data: DailyReportFormData
}

function fromHistoryDto(dto: HistoryDto): DailyReportHistoryEntry {
  return {
    id: String(dto.id),
    branchId: dto.branch,
    date: dto.date,
    savedAt: dto.saved_at,
    editedBy: dto.edited_by_name,
    personInCharge: dto.person_in_charge != null ? String(dto.person_in_charge) : '',
    totalRevenue: Number(dto.total_revenue),
    cashRemaining: Number(dto.cash_remaining),
    data: normalizeDailyReportFormData(dto.data),
  }
}

export async function fetchDailyReportHistory(branchId: string, date: string): Promise<DailyReportHistoryEntry[]> {
  const params = new URLSearchParams({ branch: branchId, date })
  const rows = await http.get<HistoryDto[]>(`/daily-report-history/?${params.toString()}`)
  return rows.map(fromHistoryDto).sort((a, b) => (a.savedAt < b.savedAt ? 1 : -1))
}

export interface SaveHistorySnapshotPayload {
  branchId: string
  date: string
  cashRemaining: number
  data: DailyReportFormData
}

/** Append-only — edited_by/saved_at are always set server-side from the
 * authenticated request, never trusted from the client. */
export async function saveDailyReportHistorySnapshot(payload: SaveHistorySnapshotPayload): Promise<void> {
  await http.post('/daily-report-history/', {
    ...(payload.branchId ? { branch: payload.branchId } : {}),
    date: payload.date,
    person_in_charge: payload.data.personInCharge ? Number(payload.data.personInCharge) : null,
    total_revenue: payload.data.totalRevenue,
    cash_remaining: payload.cashRemaining,
    data: payload.data,
  })
}
