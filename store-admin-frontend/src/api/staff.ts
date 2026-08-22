import { http, ApiError } from './http'

export type EmploymentType = 'regular_monthly' | 'hourly' | 'temporary'
export type WorkArea = 'kitchen' | 'hall'

export interface StaffWageSetting {
  hourlyRate: number
  transportationAmount: number
  effectiveFrom: string
  note: string
}

export interface StaffMember {
  id: string
  branchId: string
  name: string
  role: string
  workArea: WorkArea
  phone: string
  status: 'active' | 'inactive'
  employmentType: EmploymentType
  hireDate: string | null
  leaveDate: string | null
  note: string
  wageSetting: StaffWageSetting | null
}

interface StaffDto {
  id: number
  branch: string
  name: string
  role: string
  work_area: WorkArea
  phone: string
  status: 'active' | 'inactive'
  employment_type: EmploymentType
  hire_date: string | null
  leave_date: string | null
  note: string
  wage_setting: {
    hourly_rate: string | number
    transportation_amount: string | number
    effective_from: string
    note: string
  } | null
}

function fromDto(dto: StaffDto): StaffMember {
  return {
    id: String(dto.id),
    branchId: dto.branch,
    name: dto.name,
    role: dto.role,
    workArea: dto.work_area,
    phone: dto.phone,
    status: dto.status,
    employmentType: dto.employment_type,
    hireDate: dto.hire_date,
    leaveDate: dto.leave_date,
    note: dto.note,
    wageSetting: dto.wage_setting ? {
      hourlyRate: Number(dto.wage_setting.hourly_rate),
      transportationAmount: Number(dto.wage_setting.transportation_amount),
      effectiveFrom: dto.wage_setting.effective_from,
      note: dto.wage_setting.note,
    } : null,
  }
}

function toDto(payload: Omit<StaffMember, 'id'>) {
  return {
    branch: payload.branchId,
    name: payload.name,
    role: payload.role,
    work_area: payload.workArea,
    phone: payload.phone,
    status: payload.status,
    employment_type: payload.employmentType,
    hire_date: payload.hireDate,
    leave_date: payload.leaveDate,
    note: payload.note,
    wage_setting: payload.wageSetting ? {
      hourly_rate: payload.wageSetting.hourlyRate,
      transportation_amount: payload.wageSetting.transportationAmount,
      effective_from: payload.wageSetting.effectiveFrom,
      note: payload.wageSetting.note,
    } : null,
  }
}

export async function fetchAllStaff(): Promise<StaffMember[]> {
  const rows = await http.get<StaffDto[]>('/staff/')
  return rows.map(fromDto)
}

export async function fetchStaffByBranch(branchId: string): Promise<StaffMember[]> {
  const params = new URLSearchParams({ branch: branchId, status: 'active' })
  const rows = await http.get<StaffDto[]>(`/staff/?${params.toString()}`)
  return rows.map(fromDto)
}

export async function createStaff(payload: Omit<StaffMember, 'id'>): Promise<StaffMember> {
  const dto = await http.post<StaffDto>('/staff/', toDto(payload))
  return fromDto(dto)
}

export async function updateStaff(id: string, payload: Omit<StaffMember, 'id'>): Promise<void> {
  await http.patch(`/staff/${id}/`, toDto(payload))
}

export async function deleteStaff(id: string): Promise<void> {
  await http.delete(`/staff/${id}/`)
}

export interface StaffTransfer {
  id: string
  employeeId: string
  employeeName: string
  fromBranchId: string
  fromBranchName: string
  toBranchId: string
  toBranchName: string
  effectiveDate: string
  reason: string
  changedByName: string | null
  changedAt: string
}

interface StaffTransferDto {
  id: number
  employee: number
  employee_name: string
  from_branch: string
  from_branch_name: string
  to_branch: string
  to_branch_name: string
  effective_date: string
  reason: string
  changed_by_name: string | null
  changed_at: string
}

function fromTransferDto(dto: StaffTransferDto): StaffTransfer {
  return {
    id: String(dto.id),
    employeeId: String(dto.employee),
    employeeName: dto.employee_name,
    fromBranchId: dto.from_branch,
    fromBranchName: dto.from_branch_name,
    toBranchId: dto.to_branch,
    toBranchName: dto.to_branch_name,
    effectiveDate: dto.effective_date,
    reason: dto.reason,
    changedByName: dto.changed_by_name,
    changedAt: dto.changed_at,
  }
}

export interface TransferConflictShift {
  id: number
  workDate: string
  periodId: number
}

export class TransferHasFutureShiftsError extends Error {
  shifts: TransferConflictShift[]
  constructor(shifts: { id: number; work_date: string; period_id: number }[]) {
    super('has-future-shifts-at-old-branch')
    this.shifts = shifts.map((s) => ({ id: s.id, workDate: s.work_date, periodId: s.period_id }))
  }
}

export async function fetchStaffTransfers(employeeId?: string): Promise<StaffTransfer[]> {
  const params = employeeId ? `?${new URLSearchParams({ employee: employeeId }).toString()}` : ''
  const rows = await http.get<StaffTransferDto[]>(`/staff-transfers/${params}`)
  return rows.map(fromTransferDto)
}

export async function createStaffTransfer(payload: {
  employeeId: string
  toBranchId: string
  effectiveDate: string
  reason: string
  force?: boolean
}): Promise<StaffTransfer> {
  try {
    const dto = await http.post<StaffTransferDto>('/staff-transfers/', {
      employee: payload.employeeId,
      to_branch: payload.toBranchId,
      effective_date: payload.effectiveDate,
      reason: payload.reason,
      force: payload.force ?? false,
    })
    return fromTransferDto(dto)
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      const body = err.body as { code?: string; shifts?: { id: number; work_date: string; period_id: number }[] }
      if (body?.code === 'has-future-shifts-at-old-branch') {
        throw new TransferHasFutureShiftsError(body.shifts ?? [])
      }
    }
    throw err
  }
}
