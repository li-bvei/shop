import { http } from './http'

export interface Supplier {
  id: string
  name: string
  category: string
  contact: string
  phone: string
  address: string
  bankName: string
  bankNameFurigana: string
  branchName: string
  branchNameFurigana: string
  accountType: string
  accountNumber: string
  accountHolderFurigana: string
  note: string
  /** Manual override for this month's payable amount; null means auto-sum from purchase records. */
  payableOverride: number | null
  /** Server-computed sum of this month's purchase records for this supplier (DB-side aggregate) — used whenever payableOverride is null. */
  monthlyPayable: number
}

interface SupplierDto {
  id: number
  name: string
  category: string
  contact: string
  phone: string
  address: string
  bank_name: string
  bank_name_furigana: string
  branch_name: string
  branch_name_furigana: string
  account_type: string
  account_number: string
  account_holder_furigana: string
  note: string
  payable_override: number | null
  monthly_payable: number
}

function fromDto(dto: SupplierDto): Supplier {
  return {
    id: String(dto.id),
    name: dto.name,
    category: dto.category,
    contact: dto.contact,
    phone: dto.phone,
    address: dto.address,
    bankName: dto.bank_name,
    bankNameFurigana: dto.bank_name_furigana,
    branchName: dto.branch_name,
    branchNameFurigana: dto.branch_name_furigana,
    accountType: dto.account_type,
    accountNumber: dto.account_number,
    accountHolderFurigana: dto.account_holder_furigana,
    note: dto.note,
    payableOverride: dto.payable_override,
    monthlyPayable: dto.monthly_payable,
  }
}

function toDto(payload: Omit<Supplier, 'id' | 'monthlyPayable'>) {
  return {
    name: payload.name,
    category: payload.category,
    contact: payload.contact,
    phone: payload.phone,
    address: payload.address,
    bank_name: payload.bankName,
    bank_name_furigana: payload.bankNameFurigana,
    branch_name: payload.branchName,
    branch_name_furigana: payload.branchNameFurigana,
    account_type: payload.accountType,
    account_number: payload.accountNumber,
    account_holder_furigana: payload.accountHolderFurigana,
    note: payload.note,
    payable_override: payload.payableOverride,
  }
}

export async function fetchSuppliers(params: { month?: string; branchId?: string } = {}): Promise<Supplier[]> {
  const query = new URLSearchParams()
  if (params.month) query.set('month', params.month)
  if (params.branchId) query.set('branch', params.branchId)
  const rows = await http.get<SupplierDto[]>(`/suppliers/?${query}`)
  return rows.map(fromDto)
}

// monthlyPayable is server-computed (a DB-side sum of purchase records —
// see SupplierSerializer.get_monthly_payable), never something a create/
// update request supplies.
export async function createSupplier(payload: Omit<Supplier, 'id' | 'monthlyPayable'>): Promise<Supplier> {
  const dto = await http.post<SupplierDto>('/suppliers/', toDto(payload))
  return fromDto(dto)
}

export async function updateSupplier(id: string, payload: Omit<Supplier, 'id' | 'monthlyPayable'>): Promise<void> {
  await http.patch(`/suppliers/${id}/`, toDto(payload))
}

export async function deleteSupplier(id: string): Promise<void> {
  await http.delete(`/suppliers/${id}/`)
}

export async function setSupplierPayableOverride(
  id: string,
  value: number | null,
  month: string,
  branchId?: string,
): Promise<void> {
  const query = new URLSearchParams({ month })
  if (branchId) query.set('branch', branchId)
  await http.patch(`/suppliers/${id}/monthly-payable/?${query}`, { amount: value })
}
