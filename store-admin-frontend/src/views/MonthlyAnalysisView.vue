<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import { Download } from '@element-plus/icons-vue'
import { fetchMonthlyAnalysis, type MonthlyAnalysis } from '@/api/monthlyAnalysis'
import { fetchYearlyAnalysis, type YearlyAnalysis } from '@/api/yearlyAnalysis'
import { fetchPaymentMethods } from '@/api/masterData'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { formatCurrency, formatNumber, branchDisplayName, todayJst, formatMonthKanji } from '@/utils/format'
import { useChartTheme } from '@/composables/useChartTheme'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { downloadCustomExcel } from '@/utils/excelExport'
import { renderOffscreenToPdf } from '@/utils/pdfExport'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const branchStore = useBranchStore()
const chartTheme = useChartTheme()
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

const kpis = computed(() => {
  const a = analysis.value
  if (!a) return []
  return [
    { label: t('monthlyAnalysis.revenue'), value: formatCurrency(a.revenue), delta: deltaText(a.revenueDeltaPct), up: (a.revenueDeltaPct ?? 0) >= 0 },
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
        formatter: (params: { name: string; percent: number }) => (
          params.percent >= PIE_LABEL_MIN_SHARE_PCT ? params.name : ''
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

async function handleDownload() {
  const branchText = currentBranchLabel()

  if (viewMode.value === 'month') {
    const a = monthlyAnalysis.value
    if (!a) return
    await downloadCustomExcel(
      `月度经营-${branchText}-${selectedMonth.value}`,
      t('monthlyAnalysis.pageTitle'),
      (ws) => {
        const summaryRows: [string, string | number][] = [
          [t('monthlyAnalysis.revenue'), a.revenue],
          [t('monthlyAnalysis.customers'), a.customers],
          [t('monthlyAnalysis.avgSpend'), a.avgSpend],
          [t('monthlyAnalysis.purchasing'), a.purchasing],
          [t('monthlyAnalysis.expenses'), a.expenses],
          [t('monthlyAnalysis.tentativeOperatingGap'), a.tentativeOperatingGap],
          [t('monthlyAnalysis.daysWithReports'), a.daysWithReports],
        ]
        ws.addRow([branchText, selectedMonth.value])
        ws.getRow(1).font = { bold: true, size: 13 }
        ws.addRow([])
        for (const [label, value] of summaryRows) {
          const row = ws.addRow([label, value])
          row.getCell(1).font = { bold: true }
        }
        ws.addRow([])

        const headerRow = ws.addRow([
          '日期',
          isAdmin.value ? t('monthlyAnalysis.branch') : null,
          t('monthlyAnalysis.revenue'),
          t('monthlyAnalysis.customers'),
          t('monthlyAnalysis.avgSpend'),
          t('monthlyAnalysis.editCount'),
        ].filter((v) => v !== null))
        headerRow.font = { bold: true }
        headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } }

        for (const row of a.dailyDetail) {
          const cells = [row.date, isAdmin.value ? branchName(row.branchId) : null, row.revenue, row.customers, row.avgSpend, row.editCount]
            .filter((v) => v !== null)
          ws.addRow(cells)
        }
        ws.columns.forEach((col) => { col.width = 16 })
      },
    )
  } else {
    const a = yearlyAnalysis.value
    if (!a) return
    await downloadCustomExcel(
      `年度经营-${branchText}-${selectedYear.value}`,
      t('monthlyAnalysis.pageTitle'),
      (ws) => {
        const summaryRows: [string, string | number][] = [
          [t('monthlyAnalysis.revenue'), a.revenue],
          [t('monthlyAnalysis.customers'), a.customers],
          [t('monthlyAnalysis.avgSpend'), a.avgSpend],
          [t('monthlyAnalysis.purchasing'), a.purchasing],
          [t('monthlyAnalysis.expenses'), a.expenses],
          [t('monthlyAnalysis.tentativeOperatingGap'), a.tentativeOperatingGap],
          [t('monthlyAnalysis.daysWithReports'), a.daysWithReports],
        ]
        ws.addRow([branchText, selectedYear.value])
        ws.getRow(1).font = { bold: true, size: 13 }
        ws.addRow([])
        for (const [label, value] of summaryRows) {
          const row = ws.addRow([label, value])
          row.getCell(1).font = { bold: true }
        }
        ws.addRow([])

        const headerRow = ws.addRow([
          '月份', t('monthlyAnalysis.revenue'), t('monthlyAnalysis.customers'),
          t('monthlyAnalysis.avgSpend'), t('monthlyAnalysis.editCount'),
        ])
        headerRow.font = { bold: true }
        headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } }

        for (const row of a.monthlyDetail) {
          ws.addRow([row.month, row.revenue, row.customers, row.avgSpend, row.editCount])
        }
        ws.columns.forEach((col) => { col.width = 16 })
      },
    )
  }
}

const pdfDownloading = ref(false)

// A compact, hand-built tabular document (same el()-builder approach as
// SuppliersView.vue's PDF) rather than a screenshot of the live dashboard —
// the on-screen page is several charts tall, which would force a single
// shrink-to-fit A4 page down to illegible text; a report is meant for the
// numbers, not the chart pixels.
const PDF_PAGE_WIDTH_PX = 794

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  styles: Partial<CSSStyleDeclaration>,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  Object.assign(node.style, styles)
  if (text !== undefined) node.textContent = text
  return node
}

async function handleDownloadPdf() {
  const a = analysis.value
  if (!a) return
  pdfDownloading.value = true
  try {
    const branchText = currentBranchLabel()
    const periodLabel = viewMode.value === 'month' ? formatMonthKanji(selectedMonth.value) : `${selectedYear.value}年`
    const suffix = viewMode.value === 'month' ? t('monthlyAnalysis.pdfSuffixMonthly') : t('monthlyAnalysis.pdfSuffixYearly')
    const filename = `${periodLabel}_${branchText}_${suffix}`

    await renderOffscreenToPdf(filename, PDF_PAGE_WIDTH_PX, (root) => {
      root.style.padding = '28px 32px'
      root.style.fontFamily = '"Hiragino Sans", "Microsoft YaHei", sans-serif'
      root.style.color = '#1a1a1a'

      const header = el('div', { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '14px' })
      header.appendChild(el('div', { fontSize: '18px', fontWeight: '700' }, `${periodLabel} ${branchText} ${suffix}`))
      header.appendChild(el('div', { fontSize: '11px', color: '#666' }, todayJst()))
      root.appendChild(header)

      const summaryGrid = el('div', {
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '16px',
        fontSize: '11px', border: '1px solid #ddd', padding: '10px 12px',
      })
      const summaryItems: [string, string][] = [
        [t('monthlyAnalysis.revenue'), formatCurrency(a.revenue)],
        [t('monthlyAnalysis.customers'), formatNumber(a.customers)],
        [t('monthlyAnalysis.avgSpend'), formatCurrency(a.avgSpend)],
        [t('monthlyAnalysis.purchasing'), formatCurrency(a.purchasing)],
        [t('monthlyAnalysis.expenses'), formatCurrency(a.expenses)],
        [t('monthlyAnalysis.tentativeOperatingGap'), formatCurrency(a.tentativeOperatingGap)],
        [t('monthlyAnalysis.daysWithReports'), String(a.daysWithReports)],
        [t('monthlyAnalysis.dailyAverageRevenue'), formatCurrency(a.dailyAverageRevenue)],
      ]
      for (const [label, value] of summaryItems) {
        const cell = el('div', {})
        cell.appendChild(el('div', { color: '#888', fontSize: '9px', marginBottom: '2px' }, label))
        cell.appendChild(el('div', { fontWeight: '700' }, value))
        summaryGrid.appendChild(cell)
      }
      root.appendChild(summaryGrid)

      const sectionTitle = (text: string) => el('div', { fontSize: '12px', fontWeight: '700', margin: '14px 0 6px' }, text)

      root.appendChild(sectionTitle(t('monthlyAnalysis.paymentMethodChart')))
      const pmTable = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '10px', marginBottom: '8px' })
      for (const row of paymentMethodRows.value) {
        const tr = document.createElement('tr')
        tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd' }, row.name))
        tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd', textAlign: 'right' }, formatCurrency(row.amount)))
        tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd', textAlign: 'right', width: '50px', color: '#666' }, `${row.pct.toFixed(1)}%`))
        pmTable.appendChild(tr)
      }
      root.appendChild(pmTable)

      root.appendChild(sectionTitle(t('monthlyAnalysis.supplierRankingChart')))
      const supplierTable = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '10px', marginBottom: '8px' })
      for (const row of a.supplierRanking.slice(0, 15)) {
        const tr = document.createElement('tr')
        tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd' }, row.supplierName))
        tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd', textAlign: 'right' }, formatCurrency(row.amount)))
        supplierTable.appendChild(tr)
      }
      root.appendChild(supplierTable)

      const detailTitle = viewMode.value === 'month' ? t('monthlyAnalysis.dailyDetailTitle') : t('monthlyAnalysis.monthlyDetailTitle')
      root.appendChild(sectionTitle(detailTitle))
      const detailTable = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '9.5px', tableLayout: 'fixed' })
      const thead = document.createElement('thead')
      const headRow = document.createElement('tr')
      const columns = [
        viewMode.value === 'month' ? '日期' : '月份',
        t('monthlyAnalysis.revenue'), t('monthlyAnalysis.customers'), t('monthlyAnalysis.avgSpend'), t('monthlyAnalysis.editCount'),
      ]
      for (const label of columns) {
        headRow.appendChild(el('th', { padding: '4px 6px', borderBottom: '1.5px solid #333', textAlign: 'left', fontWeight: '700' }, label))
      }
      thead.appendChild(headRow)
      detailTable.appendChild(thead)
      const tbody = document.createElement('tbody')
      const detailRows = viewMode.value === 'month'
        ? (monthlyAnalysis.value?.dailyDetail ?? []).map((r) => [r.date, formatCurrency(r.revenue), String(r.customers), formatCurrency(r.avgSpend), String(r.editCount)])
        : (yearlyAnalysis.value?.monthlyDetail ?? []).map((r) => [r.month, formatCurrency(r.revenue), String(r.customers), formatCurrency(r.avgSpend), String(r.editCount)])
      detailRows.forEach((cells, index) => {
        const tr = document.createElement('tr')
        if (index % 2 === 1) tr.style.backgroundColor = '#f7f7f7'
        for (const cellText of cells) {
          tr.appendChild(el('td', { padding: '3px 6px', borderBottom: '0.5px solid #ddd' }, cellText))
        }
        tbody.appendChild(tr)
      })
      detailTable.appendChild(tbody)
      root.appendChild(detailTable)
    })
  } finally {
    pdfDownloading.value = false
  }
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
      <div class="filter-actions">
        <el-button :icon="Download" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
        <el-button :icon="Download" :loading="pdfDownloading" @click="handleDownloadPdf">{{ t('common.downloadPdf') }}</el-button>
      </div>
    </div>

    <template v-if="analysis">
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
            <el-table-column label="日期" prop="date" width="110" />
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
            <el-table-column :label="t('monthlyAnalysis.editCount')" prop="editCount" width="100" />
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
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.editCount') }}</span><span>{{ row.editCount }}</span></div>
          </div>
          <p v-if="!monthlyAnalysis.dailyDetail.length" class="empty-hint">{{ t('monthlyAnalysis.noData') }}</p>
        </div>
      </div>

      <div v-else-if="yearlyAnalysis" class="card">
        <h3>{{ t('monthlyAnalysis.monthlyDetailTitle') }}</h3>
        <div class="table-scroll desktop-table">
          <el-table :data="yearlyAnalysis.monthlyDetail" class="detail-table">
            <el-table-column label="月份" prop="month" width="110" />
            <el-table-column :label="t('monthlyAnalysis.revenue')" width="120">
              <template #default="{ row }">{{ formatCurrency(row.revenue) }}</template>
            </el-table-column>
            <el-table-column :label="t('monthlyAnalysis.customers')" prop="customers" width="90" />
            <el-table-column :label="t('monthlyAnalysis.avgSpend')" width="100">
              <template #default="{ row }">{{ formatCurrency(row.avgSpend) }}</template>
            </el-table-column>
            <el-table-column :label="t('monthlyAnalysis.editCount')" prop="editCount" width="100" />
          </el-table>
        </div>
        <div class="mobile-cards">
          <div v-for="row in yearlyAnalysis.monthlyDetail" :key="row.month" class="detail-card">
            <div class="detail-card-head"><span>{{ row.month }}</span></div>
            <div class="detail-card-revenue">{{ formatCurrency(row.revenue) }}</div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.customers') }}</span><span>{{ row.customers }}</span></div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.avgSpend') }}</span><span>{{ formatCurrency(row.avgSpend) }}</span></div>
            <div class="detail-card-row"><span>{{ t('monthlyAnalysis.editCount') }}</span><span>{{ row.editCount }}</span></div>
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

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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
  font-size: 12.5px;
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
  font-size: 12.5px;
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
  font-size: 12.5px;
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
}

</style>
