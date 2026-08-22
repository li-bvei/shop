<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  fetchSchedulePeriods,
  fetchAvailabilityRequests,
  saveAvailabilityRequest,
  type SchedulePeriod,
  type Availability,
} from '@/api/scheduling'
import { useAuthStore } from '@/stores/auth'
import { currentMonthJst } from '@/utils/format'

const { t } = useI18n()
const auth = useAuthStore()

// Staff picks a month, never a raw period range — the period behind it is
// always the one the manager auto-created for that branch+month (see the
// manager-side monthly grid); if none exists yet, availability simply
// can't be submitted for that month yet.
const selectedMonth = ref(currentMonthJst())
const periods = ref<SchedulePeriod[]>([])
const loading = ref(false)
const saving = ref(false)

const selectedPeriod = computed(
  () => periods.value.find((p) => p.month === `${selectedMonth.value}-01`) ?? null,
)

interface DayRow {
  workDate: string
  id: string | null
  availability: Availability
  startTime: string | null
  endTime: string | null
  crossesMidnight: boolean
  note: string
}

const dayRows = ref<DayRow[]>([])

const isEditable = computed(() => selectedPeriod.value?.status === 'collecting')

function enumerateDates(start: string, end: string): string[] {
  const dates: string[] = []
  const cursor = new Date(`${start}T00:00:00`)
  const endDate = new Date(`${end}T00:00:00`)
  while (cursor <= endDate) {
    dates.push(cursor.toISOString().slice(0, 10))
    cursor.setDate(cursor.getDate() + 1)
  }
  return dates
}

async function loadPeriods() {
  if (!auth.branchId) return
  periods.value = await fetchSchedulePeriods({ branchId: auth.branchId })
  if (!periods.value.some((p) => p.month === `${selectedMonth.value}-01`)) {
    // default to whichever month is actually open for collecting, if the
    // current calendar month has no period yet
    const collecting = periods.value.find((p) => p.status === 'collecting' && p.month)
    if (collecting?.month) selectedMonth.value = collecting.month.slice(0, 7)
  }
}

async function loadAvailability() {
  if (!selectedPeriod.value || !auth.staffMemberId) {
    dayRows.value = []
    return
  }
  loading.value = true
  try {
    const existing = await fetchAvailabilityRequests({
      periodId: selectedPeriod.value.id, employeeId: auth.staffMemberId,
    })
    const byDate = new Map(existing.map((e) => [e.workDate, e]))
    dayRows.value = enumerateDates(selectedPeriod.value.startDate, selectedPeriod.value.endDate).map((workDate) => {
      const found = byDate.get(workDate)
      return {
        workDate,
        id: found?.id ?? null,
        availability: found?.availability ?? 'available',
        startTime: found?.startTime ?? '09:00',
        endTime: found?.endTime ?? '18:00',
        crossesMidnight: found?.crossesMidnight ?? false,
        note: found?.note ?? '',
      }
    })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadPeriods()
  await loadAvailability()
})
watch(selectedMonth, loadAvailability)

function weekdayLabel(dateStr: string) {
  const names = t('common.weekdayShort').split(',')
  return names[new Date(`${dateStr}T00:00:00`).getDay()]
}

async function saveRow(row: DayRow) {
  if (!selectedPeriod.value || !auth.staffMemberId) return
  const saved = await saveAvailabilityRequest(row.id, {
    periodId: selectedPeriod.value.id,
    employeeId: auth.staffMemberId,
    workDate: row.workDate,
    availability: row.availability,
    startTime: row.availability === 'available' ? row.startTime : null,
    endTime: row.availability === 'available' ? row.endTime : null,
    crossesMidnight: row.crossesMidnight,
    note: row.note,
  })
  row.id = saved.id
}

async function handleSaveAll() {
  if (!isEditable.value) return
  saving.value = true
  try {
    for (const row of dayRows.value) {
      await saveRow(row)
    }
    ElMessage.success(t('common.savedSuccess'))
  } finally {
    saving.value = false
  }
}

function shiftMonth(monthStr: string, delta: number): string {
  const parts = monthStr.split('-')
  const y = Number(parts[0]); const m = Number(parts[1])
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

async function copyFromPreviousMonth() {
  if (!selectedPeriod.value || !auth.staffMemberId) return
  const previousMonth = shiftMonth(selectedMonth.value, -1)
  const previous = periods.value.find((p) => p.month === `${previousMonth}-01`)
  if (!previous) {
    ElMessage.warning(t('scheduling.noPreviousPeriod'))
    return
  }
  const previousRows = await fetchAvailabilityRequests({ periodId: previous.id, employeeId: auth.staffMemberId })
  // Matched by day-of-month, not weekday offset — months have different
  // lengths and weekday alignment, so "the 5th" is the only stable anchor.
  const byDay = new Map(previousRows.map((r) => [r.workDate.slice(8, 10), r]))
  for (const row of dayRows.value) {
    const source = byDay.get(row.workDate.slice(8, 10))
    if (source) {
      row.availability = source.availability
      row.startTime = source.startTime
      row.endTime = source.endTime
      row.crossesMidnight = source.crossesMidnight
      row.note = source.note
    }
  }
  ElMessage.success(t('scheduling.copiedFromPreviousPeriod'))
}
</script>

<template>
  <div class="my-availability-view">
    <div class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('nav.myAvailability') }}</h3>
          <p class="section-hint">{{ t('scheduling.availabilityHint') }}</p>
        </div>
        <div class="header-actions">
          <el-date-picker v-model="selectedMonth" type="month" value-format="YYYY-MM" style="width: 150px" :clearable="false" />
          <el-button v-if="isEditable" @click="copyFromPreviousMonth">{{ t('scheduling.copyPreviousMonth') }}</el-button>
        </div>
      </div>

      <el-alert v-if="!isEditable && selectedPeriod" type="info" :closable="false" show-icon class="readonly-alert">
        {{ t('scheduling.availabilityReadonlyHint') }}
      </el-alert>
      <el-alert v-else-if="!selectedPeriod" type="info" :closable="false" show-icon class="readonly-alert">
        {{ t('scheduling.noAvailabilityPeriodThisMonth') }}
      </el-alert>

      <el-table v-if="selectedPeriod" :data="dayRows" v-loading="loading">
        <el-table-column :label="t('scheduling.workDate')" width="140">
          <template #default="{ row }">{{ row.workDate }}（{{ weekdayLabel(row.workDate) }}）</template>
        </el-table-column>
        <el-table-column :label="t('scheduling.availability')" width="160">
          <template #default="{ row }">
            <el-radio-group v-model="row.availability" :disabled="!isEditable" size="small">
              <el-radio-button value="available">{{ t('scheduling.available') }}</el-radio-button>
              <el-radio-button value="day_off">{{ t('scheduling.dayOff') }}</el-radio-button>
            </el-radio-group>
          </template>
        </el-table-column>
        <el-table-column :label="t('scheduling.startTime')" width="120">
          <template #default="{ row }">
            <el-time-picker
              v-if="row.availability === 'available'"
              v-model="row.startTime"
              value-format="HH:mm"
              :disabled="!isEditable"
              format="HH:mm"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('scheduling.endTime')" width="120">
          <template #default="{ row }">
            <el-time-picker
              v-if="row.availability === 'available'"
              v-model="row.endTime"
              value-format="HH:mm"
              :disabled="!isEditable"
              format="HH:mm"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('scheduling.crossesMidnight')" width="100">
          <template #default="{ row }">
            <el-checkbox v-if="row.availability === 'available'" v-model="row.crossesMidnight" :disabled="!isEditable" />
          </template>
        </el-table-column>
        <el-table-column :label="t('common.note')" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.note" :disabled="!isEditable" />
          </template>
        </el-table-column>
      </el-table>

      <div v-if="isEditable" class="submit-row">
        <el-button type="primary" :loading="saving" @click="handleSaveAll">{{ t('common.save') }}</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.page-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.section-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.readonly-alert {
  margin-bottom: 14px;
}

.submit-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
