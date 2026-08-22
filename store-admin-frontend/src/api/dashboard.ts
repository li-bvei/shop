import { http } from './http'

export interface DailyRevenuePoint {
  date: string
  revenue: number
}

export interface BranchRevenue {
  branchId: string
  revenue: number
}

export interface DashboardSummary {
  todayRevenue: number
  todayRevenueDeltaPct: number
  customerCount: number
  customerCountDelta: number
  avgSpend: number
  avgSpendDeltaPct: number
  monthlyPurchasing: number
  monthlyPurchasingDeltaPct: number
  revenueTrend: DailyRevenuePoint[]
  branchRevenueToday: BranchRevenue[]
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  return http.get<DashboardSummary>('/dashboard/summary/')
}
