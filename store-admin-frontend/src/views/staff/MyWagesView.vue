<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download } from '@element-plus/icons-vue'
import { fetchWageEmployeeResults, type WageEmployeeResultRecord } from '@/api/wages'
import { useAuthStore } from '@/stores/auth'
import { formatCurrency } from '@/utils/format'
import { downloadCustomExcel } from '@/utils/excelExport'

const { t } = useI18n()
const auth = useAuthStore()

const results = ref<WageEmployeeResultRecord[]>([])
const loading = ref(false)

async function load() {
  if (!auth.staffMemberId) return
  loading.value = true
  try {
    results.value = await fetchWageEmployeeResults({ employeeId: auth.staffMemberId })
  } finally {
    loading.value = false
  }
}

onMounted(load)

function closingStatusLabel(status: string) {
  return t(`wages.closingStatus.${status}`)
}

// e.g. "田中-2026年08月-工资计算明细"
async function handleDownload(row: WageEmployeeResultRecord) {
  const [year, month] = row.closingMonth.slice(0, 7).split('-')
  const period = row.calculationPeriodStart || row.calculationPeriodEnd
    ? `${row.calculationPeriodStart ?? ''} ~ ${row.calculationPeriodEnd ?? ''}`
    : t('wages.fullMonth')

  await downloadCustomExcel(`${row.employeeName}-${year}年${month}月-工资计算明细`, t('wages.printPersonal'), (ws) => {
    ws.addRow([row.employeeName, `${year}年${month}月`, row.closingBranchName, closingStatusLabel(row.closingStatus)])
    ws.getRow(1).font = { bold: true, size: 13 }
    ws.addRow([t('wages.attendanceDays'), row.attendanceDays, t('wages.totalMinutes'), row.totalMinutes, t('wages.calculationPeriod'), period])
    ws.addRow([])

    const headerRow = ws.addRow([
      t('scheduling.workDate'), t('scheduling.actualStart'), t('scheduling.actualEnd'),
      t('scheduling.actualBreakMinutes'), t('wages.totalMinutes'), t('wages.baseAmount'),
    ])
    headerRow.font = { bold: true }
    headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } }
    for (const d of row.dailyDetails) {
      ws.addRow([d.workDate, d.actualStart ?? '—', d.actualEnd ?? '—', d.actualBreakMinutes ?? '—', d.totalMinutes, d.baseAmount])
    }
    ws.addRow([])

    ws.addRow([t('wages.baseAmount'), row.baseAmount])
    ws.addRow([t('wages.transportationAmount2'), row.transportationAmount])
    ws.addRow([t('wages.bonusAmount'), row.bonusAmount])
    const totalRow = ws.addRow([t('wages.estimatedTotal'), row.estimatedTotal])
    totalRow.font = { bold: true }
    ws.addRow([])
    ws.addRow([t('wages.disclaimer')])
    ws.columns.forEach((col) => { col.width = 16 })
  })
}
</script>

<template>
  <div class="my-wages-view">
    <div class="card">
      <h3>{{ t('nav.myWages') }}</h3>
      <p class="section-hint">{{ t('wages.myWagesHint') }}</p>
      <el-alert type="info" :closable="false" show-icon class="disclaimer-alert">
        {{ t('wages.disclaimer') }}
      </el-alert>

      <el-table :data="results" v-loading="loading">
        <el-table-column :label="t('monthlyAnalysis.month')" width="110">
          <template #default="{ row }">{{ row.closingMonth.slice(0, 7) }}</template>
        </el-table-column>
        <el-table-column :label="t('settings.accountBranch')" width="120" prop="closingBranchName" />
        <el-table-column :label="t('wages.closingStatus.locked')" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.closingStatus === 'locked' ? 'success' : 'info'" round>
              {{ closingStatusLabel(row.closingStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('wages.attendanceDays')" width="100" prop="attendanceDays" />
        <el-table-column :label="t('wages.baseAmount')" width="110">
          <template #default="{ row }">{{ formatCurrency(row.baseAmount) }}</template>
        </el-table-column>
        <el-table-column :label="t('wages.transportationAmount2')" width="100">
          <template #default="{ row }">{{ formatCurrency(row.transportationAmount) }}</template>
        </el-table-column>
        <el-table-column :label="t('wages.bonusAmount')" width="100">
          <template #default="{ row }">{{ formatCurrency(row.bonusAmount) }}</template>
        </el-table-column>
        <el-table-column :label="t('wages.estimatedTotal')" width="130">
          <template #default="{ row }">{{ formatCurrency(row.estimatedTotal) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="100" fixed="right">
          <template #default="{ row }">
            <el-button circle text :icon="Download" size="small" @click="handleDownload(row)" />
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <el-table :data="row.dailyDetails" size="small" class="daily-detail-table">
              <el-table-column :label="t('scheduling.workDate')" prop="workDate" width="110" />
              <el-table-column :label="t('scheduling.actualStart')" width="90">
                <template #default="{ row: d }">{{ d.actualStart ?? '—' }}</template>
              </el-table-column>
              <el-table-column :label="t('scheduling.actualEnd')" width="90">
                <template #default="{ row: d }">{{ d.actualEnd ?? '—' }}</template>
              </el-table-column>
              <el-table-column :label="t('scheduling.actualBreakMinutes')" width="90">
                <template #default="{ row: d }">{{ d.actualBreakMinutes ?? '—' }}</template>
              </el-table-column>
              <el-table-column :label="t('wages.totalMinutes')" prop="totalMinutes" width="100" />
              <el-table-column :label="t('wages.baseAmount')" width="100">
                <template #default="{ row: d }">{{ formatCurrency(d.baseAmount) }}</template>
              </el-table-column>
            </el-table>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.card h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.section-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0 0 14px;
}

.disclaimer-alert {
  margin-bottom: 14px;
}

.daily-detail-table {
  margin: 4px 0 4px 40px;
}
</style>
