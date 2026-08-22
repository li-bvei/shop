<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import {
  fetchWageMonthlyClosings, createWageMonthlyClosing, generateWageResults,
  confirmWageMonthlyClosing, lockWageMonthlyClosing, unlockWageMonthlyClosing, unconfirmWageMonthlyClosing,
  updateWageEmployeeResultBonus, updateWageEmployeeResultTransportation,
  updateWageEmployeeResultCalculationPeriod,
  type WageEmployeeResultRecord, type WageMonthlyClosingRecord,
} from '@/api/wages'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName, currentMonthJst, formatCurrency } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { downloadTableExcel } from '@/utils/excelExport'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')
const activeBranchId = ref(auth.branchId ?? '')
const month = ref(currentMonthJst())
const { loading, run } = useDelayedLoading()
const closing = ref<WageMonthlyClosingRecord | null>(null)
const staff = ref<StaffMember[]>([])

function branchLabel(id: string) {
  return branchDisplayName(branchStore.list.find((branch) => branch.id === id), locale.value, id)
}

function statusLabel(status: WageMonthlyClosingRecord['status']) {
  return t(`wages.simpleStatus.${status}`)
}

async function load(createIfMissing = true) {
  if (!activeBranchId.value || !month.value) return
  await run(async () => {
    const [rows, employees] = await Promise.all([
      fetchWageMonthlyClosings({ branchId: activeBranchId.value }),
      fetchStaffByBranch(activeBranchId.value),
    ])
    staff.value = employees
    closing.value = rows.find((row) => row.month.slice(0, 7) === month.value) ?? null
    if (!closing.value && createIfMissing) {
      closing.value = await createWageMonthlyClosing(activeBranchId.value, `${month.value}-01`)
    }
  })
}

async function calculate() {
  if (!closing.value) await load(true)
  if (!closing.value || closing.value.status !== 'draft') return
  closing.value = await generateWageResults(closing.value.id)
  ElMessage.success(t('wages.calculatedUpdated'))
}

async function confirmMonth() {
  if (!closing.value) return
  try {
    if (closing.value.status === 'draft') closing.value = await confirmWageMonthlyClosing(closing.value.id)
    else if (closing.value.status === 'confirmed' && isAdmin.value) closing.value = await lockWageMonthlyClosing(closing.value.id)
    ElMessage.success(t('common.savedSuccess'))
  } catch (error) {
    const err = error as Error & { missing?: { employee: string; date: string }[] }
    if (err.message === 'missing-wage-rule') {
      ElMessageBox.alert(
        (err.missing ?? []).map((item) => `${item.employee}：${item.date}`).join('\n'),
        t('wages.missingWageRuleTitle'), { type: 'warning' },
      )
    } else {
      ElMessage.warning(t('wages.needsRegenerateHint'))
    }
  }
}

async function unconfirmMonth() {
  if (!closing.value || closing.value.status !== 'confirmed') return
  try {
    const { value: reason } = await ElMessageBox.prompt(t('wages.unconfirmReasonPrompt'), t('wages.unconfirmThisMonth'), {
      inputValidator: (value) => !!value?.trim(),
    })
    closing.value = await unconfirmWageMonthlyClosing(closing.value.id, reason)
    ElMessage.success(t('common.savedSuccess'))
  } catch {
    // cancelled prompt — no-op
  }
}

async function unlockMonth() {
  if (!closing.value || closing.value.status !== 'locked') return
  try {
    const { value: reason } = await ElMessageBox.prompt(t('wages.unlockThisMonthPrompt'), t('wages.unlockThisMonth'), {
      inputValidator: (value) => !!value?.trim(),
    })
    closing.value = await unlockWageMonthlyClosing(closing.value.id, reason)
    ElMessage.success(t('common.savedSuccess'))
  } catch {
    // cancelled prompt — no-op
  }
}

function replaceResult(updated: WageEmployeeResultRecord) {
  if (!closing.value) return
  const index = closing.value.employeeResults.findIndex((row) => row.id === updated.id)
  if (index >= 0) closing.value.employeeResults[index] = updated
}

async function saveTransportation(row: WageEmployeeResultRecord) {
  if (closing.value?.status !== 'draft') return
  replaceResult(await updateWageEmployeeResultTransportation(row.id, {
    override: row.monthlyTransportationOverride ?? row.transportationAmount,
    reason: row.transportationOverrideReason,
  }))
}

async function saveBonus(row: WageEmployeeResultRecord) {
  if (row.bonusAmount !== 0 && !row.bonusNote.trim()) {
    ElMessage.warning(t('wages.validateBonusNote'))
    return
  }
  replaceResult(await updateWageEmployeeResultBonus(row.id, {
    bonusAmount: row.bonusAmount, bonusNote: row.bonusNote,
  }))
  ElMessage.success(t('common.savedSuccess'))
}

function employeeFor(row: WageEmployeeResultRecord) {
  return staff.value.find((employee) => employee.id === row.employeeId)
}

function defaultPeriod(row: WageEmployeeResultRecord) {
  const [year, monthValue] = month.value.split('-').map(Number)
  const last = new Date(year!, monthValue!, 0).getDate()
  const start = `${month.value}-01`
  const monthEnd = `${month.value}-${String(last).padStart(2, '0')}`
  const leaveDate = employeeFor(row)?.leaveDate
  return { start, end: leaveDate?.startsWith(month.value) ? leaveDate : monthEnd }
}

async function savePeriod(row: WageEmployeeResultRecord) {
  const fallback = defaultPeriod(row)
  replaceResult(await updateWageEmployeeResultCalculationPeriod(row.id, {
    start: row.calculationPeriodStart ?? fallback.start,
    end: row.calculationPeriodEnd ?? fallback.end,
  }))
  await load(false)
}

async function clearPeriod(row: WageEmployeeResultRecord) {
  replaceResult(await updateWageEmployeeResultCalculationPeriod(row.id, { start: null, end: null }))
  await load(false)
}

async function handleDownload() {
  if (!closing.value) return
  await downloadTableExcel(
    `工资-${branchLabel(activeBranchId.value)}-${month.value}`,
    t('wages.simplePageTitle'),
    [
      { header: t('scheduling.employee'), key: 'name', width: 16 },
      { header: t('wages.attendanceDays'), key: 'attendanceDays', width: 12 },
      { header: t('wages.actualHours'), key: 'hours', width: 12 },
      { header: t('wages.hourlyRate'), key: 'hourlyRate', width: 12, numFmt: '#,##0' },
      { header: t('wages.baseAmount'), key: 'baseAmount', width: 14, numFmt: '#,##0' },
      { header: t('wages.transportationAmount2'), key: 'transportation', width: 14, numFmt: '#,##0' },
      { header: t('wages.bonusAmount'), key: 'bonus', width: 12, numFmt: '#,##0' },
      { header: t('wages.bonusNote'), key: 'bonusNote', width: 20 },
      { header: t('wages.estimatedTotal'), key: 'total', width: 14, numFmt: '#,##0' },
      { header: t('common.status'), key: 'status', width: 12 },
    ],
    closing.value.employeeResults.map((row) => ({
      name: row.employeeName,
      attendanceDays: row.attendanceDays,
      hours: Number((row.totalMinutes / 60).toFixed(1)),
      hourlyRate: row.hourlyRate,
      baseAmount: row.baseAmount,
      transportation: row.monthlyTransportationOverride ?? row.transportationAmount,
      bonus: row.bonusAmount,
      bonusNote: row.bonusNote,
      total: row.estimatedTotal,
      status: statusLabel(closing.value!.status),
    })),
    'landscape',
  )
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  if (isAdmin.value && !activeBranchId.value) activeBranchId.value = branchStore.list[0]?.id ?? ''
  await load(true)
})

watch([activeBranchId, month], () => load(true))
</script>

<template>
  <div class="wages-view">
    <div class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('wages.simplePageTitle') }}</h3>
          <span v-if="closing" class="status-pill" :class="closing.status">{{ statusLabel(closing.status) }}</span>
        </div>
        <el-button :icon="Download" :disabled="!closing" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
      </div>

      <div class="toolbar">
        <el-select v-if="isAdmin" v-model="activeBranchId" style="width: 170px">
          <el-option v-for="branch in branchStore.list" :key="branch.id" :value="branch.id" :label="branchDisplayName(branch, locale)" />
        </el-select>
        <span v-else class="branch-label">{{ branchLabel(activeBranchId) }}</span>
        <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" style="width: 150px" />
        <el-button type="primary" :disabled="closing?.status !== 'draft'" @click="calculate">{{ t('wages.calculateUpdate') }}</el-button>
        <el-button type="success" :disabled="!closing || closing.status === 'locked'" @click="confirmMonth">
          {{ closing?.status === 'confirmed' && isAdmin ? t('wages.lockThisMonth') : t('wages.confirmThisMonth') }}
        </el-button>
        <el-button v-if="isAdmin && closing?.status === 'confirmed'" @click="unconfirmMonth">{{ t('wages.unconfirmThisMonth') }}</el-button>
        <el-button v-if="isAdmin && closing?.status === 'locked'" @click="unlockMonth">{{ t('wages.unlockThisMonth') }}</el-button>
      </div>

      <div v-loading="loading" class="wage-table-wrap">
        <el-table v-if="closing" :data="closing.employeeResults" row-key="id" class="wage-table" :empty-text="t('wages.noEmployeeResults')">
          <el-table-column type="expand" width="42">
            <template #default="{ row }">
              <div class="advanced-row">
                <span>{{ t('wages.calculationPeriod') }}</span>
                <el-date-picker v-model="row.calculationPeriodStart" type="date" value-format="YYYY-MM-DD" size="small" />
                <span>〜</span>
                <el-date-picker v-model="row.calculationPeriodEnd" type="date" value-format="YYYY-MM-DD" size="small" />
                <el-button size="small" :disabled="closing.status !== 'draft'" @click="savePeriod(row)">{{ t('common.save') }}</el-button>
                <el-button link size="small" :disabled="closing.status !== 'draft'" @click="clearPeriod(row)">{{ t('wages.resetToDefault') }}</el-button>
                <small v-if="employeeFor(row)?.leaveDate?.startsWith(month)">{{ t('wages.calculatedThroughLeaveDate') }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="employeeName" :label="t('scheduling.employee')" min-width="130">
            <template #default="{ row }">
              <span>{{ row.employeeName }}</span>
              <el-button v-if="row.hourlyRate === null" link type="danger" class="set-rate-link" @click="router.push('/staff')">
                {{ t('wages.setHourlyRateFirst') }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column prop="attendanceDays" :label="t('wages.attendanceDays')" width="92" />
          <el-table-column :label="t('wages.actualHours')" width="92"><template #default="{ row }">{{ (row.totalMinutes / 60).toFixed(1) }}h</template></el-table-column>
          <el-table-column :label="t('wages.hourlyRate')" width="100"><template #default="{ row }">{{ row.hourlyRate === null ? '—' : formatCurrency(row.hourlyRate) }}</template></el-table-column>
          <el-table-column :label="t('wages.baseAmount')" width="112"><template #default="{ row }">{{ formatCurrency(row.baseAmount) }}</template></el-table-column>
          <el-table-column :label="t('wages.transportationAmount2')" width="180">
            <template #default="{ row }">
              <div class="stacked-cell">
                <el-input-number v-model="row.monthlyTransportationOverride" :placeholder="String(row.transportationAmount)" :min="0" :controls="false" size="small" :disabled="closing.status !== 'draft'" @change="saveTransportation(row)" />
                <el-input
                  v-if="row.monthlyTransportationOverride !== null && row.monthlyTransportationOverride !== undefined"
                  v-model="row.transportationOverrideReason"
                  size="small"
                  :placeholder="t('wages.transportationOverrideReason')"
                  :disabled="closing.status !== 'draft'"
                  @change="saveTransportation(row)"
                />
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('wages.bonusAmount')" width="130">
            <template #default="{ row }"><el-input-number v-model="row.bonusAmount" :min="0" :controls="false" size="small" :disabled="closing.status !== 'draft'" /></template>
          </el-table-column>
          <el-table-column :label="t('wages.bonusNote')" min-width="180">
            <template #default="{ row }">
              <div class="stacked-cell">
                <el-input v-model="row.bonusNote" size="small" :placeholder="t('wages.bonusNotePlaceholder')" :disabled="closing.status !== 'draft'" />
                <el-button size="small" :disabled="closing.status !== 'draft'" @click="saveBonus(row)">{{ t('wages.saveBonusRow') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('wages.estimatedTotal')" width="120"><template #default="{ row }"><strong>{{ formatCurrency(row.estimatedTotal) }}</strong></template></el-table-column>
          <el-table-column :label="t('common.status')" width="90"><template #default>{{ statusLabel(closing.status) }}</template></el-table-column>
        </el-table>
        <p v-else-if="!loading" class="empty-hint">{{ t('wages.noClosingSelected') }}</p>
      </div>

      <p class="disclaimer">{{ t('wages.disclaimer') }}</p>
    </div>
  </div>
</template>

<style scoped>
.page-header, .toolbar, .advanced-row { display: flex; align-items: center; gap: 10px; }
.page-header { justify-content: space-between; margin-bottom: 14px; }
.page-header h3 { margin: 0 0 5px; }
.toolbar { flex-wrap: wrap; margin-bottom: 16px; }
.status-pill { font-size: 11px; padding: 3px 8px; border-radius: 999px; background: var(--surface-alt); }
.status-pill.confirmed { color: var(--success); }
.status-pill.locked { color: var(--text-tertiary); }
.advanced-row { padding: 8px 54px; flex-wrap: wrap; }
.advanced-row small { color: var(--text-tertiary); }
.set-rate-link { display: block; padding: 0; font-size: 11px; }
.wage-table-wrap { min-height: 80px; }
.stacked-cell { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.empty-hint { text-align: center; color: var(--text-tertiary); font-size: 13px; padding: 24px 0; }
.disclaimer { margin: 16px 0 0; font-size: 11px; color: var(--text-tertiary); }
:deep(.el-input-number) { width: 110px; }
</style>
