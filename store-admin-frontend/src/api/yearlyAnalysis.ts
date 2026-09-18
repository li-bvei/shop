import { http } from './http'
import type { PaymentMethodAmount, SupplierRankingRow, BranchComparisonRow, Insight } from './monthlyAnalysis'

export interface MonthlyTrendPoint {
  month: string
  revenue: number
  customers: number
  avgSpend: number
  purchasing: number
}

export interface MonthlyDetailRow {
  month: string
  revenue: number
  customers: number
  avgSpend: number
  editCount: number
}

// Field names deliberately mirror MonthlyAnalysis wherever the concept is
// unchanged (see build_yearly_analysis's docstring) so the view layer can
// share one rendering path for both granularities.
export interface YearlyAnalysis {
  year: string
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
  tentativeOperatingGap: number
  daysWithReports: number
  dailyAverageRevenue: number
  highestRevenueDay: { date: string; revenue: number } | null
  lowestRevenueDay: { date: string; revenue: number } | null
  monthlyTrend: MonthlyTrendPoint[]
  paymentMethodBreakdown: PaymentMethodAmount[]
  supplierRanking: SupplierRankingRow[]
  branchComparison: BranchComparisonRow[] | null
  monthlyDetail: MonthlyDetailRow[]
  insights: Insight[]
}

interface YearlyAnalysisDto extends Omit<
  YearlyAnalysis,
  'revenue' | 'previousRevenue' | 'avgSpend' | 'previousAvgSpend' | 'purchasing' | 'previousPurchasing' |
  'expenses' | 'tentativeOperatingGap' | 'dailyAverageRevenue' | 'highestRevenueDay' |
  'lowestRevenueDay' | 'monthlyTrend' | 'paymentMethodBreakdown' | 'supplierRanking' | 'branchComparison' |
  'monthlyDetail'
> {
  revenue: string
  previousRevenue: string
  avgSpend: string
  previousAvgSpend: string
  purchasing: string
  previousPurchasing: string
  expenses: string
  tentativeOperatingGap: string
  dailyAverageRevenue: string
  highestRevenueDay: { date: string; revenue: string } | null
  lowestRevenueDay: { date: string; revenue: string } | null
  monthlyTrend: { month: string; revenue: string; customers: number; avgSpend: string; purchasing: string }[]
  paymentMethodBreakdown: { paymentMethodId: string; amount: string }[]
  supplierRanking: { supplierId: string; supplierName: string; amount: string }[]
  branchComparison: { branchId: string; revenue: string; previousRevenue: string; deltaPct: number | null }[] | null
  monthlyDetail: { month: string; revenue: string; customers: number; avgSpend: string; editCount: number }[]
}

function fromDto(dto: YearlyAnalysisDto): YearlyAnalysis {
  return {
    ...dto,
    revenue: Number(dto.revenue),
    previousRevenue: Number(dto.previousRevenue),
    avgSpend: Number(dto.avgSpend),
    previousAvgSpend: Number(dto.previousAvgSpend),
    purchasing: Number(dto.purchasing),
    previousPurchasing: Number(dto.previousPurchasing),
    expenses: Number(dto.expenses),
    tentativeOperatingGap: Number(dto.tentativeOperatingGap),
    dailyAverageRevenue: Number(dto.dailyAverageRevenue),
    highestRevenueDay: dto.highestRevenueDay
      ? { date: dto.highestRevenueDay.date, revenue: Number(dto.highestRevenueDay.revenue) }
      : null,
    lowestRevenueDay: dto.lowestRevenueDay
      ? { date: dto.lowestRevenueDay.date, revenue: Number(dto.lowestRevenueDay.revenue) }
      : null,
    monthlyTrend: dto.monthlyTrend.map((p) => ({
      month: p.month, revenue: Number(p.revenue), customers: p.customers,
      avgSpend: Number(p.avgSpend), purchasing: Number(p.purchasing),
    })),
    paymentMethodBreakdown: dto.paymentMethodBreakdown.map((p) => ({
      paymentMethodId: p.paymentMethodId, amount: Number(p.amount),
    })),
    supplierRanking: dto.supplierRanking.map((s) => ({
      supplierId: s.supplierId, supplierName: s.supplierName, amount: Number(s.amount),
    })),
    branchComparison: dto.branchComparison
      ? dto.branchComparison.map((b) => ({
          branchId: b.branchId, revenue: Number(b.revenue),
          previousRevenue: Number(b.previousRevenue), deltaPct: b.deltaPct,
        }))
      : null,
    monthlyDetail: dto.monthlyDetail.map((m) => ({
      month: m.month, revenue: Number(m.revenue), customers: m.customers,
      avgSpend: Number(m.avgSpend), editCount: m.editCount,
    })),
  }
}

export async function fetchYearlyAnalysis(year: string, branchId?: string): Promise<YearlyAnalysis> {
  const params = new URLSearchParams({ year })
  if (branchId) params.set('branch', branchId)
  const dto = await http.get<YearlyAnalysisDto>(`/dashboard/yearly-analysis/?${params.toString()}`)
  return fromDto(dto)
}
