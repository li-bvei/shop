import { http } from './http'

export interface DailyTrendPoint {
  date: string
  revenue: number
  customers: number
  avgSpend: number
  purchasing: number
}

export interface PaymentMethodAmount {
  paymentMethodId: string
  amount: number
}

export interface SupplierRankingRow {
  supplierId: string
  supplierName: string
  amount: number
}

export interface WeekdayAverage {
  weekday: number
  nameZh: string
  nameJa: string
  averageRevenue: number | null
}

export interface BranchComparisonRow {
  branchId: string
  revenue: number
  previousRevenue: number
  deltaPct: number | null
}

export interface DailyDetailRow {
  date: string
  branchId: string
  revenue: number
  customers: number
  avgSpend: number
  editCount: number
}

export type InsightSeverity = 'info' | 'notice'

export interface Insight {
  rule: string
  severity: InsightSeverity
  message: string
  threshold: number | null
  value: number | null
}

export type WageStatus = 'not_generated' | 'draft' | 'confirmed' | 'partially_locked' | 'locked'

export interface MonthlyAnalysis {
  month: string
  revenue: number
  previousRevenue: number
  revenueDeltaPct: number | null
  customers: number
  previousCustomers: number
  customersDeltaPct: number | null
  avgSpend: number
  previousAvgSpend: number
  avgSpendDeltaPct: number | null
  purchasing: number
  previousPurchasing: number
  purchasingDeltaPct: number | null
  expenses: number
  wageTotal: number
  wageStatus: WageStatus
  tentativeOperatingGap: number
  daysWithReports: number
  dailyAverageRevenue: number
  highestRevenueDay: { date: string; revenue: number } | null
  lowestRevenueDay: { date: string; revenue: number } | null
  dailyTrend: DailyTrendPoint[]
  paymentMethodBreakdown: PaymentMethodAmount[]
  supplierRanking: SupplierRankingRow[]
  weekdayAverages: WeekdayAverage[]
  branchComparison: BranchComparisonRow[] | null
  dailyDetail: DailyDetailRow[]
  insights: Insight[]
}

interface MonthlyAnalysisDto extends Omit<
  MonthlyAnalysis,
  'revenue' | 'previousRevenue' | 'avgSpend' | 'previousAvgSpend' | 'purchasing' | 'previousPurchasing' |
  'expenses' | 'wageTotal' | 'tentativeOperatingGap' | 'dailyAverageRevenue' | 'highestRevenueDay' |
  'lowestRevenueDay' | 'dailyTrend' | 'paymentMethodBreakdown' | 'supplierRanking' | 'weekdayAverages' |
  'branchComparison'
> {
  revenue: string
  previousRevenue: string
  avgSpend: string
  previousAvgSpend: string
  purchasing: string
  previousPurchasing: string
  expenses: string
  wageTotal: string
  tentativeOperatingGap: string
  dailyAverageRevenue: string
  highestRevenueDay: { date: string; revenue: string } | null
  lowestRevenueDay: { date: string; revenue: string } | null
  dailyTrend: { date: string; revenue: string; customers: number; avgSpend: string; purchasing: string }[]
  paymentMethodBreakdown: { paymentMethodId: string; amount: string }[]
  supplierRanking: { supplierId: string; supplierName: string; amount: string }[]
  weekdayAverages: { weekday: number; nameZh: string; nameJa: string; averageRevenue: string | null }[]
  branchComparison: { branchId: string; revenue: string; previousRevenue: string; deltaPct: number | null }[] | null
}

function fromDto(dto: MonthlyAnalysisDto): MonthlyAnalysis {
  return {
    ...dto,
    revenue: Number(dto.revenue),
    previousRevenue: Number(dto.previousRevenue),
    avgSpend: Number(dto.avgSpend),
    previousAvgSpend: Number(dto.previousAvgSpend),
    purchasing: Number(dto.purchasing),
    previousPurchasing: Number(dto.previousPurchasing),
    expenses: Number(dto.expenses),
    wageTotal: Number(dto.wageTotal),
    tentativeOperatingGap: Number(dto.tentativeOperatingGap),
    dailyAverageRevenue: Number(dto.dailyAverageRevenue),
    highestRevenueDay: dto.highestRevenueDay
      ? { date: dto.highestRevenueDay.date, revenue: Number(dto.highestRevenueDay.revenue) }
      : null,
    lowestRevenueDay: dto.lowestRevenueDay
      ? { date: dto.lowestRevenueDay.date, revenue: Number(dto.lowestRevenueDay.revenue) }
      : null,
    dailyTrend: dto.dailyTrend.map((p) => ({
      date: p.date, revenue: Number(p.revenue), customers: p.customers,
      avgSpend: Number(p.avgSpend), purchasing: Number(p.purchasing),
    })),
    paymentMethodBreakdown: dto.paymentMethodBreakdown.map((p) => ({
      paymentMethodId: p.paymentMethodId, amount: Number(p.amount),
    })),
    supplierRanking: dto.supplierRanking.map((s) => ({
      supplierId: s.supplierId, supplierName: s.supplierName, amount: Number(s.amount),
    })),
    weekdayAverages: dto.weekdayAverages.map((w) => ({
      weekday: w.weekday, nameZh: w.nameZh, nameJa: w.nameJa,
      averageRevenue: w.averageRevenue !== null ? Number(w.averageRevenue) : null,
    })),
    branchComparison: dto.branchComparison
      ? dto.branchComparison.map((b) => ({
          branchId: b.branchId, revenue: Number(b.revenue),
          previousRevenue: Number(b.previousRevenue), deltaPct: b.deltaPct,
        }))
      : null,
  }
}

export async function fetchMonthlyAnalysis(month: string, branchId?: string): Promise<MonthlyAnalysis> {
  const params = new URLSearchParams({ month })
  if (branchId) params.set('branch', branchId)
  const dto = await http.get<MonthlyAnalysisDto>(`/dashboard/monthly-analysis/?${params.toString()}`)
  return fromDto(dto)
}
