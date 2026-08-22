<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { EChartsOption } from 'echarts'
import { fetchDashboardSummary, type DashboardSummary } from '@/api/dashboard'
import { useBranchStore } from '@/stores/branches'
import { formatCurrency, formatNumber, branchDisplayName } from '@/utils/format'
import { useChartTheme } from '@/composables/useChartTheme'

const { t, locale } = useI18n()
const chartTheme = useChartTheme()
const branchStore = useBranchStore()

const summary = ref<DashboardSummary | null>(null)

onMounted(async () => {
  summary.value = await fetchDashboardSummary()
  await branchStore.ensureLoaded()
})

const kpis = computed(() => {
  if (!summary.value) return []
  return [
    {
      label: t('dashboard.todayRevenue'),
      value: formatCurrency(summary.value.todayRevenue),
      deltaUp: summary.value.todayRevenueDeltaPct >= 0,
      deltaText: `${summary.value.todayRevenueDeltaPct >= 0 ? '↑' : '↓'} ${Math.abs(summary.value.todayRevenueDeltaPct)}% ${t('dashboard.vsYesterday')}`,
    },
    {
      label: t('dashboard.customerCount'),
      value: formatNumber(summary.value.customerCount),
      deltaUp: summary.value.customerCountDelta >= 0,
      deltaText: `${summary.value.customerCountDelta >= 0 ? '↑' : '↓'} ${Math.abs(summary.value.customerCountDelta)}${t('dashboard.personUnit')} ${t('dashboard.vsYesterday')}`,
    },
    {
      label: t('dashboard.avgSpend'),
      value: formatCurrency(summary.value.avgSpend),
      deltaUp: summary.value.avgSpendDeltaPct >= 0,
      deltaText: `${summary.value.avgSpendDeltaPct >= 0 ? '↑' : '↓'} ${Math.abs(summary.value.avgSpendDeltaPct)}% ${t('dashboard.vsYesterday')}`,
    },
    {
      label: t('dashboard.monthlyPurchasing'),
      value: formatCurrency(summary.value.monthlyPurchasing),
      deltaUp: summary.value.monthlyPurchasingDeltaPct >= 0,
      deltaText: `${summary.value.monthlyPurchasingDeltaPct >= 0 ? '↑' : '↓'} ${Math.abs(summary.value.monthlyPurchasingDeltaPct)}% ${t('dashboard.vsLastMonth')}`,
    },
  ]
})

const trendOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const points = summary.value?.revenueTrend ?? []
  return {
    grid: { left: 8, right: 12, top: 16, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => formatCurrency(value as number),
    },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.date.slice(5).replace('-', '/')),
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axisLine } },
      axisTick: { show: false },
      axisLabel: { color: theme.textTertiary, fontSize: 11, interval: 1 },
    },
    yAxis: {
      type: 'value',
      show: false,
    },
    series: [
      {
        type: 'line',
        data: points.map((p) => p.revenue),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        lineStyle: { color: theme.accent, width: 2.5 },
        itemStyle: { color: theme.accent },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: theme.accentSoft },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
      },
    ],
  }
})

const branchOption = computed<EChartsOption>(() => {
  const theme = chartTheme.value
  const rows = summary.value?.branchRevenueToday ?? []
  const names = rows.map((r) => branchDisplayName(branchStore.list.find((b) => b.id === r.branchId), locale.value, r.branchId))
  return {
    grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'none' },
      valueFormatter: (value) => formatCurrency(value as number),
    },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.textPrimary, fontSize: 13 },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((r) => r.revenue),
        barWidth: 12,
        itemStyle: { color: theme.accent, borderRadius: 6 },
        label: {
          show: true,
          position: 'right',
          color: theme.textSecondary,
          fontSize: 12.5,
          formatter: (p) => formatCurrency(p.value as number),
        },
      },
    ],
  }
})
</script>

<template>
  <div class="dashboard-view" :key="locale">
    <div class="kpi-grid">
      <div v-for="kpi in kpis" :key="kpi.label" class="kpi-card">
        <div class="label">{{ kpi.label }}</div>
        <div class="value">{{ kpi.value }}</div>
        <div class="delta" :class="kpi.deltaUp ? 'up' : 'down'">{{ kpi.deltaText }}</div>
      </div>
    </div>

    <div class="grid-2col">
      <div class="card">
        <h3>
          <span>{{ t('dashboard.revenueTrend') }}</span>
          <small>{{ t('dashboard.past14Days') }}</small>
        </h3>
        <v-chart class="chart" :option="trendOption" autoresize />
      </div>
      <div class="card">
        <h3>
          <span>{{ t('dashboard.branchCompare') }}</span>
          <small>{{ t('dashboard.todayRevenueSub') }}</small>
        </h3>
        <v-chart class="chart" :option="branchOption" autoresize />
      </div>
    </div>
  </div>
</template>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

@media (max-width: 1180px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
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
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.02em;
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

.grid-2col {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 14px;
}

.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
}

.card h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 16px;
  color: var(--text-primary);
}

.card h3 small {
  display: block;
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-weight: 400;
  margin-top: 2px;
}

.chart {
  height: 220px;
}

@media (max-width: 960px) {
  .kpi-grid,
  .grid-2col {
    grid-template-columns: 1fr;
  }
}
</style>
