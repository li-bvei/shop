<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import { Download } from '@element-plus/icons-vue'
import { fetchMonthlyAnalysis, type MonthlyAnalysis } from '@/api/monthlyAnalysis'
import { fetchPaymentMethods } from '@/api/masterData'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { formatCurrency, formatNumber, branchDisplayName, todayJst } from '@/utils/format'
import { useChartTheme } from '@/composables/useChartTheme'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { downloadCustomExcel } from '@/utils/excelExport'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const branchStore = useBranchStore()
const chartTheme = useChartTheme()
const isAdmin = computed(() => auth.role === 'admin')

const selectedMonth = ref(todayJst().slice(0, 7))
const selectedBranchId = ref(auth.branchId ?? '')
const { loading, run } = useDelayedLoading()
const analysis = ref<MonthlyAnalysis | null>(null)
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
    analysis.value = await fetchMonthlyAnalysis(
      selectedMonth.value,
      isAdmin.value ? (selectedBranchId.value || undefined) : (auth.branchId ?? undefined),
    )
    await loadPaymentMethodNames()
  })
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  await load()
})
watch([selectedMonth, selectedBranchId], load)

function deltaText(pct: number | null) {
  if (pct === null) return '—'
  return `${pct >= 0 ? '↑' : '↓'} ${Math.abs(pct)}% ${t('monthlyAnalysis.vsLastMonth')}`
}

function branchName(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

const kpis = computed(() => {
  if (!analysis.value) return []
  const a = analysis.value
  return [
    { label: t('monthlyAnalysis.revenue'), value: formatCurrency(a.revenue), delta: deltaText(a.revenueDeltaPct), up: (a.revenueDeltaPct ?? 0) >= 0 },
    { label: t('monthlyAnalysis.customers'), value: formatNumber(a.customers), delta: deltaText(a.customersDeltaPct), up: (a.customersDeltaPct ?? 0) >= 0 },
    { label: t('monthlyAnalysis.avgSpend'), value: formatCurrency(a.avgSpend), delta: deltaText(a.avgSpendDeltaPct), up: (a.avgSpendDeltaPct ?? 0) >= 0 },
    { label: t('monthlyAnalysis.purchasing'), value: formatCurrency(a.purchasing), delta: deltaText(a.purchasingDeltaPct), up: (a.purchasingDeltaPct ?? 0) >= 0 },
  ]
})

const secondaryStats = computed(() => {
  if (!analysis.value) return []
  const a = analysis.value
  return [
    { label: t('monthlyAnalysis.expenses'), value: formatCurrency(a.expenses) },
    { label: t('monthlyAnalysis.wageTotal'), value: formatCurrency(a.wageTotal) },
    { label: t('monthlyAnalysis.tentativeOperatingGap'), value: formatCurrency(a.tentativeOperatingGap) },
    { label: t('monthlyAnalysis.daysWithReports'), value: String(a.daysWithReports) },
    { label: t('monthlyAnalysis.dailyAverageRevenue'), value: formatCurrency(a.dailyAverageRevenue) },
  ]
})

const trendOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const points = analysis.value?.dailyTrend ?? []
  return {
    grid: { left: 8, right: 40, top: 24, bottom: 24, containLabel: true },
    legend: { top: 0, textStyle: { color: theme.textSecondary, fontSize: 11 } },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category', data: points.map((p) => p.date.slice(5)), boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axisLine } }, axisTick: { show: false },
      axisLabel: { color: theme.textTertiary, fontSize: 10, interval: 2 },
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

const paymentMethodOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const rows = analysis.value?.paymentMethodBreakdown ?? []
  return {
    tooltip: { trigger: 'item', valueFormatter: (v) => formatCurrency(v as number) },
    legend: { show: false },
    series: [{
      type: 'pie', radius: ['45%', '70%'], avoidLabelOverlap: true,
      label: { color: theme.textSecondary, fontSize: 11 },
      data: rows.map((r) => ({ name: paymentMethodLabel(r.paymentMethodId), value: r.amount })),
    }],
  }
})

const weekdayOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const rows = analysis.value?.weekdayAverages ?? []
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

async function handleDownload() {
  if (!analysis.value) return
  const a = analysis.value
  const branchText = isAdmin.value && !selectedBranchId.value
    ? t('monthlyAnalysis.allBranches')
    : branchName(isAdmin.value ? selectedBranchId.value : (auth.branchId ?? ''))

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
        [t('monthlyAnalysis.wageTotal'), a.wageTotal],
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
}
</script>

<template>
  <div class="monthly-analysis-view" v-loading="loading">
    <div class="card filter-card">
      <div class="filter-controls">
        <el-date-picker v-model="selectedMonth" type="month" value-format="YYYY-MM" style="width: 160px" :clearable="false" />
        <el-select v-if="isAdmin" v-model="selectedBranchId" style="width: 160px" :placeholder="t('monthlyAnalysis.allBranches')" clearable>
          <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
        </el-select>
        <span v-else class="branch-badge">{{ branchName(auth.branchId ?? '') }}</span>
      </div>
      <el-button :icon="Download" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
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
        <div class="secondary-card">
          <span class="label">{{ t('wages.closingStatus.locked') }}</span>
          <el-tag size="small" round>{{ t(`monthlyAnalysis.wageStatus.${analysis.wageStatus}`) }}</el-tag>
        </div>
      </div>
      <p class="gap-hint">{{ t('monthlyAnalysis.tentativeOperatingGapHint') }}</p>

      <div class="grid-2col">
        <div class="card chart-card">
          <h3>{{ t('monthlyAnalysis.dailyTrendChart') }}</h3>
          <v-chart class="chart" :option="trendOption" autoresize />
        </div>
        <div class="card chart-card">
          <h3>{{ t('monthlyAnalysis.paymentMethodChart') }}</h3>
          <v-chart class="chart" :option="paymentMethodOption" autoresize />
        </div>
      </div>

      <div class="grid-2col">
        <div class="card chart-card">
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

      <div class="card">
        <h3>{{ t('monthlyAnalysis.dailyDetailTitle') }}</h3>
        <div class="table-scroll">
          <el-table :data="analysis.dailyDetail" @row-click="(row: any) => goToDailyReport(row.date, row.branchId)" class="detail-table">
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
      </div>
    </template>

  </div>
</template>

<style scoped>
.filter-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 12px;
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

@media (max-width: 960px) {
  .kpi-grid,
  .secondary-grid,
  .grid-2col {
    grid-template-columns: 1fr 1fr;
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
