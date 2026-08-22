<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchShifts, type ShiftRecord } from '@/api/scheduling'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()

const shifts = ref<ShiftRecord[]>([])
const loading = ref(false)

async function load() {
  if (!auth.staffMemberId) return
  loading.value = true
  try {
    shifts.value = await fetchShifts({ employeeId: auth.staffMemberId })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="my-shifts-view">
    <div class="card">
      <h3>{{ t('nav.myShifts') }}</h3>
      <p class="section-hint">{{ t('scheduling.myShiftsHint') }}</p>

      <el-table :data="shifts" v-loading="loading" :empty-text="t('scheduling.noShiftsThisWeek')">
        <el-table-column :label="t('scheduling.workDate')" prop="workDate" width="120" />
        <el-table-column :label="t('scheduling.plannedStart')" prop="plannedStart" width="110" />
        <el-table-column :label="t('scheduling.plannedEnd')" prop="plannedEnd" width="110" />
        <el-table-column :label="t('scheduling.crossesMidnight')" width="90">
          <template #default="{ row }">{{ row.crossesMidnight ? '✓' : '' }}</template>
        </el-table-column>
        <el-table-column :label="t('scheduling.plannedBreakMinutes')" width="120">
          <template #default="{ row }">{{ row.plannedBreakMinutes }}{{ t('common.minutes') }}</template>
        </el-table-column>
        <el-table-column :label="t('scheduling.position')" prop="position" min-width="120" />
        <el-table-column :label="t('common.note')" prop="note" min-width="160" />
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
  margin: 0 0 16px;
}
</style>
