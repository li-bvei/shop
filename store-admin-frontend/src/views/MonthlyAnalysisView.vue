<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import type ExcelJS from 'exceljs'
import { Download, Printer } from '@element-plus/icons-vue'
import { fetchMonthlyAnalysis, type MonthlyAnalysis } from '@/api/monthlyAnalysis'
import { fetchYearlyAnalysis, type YearlyAnalysis } from '@/api/yearlyAnalysis'
import { fetchPaymentMethods } from '@/api/masterData'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import {
  formatCurrency, formatNumber, branchDisplayName, todayJst, formatMonthKanji,
  excelAmount, EXCEL_CURRENCY_FORMAT, EXCEL_COUNT_FORMAT,
} from '@/utils/format'
import { useChartTheme } from '@/composables/useChartTheme'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { useIsMobile } from '@/composables/useIsMobile'
import { usePagedDocumentPrint } from '@/composables/usePagedDocumentPrint'
import { applyA4PageSetup, downloadCustomExcel } from '@/utils/excelExport'
import { renderOffscreenPagesToPdf } from '@/utils/pdfExport'
import {
  ANALYSIS_REPORT_PAGE_WIDTH_PX, buildAnalysisReportPages,
  type AnalysisReportCell, type AnalysisReportDocument,
} from '@/utils/reports/analysisReport'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const branchStore = useBranchStore()
const chartTheme = useChartTheme()
const isMobile = useIsMobile()
const isAdmin = computed(() => auth.role === 'admin')

const viewMode = ref<'month' | 'year'>('month')
const selectedMonth = ref(todayJst().slice(0, 7))
const selectedYear = ref(todayJst().slice(0, 4))
const selectedBranchId = ref(auth.branchId ?? '')
const { loading, run } = useDelayedLoading()
const monthlyAnalysis = ref<MonthlyAnalysis | null>(null)
const yearlyAnalysis = ref<YearlyAnalysis | null>(null)
// Fields shared by both shapes (see build_yearly_analysis's docstring on the
// backend for why the names line up) — this lets the KPI/payment/supplier/
// insights sections below read from one place regardless of viewMode.
const analysis = computed<MonthlyAnalysis | YearlyAnalysis | null>(() => (
  viewMode.value === 'month' ? monthlyAnalysis.value : yearlyAnalysis.value
))
const paymentMethodNames = ref<Record<string, string>>({})

function paymentMethodLabel(id: string) {
  return paymentMethodNames.value[id] ?? id
}

async function loadPaymentMethodNames() {
  const branchIds = isAdmin.value && !selectedBranchId.value
    ? branchStore.list.map((b) => b.id)
    : [isAdmin.value ? selectedBranchId.value : (auth.branchId ?? '')].filter(Boolean)
  const lists = await Promise.all(branchIds.map((id) => fetchPaymentMethods(id)))
  const names: Record<string, string> = {}
  for (const list of lists) {
    for (const method of list) {
      names[String(method.id)] = method.customName || (method.i18nKey ? t(method.i18nKey) : String(method.id))
    }
  }
  paymentMethodNames.value = names
}

async function load() {
  await run(async () => {
    const branchId = isAdmin.value ? (selectedBranchId.value || undefined) : (auth.branchId ?? undefined)
    if (viewMode.value === 'month') {
      monthlyAnalysis.value = await fetchMonthlyAnalysis(selectedMonth.value, branchId)
    } else {
      yearlyAnalysis.value = await fetchYearlyAnalysis(selectedYear.value, branchId)
    }
    await loadPaymentMethodNames()
  })
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  await load()
})
watch([viewMode, selectedMonth, selectedYear, selectedBranchId], load)

function deltaText(pct: number | null) {
  if (pct === null) return '—'
  const suffix = viewMode.value === 'month' ? t('monthlyAnalysis.vsLastMonth') : t('monthlyAnalysis.vsLastYear')
  return `${pct >= 0 ? '↑' : '↓'} ${Math.abs(pct)}% ${suffix}`
}

function branchName(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

// 营业额 is the number everyone actually opens this page to check — a
// dedicated, larger hero card makes that the visual entry point instead of
// competing equally with customers/avgSpend/purchasing for attention.
const revenueKpi = computed(() => {
  const a = analysis.value
  if (!a) return null
  return { label: t('monthlyAnalysis.revenue'), value: formatCurrency(a.revenue), delta: deltaText(a.revenueDeltaPct), up: (a.revenueDeltaPct ?? 0) >= 0 }
})

const kpis = computed(() => {
  const a = analysis.value
  if (!a) return []
  return [
    { label: t('monthlyAnalysis.customers'), value: formatNumber(a.customers), delta: deltaText(a.customersDeltaPct), up: (a.customersDeltaPct ?? 0) >= 0 },
    { label: t('monthlyAnalysis.avgSpend'), value: formatCurrency(a.avgSpend), delta: deltaText(a.avgSpendDeltaPct), up: (a.avgSpendDeltaPct ?? 0) >= 0 },
    { label: t('monthlyAnalysis.purchasing'), value: formatCurrency(a.purchasing), delta: deltaText(a.purchasingDeltaPct), up: (a.purchasingDeltaPct ?? 0) >= 0 },
  ]
})

const secondaryStats = computed(() => {
  const a = analysis.value
  if (!a) return []
  return [
    { label: t('monthlyAnalysis.expenses'), value: formatCurrency(a.expenses) },
    { label: t('monthlyAnalysis.tentativeOperatingGap'), value: formatCurrency(a.tentativeOperatingGap) },
    { label: t('monthlyAnalysis.daysWithReports'), value: String(a.daysWithReports) },
    { label: t('monthlyAnalysis.dailyAverageRevenue'), value: formatCurrency(a.dailyAverageRevenue) },
  ]
})

const trendOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const points = viewMode.value === 'month'
    ? (monthlyAnalysis.value?.dailyTrend ?? []).map((p) => ({ label: p.date.slice(5), revenue: p.revenue, purchasing: p.purchasing }))
    : (yearlyAnalysis.value?.monthlyTrend ?? []).map((p) => ({ label: `${Number(p.month.slice(5))}月`, revenue: p.revenue, purchasing: p.purchasing }))
  return {
    grid: { left: 8, right: 40, top: 24, bottom: 24, containLabel: true },
    legend: { top: 0, textStyle: { color: theme.textSecondary, fontSize: 11 } },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category', data: points.map((p) => p.label), boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axisLine } }, axisTick: { show: false },
      axisLabel: { color: theme.textTertiary, fontSize: 10, interval: viewMode.value === 'month' ? 2 : 0 },
    },
    yAxis: [{ type: 'value', show: false }, { type: 'value', show: false }],
    series: [
      {
        name: t('monthlyAnalysis.revenue'), type: 'line', data: points.map((p) => p.revenue), smooth: true,
        showSymbol: false, lineStyle: { color: theme.accent, width: 2.5 },
      },
      {
        name: t('monthlyAnalysis.purchasing'), type: 'bar', yAxisIndex: 1, data: points.map((p) => p.purchasing),
        itemStyle: { color: theme.accentSoft },
      },
    ],
  }
})

// Every payment method gets a slice regardless of size (hovering still shows
// its exact amount), but a label is only drawn when its share is large
// enough to read without overlapping its neighbors — the list below the
// chart is where every method's exact share is always visible.
const PIE_LABEL_MIN_SHARE_PCT = 8

const paymentMethodRows = computed(() => {
  const rows = analysis.value?.paymentMethodBreakdown ?? []
  const total = rows.reduce((sum, r) => sum + r.amount, 0)
  return rows
    .map((r) => ({
      id: r.paymentMethodId,
      name: paymentMethodLabel(r.paymentMethodId),
      amount: r.amount,
      pct: total > 0 ? (r.amount / total) * 100 : 0,
    }))
    .sort((a, b) => b.amount - a.amount)
})

const paymentMethodOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  return {
    tooltip: { trigger: 'item', valueFormatter: (v) => formatCurrency(v as number) },
    legend: { show: false },
    series: [{
      type: 'pie', radius: ['45%', '70%'], avoidLabelOverlap: true,
      label: {
        color: theme.textSecondary, fontSize: 11,
        formatter: (params: { name?: string; percent?: number }) => (
          (params.percent ?? 0) >= PIE_LABEL_MIN_SHARE_PCT ? (params.name ?? '') : ''
        ),
      },
      data: paymentMethodRows.value.map((r) => ({ name: r.name, value: r.amount })),
    }],
  }
})

const weekdayOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const rows = monthlyAnalysis.value?.weekdayAverages ?? []
  const names = locale.value === 'ja' ? rows.map((r) => r.nameJa) : rows.map((r) => r.nameZh)
  return {
    grid: { left: 8, right: 12, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: (v) => formatCurrency(v as number) },
    xAxis: { type: 'category', data: names, axisLine: { lineStyle: { color: theme.axisLine } }, axisLabel: { color: theme.textSecondary, fontSize: 11 } },
    yAxis: { type: 'value', show: false },
    series: [{ type: 'bar', data: rows.map((r) => r.averageRevenue ?? 0), itemStyle: { color: theme.accent, borderRadius: 4 } }],
  }
})

function goToDailyReport(date: string, branchId: string) {
  router.push({ name: 'daily-report', query: { date, branch: branchId } })
}

function currentBranchLabel() {
  return isAdmin.value && !selectedBranchId.value
    ? t('monthlyAnalysis.allBranches')
    : branchName(isAdmin.value ? selectedBranchId.value : (auth.branchId ?? ''))
}

// --- Report document ------------------------------------------------------
// One description of the report, built once and rendered to all three
// destinations (PDF download, print, Excel) so they can't disagree about
// content, pagination, titles or how an amount reads. Amounts stay raw
// numbers right up to the point each destination renders them — PDF/print
// through analysisReport's accounting cells, Excel into numeric cells with
// an accounting number format — so no destination ever receives a
// pre-formatted string it can no longer calculate with.

/** Period label used in headings and filenames: "2026年9月" / "2026年". */
const periodLabel = computed(() => (
  viewMode.value === 'month' ? formatMonthKanji(selectedMonth.value) : `${selectedYear.value}年`
))

const reportTypeText = computed(() => (
  viewMode.value === 'month' ? t('monthlyAnalysis.pdfSuffixMonthly') : t('monthlyAnalysis.pdfSuffixYearly')
))

/** Shared by the PDF download and the print dialog's "Save as PDF" name, so
 * both routes produce an identically named file. */
const reportFileName = computed(() => (
  `${periodLabel.value}_${currentBranchLabel()}_${reportTypeText.value}`
))

/** The detail table differs only in its leading column (date vs month) and
 * in which analysis supplies the rows — everything else about the report is
 * identical between the two view modes, which is why they share this view. */
function detailTableSpec() {
  const amount = { align: 'right' as const }
  const common = [
    { label: t('monthlyAnalysis.revenue'), ...amount },
    { label: t('monthlyAnalysis.customers'), ...amount },
    { label: t('monthlyAnalysis.avgSpend'), ...amount },
  ]
  if (viewMode.value === 'month') {
    return {
      title: t('monthlyAnalysis.dailyDetailTitle'),
      columns: [{ label: t('monthlyAnalysis.detailDateColumn'), align: 'left' as const }, ...common],
      rows: (monthlyAnalysis.value?.dailyDetail ?? []).map((r): AnalysisReportCell[] => [
        { kind: 'text', text: r.date },
        { kind: 'currency', value: r.revenue, bold: true },
        { kind: 'count', value: r.customers },
        { kind: 'currency', value: r.avgSpend },
      ]),
    }
  }
  return {
    title: t('monthlyAnalysis.monthlyDetailTitle'),
    columns: [{ label: t('monthlyAnalysis.detailMonthColumn'), align: 'left' as const }, ...common],
    rows: (yearlyAnalysis.value?.monthlyDetail ?? []).map((r): AnalysisReportCell[] => [
      { kind: 'text', text: r.month },
      { kind: 'currency', value: r.revenue, bold: true },
      { kind: 'count', value: r.customers },
      { kind: 'currency', value: r.avgSpend },
    ]),
  }
}

function buildReportDocument(a: MonthlyAnalysis | YearlyAnalysis): AnalysisReportDocument {
  const detail = detailTableSpec()
  return {
    titleText: `${currentBranchLabel()}　${periodLabel.value}`,
    reportTypeText: reportTypeText.value,
    hero: { label: t('monthlyAnalysis.revenue'), value: a.revenue },
    summary: [
      { label: t('monthlyAnalysis.customers'), cell: { kind: 'count', value: a.customers } },
      { label: t('monthlyAnalysis.avgSpend'), cell: { kind: 'currency', value: a.avgSpend } },
      { label: t('monthlyAnalysis.purchasing'), cell: { kind: 'currency', value: a.purchasing } },
      { label: t('monthlyAnalysis.expenses'), cell: { kind: 'currency', value: a.expenses } },
      { label: t('monthlyAnalysis.tentativeOperatingGap'), cell: { kind: 'currency', value: a.tentativeOperatingGap } },
      { label: t('monthlyAnalysis.daysWithReports'), cell: { kind: 'count', value: a.daysWithReports } },
      { label: t('monthlyAnalysis.dailyAverageRevenue'), cell: { kind: 'currency', value: a.dailyAverageRevenue } },
    ],
    sections: [
      {
        kind: 'list',
        title: t('monthlyAnalysis.paymentMethodChart'),
        rows: paymentMethodRows.value.map((r): AnalysisReportCell[] => [
          { kind: 'text', text: r.name, bold: true },
          { kind: 'currency', value: r.amount, bold: true },
          { kind: 'ratio', text: `${r.pct.toFixed(1)}%` },
        ]),
      },
      {
        kind: 'list',
        title: t('monthlyAnalysis.supplierRankingChart'),
        rows: a.supplierRanking.slice(0, PDF_SUPPLIER_LIMIT).map((r): AnalysisReportCell[] => [
          { kind: 'text', text: r.supplierName, bold: true },
          { kind: 'currency', value: r.amount, bold: true },
        ]),
      },
      { kind: 'table', title: detail.title, columns: detail.columns, rows: detail.rows },
    ],
    emptyText: t('monthlyAnalysis.noData'),
  }
}

/** The supplier ranking is a "top N" by design, on screen and in every
 * export — the full list belongs to the purchasing module, not to a
 * one-page business summary. */
const PDF_SUPPLIER_LIMIT = 15

// --- Excel ----------------------------------------------------------------

/** Writes one `label | amount` row with the amount as a real number in an
 * accounting-formatted cell. Never a formatted string: a string column
 * can't be summed, charted or re-formatted by whoever opens the workbook,
 * which is the whole reason to export a spreadsheet rather than a PDF. */
function addExcelAmountRow(ws: ExcelJS.Worksheet, label: string, cell: AnalysisReportCell) {
  const raw = cell.kind === 'currency' || cell.kind === 'count' ? excelAmount(cell.value) : null
  const row = ws.addRow([label, raw])
  row.getCell(1).font = { bold: true }
  const valueCell = row.getCell(2)
  valueCell.numFmt = cell.kind === 'count' ? EXCEL_COUNT_FORMAT : EXCEL_CURRENCY_FORMAT
  valueCell.alignment = { horizontal: 'right' }
}

function addExcelHeaderRow(ws: ExcelJS.Worksheet, columns: { label: string; align: 'left' | 'right' }[]) {
  const row = ws.addRow(columns.map((c) => c.label))
  row.font = { bold: true }
  row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } }
  columns.forEach((c, i) => { row.getCell(i + 1).alignment = { horizontal: c.align } })
}

// Building a 31-day workbook with three sheets takes long enough on a phone
// to look like a dead button, so Excel gets the same in-progress state the
// PDF download already had.
const excelDownloading = ref(false)

async function handleDownload() {
  const a = analysis.value
  if (!a) return
  excelDownloading.value = true
  try {
    await writeExcelWorkbook(a)
  } finally {
    excelDownloading.value = false
  }
}

async function writeExcelWorkbook(a: MonthlyAnalysis | YearlyAnalysis) {
  const doc = buildReportDocument(a)
  const detail = detailTableSpec()
  const branchText = currentBranchLabel()
  const periodKey = viewMode.value === 'month' ? selectedMonth.value : selectedYear.value

  await downloadCustomExcel(
    `${viewMode.value === 'month' ? '月度经营' : '年度经营'}-${branchText}-${periodKey}`,
    t('monthlyAnalysis.pageTitle'),
    (ws) => {
      // Same heading / hero / summary / detail order as the PDF, so the two
      // files read as the same report in two formats.
      ws.addRow([doc.titleText, doc.reportTypeText])
      ws.getRow(1).font = { bold: true, size: 13 }
      ws.addRow([])
      addExcelAmountRow(ws, doc.hero.label, { kind: 'currency', value: doc.hero.value })
      for (const item of doc.summary) addExcelAmountRow(ws, item.label, item.cell)
      ws.addRow([])

      // Admin viewing every branch at once needs the branch column to tell
      // the rows apart; a branch account's rows are all its own.
      const showBranch = isAdmin.value && viewMode.value === 'month'
      const detailColumns = showBranch
        ? [detail.columns[0]!, { label: t('monthlyAnalysis.branch'), align: 'left' as const }, ...detail.columns.slice(1)]
        : detail.columns
      addExcelHeaderRow(ws, detailColumns)

      const sourceRows = viewMode.value === 'month'
        ? (monthlyAnalysis.value?.dailyDetail ?? []).map((r) => ({
            key: r.date, branchId: r.branchId, revenue: r.revenue, customers: r.customers, avgSpend: r.avgSpend,
          }))
        : (yearlyAnalysis.value?.monthlyDetail ?? []).map((r) => ({
            key: r.month, branchId: '', revenue: r.revenue, customers: r.customers, avgSpend: r.avgSpend,
          }))

      for (const r of sourceRows) {
        const row = ws.addRow([
          r.key,
          ...(showBranch ? [branchName(r.branchId)] : []),
          excelAmount(r.revenue), excelAmount(r.customers), excelAmount(r.avgSpend),
        ])
        const firstAmountColumn = showBranch ? 3 : 2
        row.getCell(firstAmountColumn).numFmt = EXCEL_CURRENCY_FORMAT
        row.getCell(firstAmountColumn + 1).numFmt = EXCEL_COUNT_FORMAT
        row.getCell(firstAmountColumn + 2).numFmt = EXCEL_CURRENCY_FORMAT
        for (let i = firstAmountColumn; i <= firstAmountColumn + 2; i += 1) {
          row.getCell(i).alignment = { horizontal: 'right' }
        }
      }

      // Payment-method and supplier breakdowns get their own sheets rather
      // than being appended under the detail table — on one sheet their
      // columns would have to share the detail table's widths and header,
      // and a reader could no longer sort or total either list on its own.
      const paymentSheet = ws.workbook.addWorksheet(t('monthlyAnalysis.paymentMethodChart'))
      addExcelHeaderRow(paymentSheet, [
        { label: t('monthlyAnalysis.paymentMethodChart'), align: 'left' },
        { label: t('monthlyAnalysis.revenue'), align: 'right' },
        { label: t('monthlyAnalysis.paymentMethodShare'), align: 'right' },
      ])
      for (const r of paymentMethodRows.value) {
        const row = paymentSheet.addRow([r.name, excelAmount(r.amount), r.pct / 100])
        row.getCell(2).numFmt = EXCEL_CURRENCY_FORMAT
        row.getCell(3).numFmt = '0.0%'
        row.getCell(2).alignment = { horizontal: 'right' }
        row.getCell(3).alignment = { horizontal: 'right' }
      }
      paymentSheet.columns.forEach((col) => { col.width = 22 })
      applyA4PageSetup(paymentSheet)

      const supplierSheet = ws.workbook.addWorksheet(t('monthlyAnalysis.supplierRankingChart'))
      addExcelHeaderRow(supplierSheet, [
        { label: t('monthlyAnalysis.supplierRankingChart'), align: 'left' },
        { label: t('monthlyAnalysis.purchasing'), align: 'right' },
      ])
      for (const r of a.supplierRanking.slice(0, PDF_SUPPLIER_LIMIT)) {
        const row = supplierSheet.addRow([r.supplierName, excelAmount(r.amount)])
        row.getCell(2).numFmt = EXCEL_CURRENCY_FORMAT
        row.getCell(2).alignment = { horizontal: 'right' }
      }
      supplierSheet.columns.forEach((col) => { col.width = 26 })
      applyA4PageSetup(supplierSheet)

      // Wide enough for a long branch/supplier name and a 9-digit amount,
      // so a cell shows its value rather than Excel's ### overflow marker.
      ws.columns.forEach((col) => { col.width = 20 })
    },
  )
}

// --- PDF and print --------------------------------------------------------

const pdfDownloading = ref(false)
const { printing, printPagedDocument } = usePagedDocumentPrint(ANALYSIS_REPORT_PAGE_WIDTH_PX)

async function handleDownloadPdf() {
  const a = analysis.value
  if (!a) return
  pdfDownloading.value = true
  try {
    await renderOffscreenPagesToPdf(
      reportFileName.value,
      ANALYSIS_REPORT_PAGE_WIDTH_PX,
      (addPage) => buildAnalysisReportPages(addPage, buildReportDocument(a)),
    )
  } finally {
    pdfDownloading.value = false
  }
}

/** Prints the exact document handleDownloadPdf writes — same builder, same
 * pagination, same amount formatting — never the live page, which would
 * otherwise print the filter bar, the charts and the editable controls. */
async function handlePrint() {
  const a = analysis.value
  if (!a) return
  await printPagedDocument(
    reportFileName.value,
    (addPage) => buildAnalysisReportPages(addPage, buildReportDocument(a)),
  )
}

</script>

<template>
  <div class="monthly-analysis-view" v-loading="loading">
    <div class="card filter-card">
      <div class="filter-controls">
        <el-radio-group v-model="viewMode" size="default">
          <el-radio-button value="month">{{ t('monthlyAnalysis.viewModeMonth') }}</el-radio-button>
          <el-radio-button value="year">{{ t('monthlyAnalysis.viewModeYear') }}</el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-if="viewMode === 'month'" v-model="selectedMonth" type="month" value-format="YYYY-MM"
          style="width: 160px" :clearable="false"
        />
        <el-date-picker
          v-else v-model="selectedYear" type="year" value-format="YYYY"
          style="width: 160px" :clearable="false"
        />
        <el-select v-if="isAdmin" v-model="selectedBranchId" style="width: 160px" :placeholder="t('monthlyAnalysis.allBranches')" clearable>
          <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
        </el-select>
        <span v-else class="branch-badge">{{ branchName(auth.branchId ?? '') }}</span>
      </div>
      <!-- Print / Excel / PDF are one group of equal-weight export actions,
           in the same order and with the same icons and labels as the daily
           report's, so the two pages' export bars read identically. On a
           phone they become a three-up grid of full-height buttons: each
           keeps a 44px tap target and its own label never has to share a
           line with a neighbour, which is what used to squash them. -->
      <div class="filter-actions no-print" :class="{ 'is-mobile': isMobile }">
        <el-button :icon="Printer" :loading="printing" @click="handlePrint">
          {{ t(isMobile ? 'common.printShort' : 'common.print') }}
        </el-button>
        <el-button :icon="Download" :loading="excelDownloading" @click="handleDownload">
          {{ t(isMobile ? 'common.downloadExcelShort' : 'common.downloadExcel') }}
        </el-button>
        <el-button :icon="Download" :loading="pdfDownloading" @click="handleDownloadPdf">
          {{ t(isMobile ? 'common.downloadPdfShort' : 'common.downloadPdf') }}
        </el-button>
      </div>
    </div>

    <template v-if="analysis">
      <div v-if="revenueKpi" class="revenue-hero">
        <div class="label">{{ revenueKpi.label }}</div>
        <div class="value">{{ revenueKpi.value }}</div>
        <div class="delta" :class="revenueKpi.up ? 'up' : 'down'">{{ revenueKpi.delta }}</div>
      </div>

      <div class="kpi-grid">
        <div v-for="kpi in kpis" :key="kpi.label" class="kpi-card">
          <div class="label">{{ kpi.label }}</div>
          <div class="value">{{ kpi.value }}</div>
          <div class="delta" :class="kpi.up ? 'up' : 'down'">{{ kpi.delta }}</div>
        </div>
      </div>

      <div class="secondary-grid">
        <div v-for="s in secondaryStats" :key="s.label" class="secondary-card">
          <span class="label">{{ s.label }}</span>
          <span class="value">{{ s.value }}</span>
        </div>
      </div>
      <p class="gap-hint">{{ t('monthlyAnalysis.tentativeOperatingGapHint') }}</p>

      <div class="grid-2col">
        <div class="card chart-card">
          <h3>{{ viewMode === 'month' ? t('monthlyAnalysis.dailyTrendChart') : t('monthlyAnalysis.monthlyTrendChart') }}</h3>
          <v-chart class="chart" :option="trendOption" autoresize />
        </div>
        <div class="card chart-card">
          <h3>{{ t('monthlyAnalysis.paymentMethodChart') }}</h3>
          <v-chart class="chart" :option="paymentMethodOption" autoresize />
          <div class="payment-method-list">
            <div v-for="row in paymentMethodRows" :key="row.id" class="payment-method-row">
              <span class="payment-method-name">{{ row.name }}</span>
              <span class="payment-method-amount">{{ formatCurrency(row.amount) }}</span>
              <span class="payment-method-pct">{{ row.pct.toFixed(1) }}%</span>
            </div>
            <p v-if="!paymentMethodRows.length" class="empty-hint">{{ t('monthlyAnalysis.noData') }}</p>
          </div>
        </div>
      </div>

      <div class="grid-2col">
        <div v-if="viewMode === 'month'" class="card chart-card">
          <h3>{{ t('monthlyAnalysis.weekdayAverageChart') }}</h3>
          <v-chart class="chart" :option="weekdayOption" autoresize />
        </div>
        <div class="card chart-card">
          <h3>{{ t('monthlyAnalysis.supplierRankingChart') }}</h3>
          <div class="supplier-list">
            <div v-for="s in analysis.supplierRanking.slice(0, 8)" :key="s.supplierId" class="supplier-row">
              <span class="supplier-name">{{ s.supplierName }}</span>
              <span class="supplier-amount">{{ formatCurrency(s.amount) }}</span>
            </div>
            <p v-if="!analysis.supplierRanking.length" class="empty-hint">{{ t('monthlyAnalysis.noData') }}</p>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>{{ t('monthlyAnalysis.insightsTitle') }}</h3>
        <ul class="insights-list">
          <li v-for="(insight, i) in analysis.insights" :key="i" :class="insight.severity">
            {{ insight.message }}
          </li>
          <li v-if="!analysis.insights.length" class="empty-hint">{{ t('monthlyAnalysis.insufficientData') }}</li>
        </ul>
      </div>

      <div v-if="viewMode === 'month' && monthlyAnalysis" class="card">
        <h3>{{ t('monthlyAnalysis.dailyDetailTitle') }}</h3>
        <div class="table-scroll desktop-table">
          <el-table :data="monthlyAnalysis.dailyDetail" @row-click="(row: any) => goToDailyReport(row.date, row.branchId)" class="detail-table">
            <el-table-column :label="t('monthlyAnalysis.detailDateColumn')" prop="date" width="110" />
            <el-table-column v-if="isAdmin" label="分店" width="110">
              <template #default="{ row }">{{ branchName(row.branchId) }}</template>
            </el-table-column>
            <el-table-column :label="t('monthlyAnalysis.revenue')" width="120">
              <template #default="{ row }">{{ formatCurrency(row.revenue) }}</template>
            </el-table-column>
            <el-table-column :label="t('monthlyAnalysis.customers')" prop="customers" width="90" />
            <el-table-column :label="t('monthlyAnalysis.avgSpend')" width="100">
              <template #default="{ row }">{{ formatCurrency(row.avgSpend) }}</template>
            </el-table-column>
          </el-table>
        </div>
        <div class="mobile-cards">
          <div
            v-for="row in monthlyAnalysis.dailyDetail" :key="`${row.date}-${row.branchId}`"
            class="detail-card" @click="goToDailyReport(row.date, row.branchId)"
          >
            <div class="detail-card-head">
              <span>{{ row.date }}</span>
              <span v-if="isAdmin" class="detail-card-branch">{{ branchName(row.branchId) }}</span>
            </div>
            <div class="detail-card-revenue">{{ formatCurrency(row.revenue) }}</div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.customers') }}</span><span>{{ row.customers }}</span></div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.avgSpend') }}</span><span>{{ formatCurrency(row.avgSpend) }}</span></div>
          </div>
          <p v-if="!monthlyAnalysis.dailyDetail.length" class="empty-hint">{{ t('monthlyAnalysis.noData') }}</p>
        </div>
      </div>

      <div v-else-if="yearlyAnalysis" class="card">
        <h3>{{ t('monthlyAnalysis.monthlyDetailTitle') }}</h3>
        <div class="table-scroll desktop-table">
          <el-table :data="yearlyAnalysis.monthlyDetail" class="detail-table">
            <el-table-column :label="t('monthlyAnalysis.detailMonthColumn')" prop="month" width="110" />
            <el-table-column :label="t('monthlyAnalysis.revenue')" width="120">
              <template #default="{ row }">{{ formatCurrency(row.revenue) }}</template>
            </el-table-column>
            <el-table-column :label="t('monthlyAnalysis.customers')" prop="customers" width="90" />
            <el-table-column :label="t('monthlyAnalysis.avgSpend')" width="100">
              <template #default="{ row }">{{ formatCurrency(row.avgSpend) }}</template>
            </el-table-column>
          </el-table>
        </div>
        <div class="mobile-cards">
          <div v-for="row in yearlyAnalysis.monthlyDetail" :key="row.month" class="detail-card">
            <div class="detail-card-head"><span>{{ row.month }}</span></div>
            <div class="detail-card-revenue">{{ formatCurrency(row.revenue) }}</div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.customers') }}</span><span>{{ row.customers }}</span></div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.avgSpend') }}</span><span>{{ formatCurrency(row.avgSpend) }}</span></div>
          </div>
          <p v-if="!yearlyAnalysis.monthlyDetail.length" class="empty-hint">{{ t('monthlyAnalysis.noData') }}</p>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
.filter-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.filter-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

/* Phone: the three export actions share the full width as equal columns
   rather than wrapping unpredictably (two on one line, one orphaned on the
   next, which is what a long Japanese label used to cause). Each button
   keeps a 44px tap target, and `min-width: 0` on the grid children is what
   actually lets them shrink inside the grid instead of overflowing it —
   Element Plus buttons have their own min-width. */
.filter-actions.is-mobile {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  width: 100%;
}

.filter-actions.is-mobile :deep(.el-button) {
  width: 100%;
  min-width: 0;
  height: 44px;
  margin-left: 0;
  padding-left: 6px;
  padding-right: 6px;
}

/* A label that can't fit beside its icon wraps onto a second line inside
   the button instead of being clipped — the button grows, the text stays
   readable. */
.filter-actions.is-mobile :deep(.el-button > span) {
  white-space: normal;
  line-height: 1.15;
  text-align: center;
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

.revenue-hero {
  background: linear-gradient(135deg, var(--accent-light) 0%, var(--surface) 75%);
  border-radius: var(--radius-md);
  padding: 24px 28px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.revenue-hero .label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.revenue-hero .value {
  font-size: 42px;
  font-weight: 700;
  color: var(--accent);
  line-height: 1.1;
  letter-spacing: -0.01em;
}

.revenue-hero .delta {
  font-size: 13px;
  margin-top: 10px;
  font-weight: 600;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

.kpi-card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 18px 18px 16px;
  box-shadow: var(--shadow-soft);
}

.kpi-card .label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.kpi-card .value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.kpi-card .delta {
  font-size: 12px;
  margin-top: 6px;
  font-weight: 600;
}

.delta.up {
  color: var(--success);
}

.delta.down {
  color: var(--danger);
}

.secondary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 6px;
}

.secondary-card {
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  box-shadow: var(--shadow-soft);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.secondary-card .label {
  color: var(--text-secondary);
}

.secondary-card .value {
  font-weight: 600;
  color: var(--text-primary);
}

.gap-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 0 0 14px;
}

.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}

.chart-card h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 16px;
  color: var(--text-primary);
}

.chart {
  height: 220px;
}

.payment-method-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.payment-method-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.payment-method-name {
  flex: 1;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.payment-method-amount {
  font-weight: 600;
  color: var(--text-primary);
}

.payment-method-pct {
  color: var(--text-tertiary);
  min-width: 44px;
  text-align: right;
}

.supplier-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.supplier-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
}

.supplier-amount {
  font-weight: 600;
  color: var(--text-primary);
}

.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.card h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 14px;
  color: var(--text-primary);
}

.insights-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.insights-list li.notice {
  color: var(--text-primary);
  font-weight: 500;
}

.empty-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
}

.table-scroll {
  overflow-x: auto;
}

.detail-table :deep(.el-table__row) {
  cursor: pointer;
}

.mobile-cards {
  display: none;
}

.detail-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
}

.detail-card-head {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.detail-card-branch {
  color: var(--text-tertiary);
}

.detail-card-revenue {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.detail-card-row {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  color: var(--text-secondary);
  padding: 2px 0;
}

.detail-card-row span:last-child {
  color: var(--text-primary);
}

@media (max-width: 960px) {
  .kpi-grid,
  .secondary-grid,
  .grid-2col {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .desktop-table {
    display: none;
  }

  .mobile-cards {
    display: block;
  }
}

@media (max-width: 600px) {
  .kpi-grid,
  .secondary-grid,
  .grid-2col {
    grid-template-columns: 1fr;
  }

  .revenue-hero .value {
    font-size: 32px;
  }
}

</style>
