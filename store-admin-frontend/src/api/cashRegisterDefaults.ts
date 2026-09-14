import { http } from './http'

// The register's small-denomination float (500/100/50/10/5 yen) and its レジ
// 固定金額 (expected total) barely change day to day — this lets a branch
// set them once and have new daily reports pre-fill from it instead of
// re-entering the same counts every day. Editing these never rewrites an
// already-saved DailyReport — only the still-blank fields on a fresh one
// get pre-filled (see DailyReportForm.vue).
//
// Kept in its own file, not api/dailyReport.ts, to avoid a circular import:
// dailyReport.ts already imports types from components/DailyReportForm.vue,
// which is what calls the functions below.

export interface CashRegisterDefaults {
  denominationDefaults: Record<string, number>
  expectedTotal: number
}

interface CashRegisterDefaultsDto {
  denomination_defaults: Record<string, number>
  expected_total: number
}

function fromDto(dto: CashRegisterDefaultsDto): CashRegisterDefaults {
  return { denominationDefaults: dto.denomination_defaults, expectedTotal: dto.expected_total }
}

export async function fetchCashRegisterDefaults(branchId: string): Promise<CashRegisterDefaults> {
  const params = new URLSearchParams({ branch: branchId })
  return fromDto(await http.get<CashRegisterDefaultsDto>(`/cash-register-defaults/?${params.toString()}`))
}

export async function updateCashRegisterDefaults(
  branchId: string,
  payload: Partial<{ denominationDefaults: Record<string, number>; expectedTotal: number }>,
): Promise<CashRegisterDefaults> {
  const params = new URLSearchParams({ branch: branchId })
  const body: Record<string, unknown> = {}
  if (payload.denominationDefaults !== undefined) body.denomination_defaults = payload.denominationDefaults
  if (payload.expectedTotal !== undefined) body.expected_total = payload.expectedTotal
  return fromDto(await http.patch<CashRegisterDefaultsDto>(`/cash-register-defaults/?${params.toString()}`, body))
}
