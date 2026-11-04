<script setup lang="ts">
/**
 * The employee's own attendance screen: clock in / out / break, this
 * month's own records, and the 補正申請 flow for a day that went wrong.
 *
 * Phone-first on purpose — this is the one screen in the app a floor
 * employee opens while standing at the counter, usually one-handed, so the
 * four punch actions are large fixed-size targets rather than toolbar
 * buttons, and every other control sits below them.
 *
 * The four actions are always rendered and individually DISABLED rather
 * than hidden. A screen whose buttons appear and vanish between taps reads
 * as broken, and "why is there no clock-out button" is a support call;
 * "clock out is greyed out because you're on a break" is self-explanatory.
 * Which ones are enabled is decided by the server (fetchPunchState), never
 * inferred here — the server enforces the same ordering on write, so a
 * stale screen can only ever produce a clear error, never a bad record.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Clock, Coffee, SwitchButton, VideoPlay } from '@element-plus/icons-vue'

import {
  createAttendancePunch, fetchActualWorkRecords, fetchAttendanceCorrections, fetchAttendancePunches,
  fetchPunchState, submitAttendanceCorrection, withdrawAttendanceCorrection,
  type ActualWorkRecord, type AttendanceCorrection, type AttendancePunch, type PunchKind, type PunchState,
} from '@/api/scheduling'
import { useAuthStore } from '@/stores/auth'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { currentMonthJst, todayJst } from '@/utils/format'
import { formatHours } from '@/utils/shiftTime'

const { t } = useI18n()
const auth = useAuthStore()
const { loading, run } = useDelayedLoading()

const state = ref<PunchState | null>(null)
const todayPunches = ref<AttendancePunch[]>([])
const records = ref<ActualWorkRecord[]>([])
const corrections = ref<AttendanceCorrection[]>([])
const month = ref(currentMonthJst())
const punching = ref<PunchKind | null>(null)

/** The month's first and last day, for the record query. Built from the
 * YYYY-MM string rather than from a Date, so the browser's own timezone
 * can never shift which month is asked for. */
const monthRange = computed(() => {
  const [year, m] = month.value.split('-').map(Number)
  const lastDay = new Date(Date.UTC(year ?? 1970, m ?? 1, 0)).getUTCDate()
  return { from: `${month.value}-01`, to: `${month.value}-${String(lastDay).padStart(2, '0')}` }
})

async function loadState() {
  state.value = await fetchPunchState()
  todayPunches.value = await fetchAttendancePunches({ workDate: state.value.workDate })
}

async function loadMonth() {
  if (!auth.staffMemberId) return
  const { from, to } = monthRange.value
  const [recordRows, correctionRows] = await Promise.all([
    fetchActualWorkRecords({ employeeId: auth.staffMemberId, dateFrom: from, dateTo: to }),
    fetchAttendanceCorrections({ employeeId: auth.staffMemberId, dateFrom: from, dateTo: to }),
  ])
  records.value = recordRows
  corrections.value = correctionRows
}

async function load() {
  await run(async () => {
    await Promise.all([loadState(), loadMonth()])
  })
}

onMounted(load)

const punchActions = computed(() => {
  const s = state.value
  return [
    { kind: 'clock_in' as const, labelKey: 'attendance.clockIn', icon: VideoPlay, enabled: !!s?.canClockIn, tone: 'in' },
    { kind: 'break_start' as const, labelKey: 'attendance.breakStart', icon: Coffee, enabled: !!s?.canStartBreak, tone: 'break' },
    { kind: 'break_end' as const, labelKey: 'attendance.breakEnd', icon: Clock, enabled: !!s?.canEndBreak, tone: 'break' },
    { kind: 'clock_out' as const, labelKey: 'attendance.clockOut', icon: SwitchButton, enabled: !!s?.canClockOut, tone: 'out' },
  ]
})

/** One line saying where the employee stands right now, so the screen
 * answers "am I clocked in?" without the user having to read the button
 * states back to themselves. */
const statusText = computed(() => {
  const s = state.value
  if (!s) return ''
  if (s.onBreak) return t('attendance.statusOnBreak')
  if (s.clockedOut) return t('attendance.statusFinished')
  if (s.clockedIn) return t('attendance.statusWorking')
  return t('attendance.statusNotStarted')
})

async function punch(kind: PunchKind) {
  punching.value = kind
  try {
    await createAttendancePunch(kind)
    ElMessage.success(t('attendance.punchRecorded'))
    // Both the state and the month are refetched: the punch also rebuilt
    // today's attendance record, so the table below is now stale too.
    await load()
  } finally {
    punching.value = null
  }
}

function punchTime(iso: string) {
  // Rendered in the browser's locale clock rather than reformatted by
  // hand — the value is a real instant, and the employee is standing in
  // the same timezone as the branch.
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

// --- Correction request ---------------------------------------------------

const correctionVisible = ref(false)
const correctionSaving = ref(false)
const correctionForm = ref({
  workDate: todayJst(),
  requestedAbsent: false,
  requestedStart: '',
  requestedEnd: '',
  requestedCrossesMidnight: false,
  requestedBreakMinutes: null as number | null,
  reason: '',
})

function openCorrection(workDate?: string) {
  correctionForm.value = {
    workDate: workDate ?? todayJst(),
    requestedAbsent: false,
    requestedStart: '',
    requestedEnd: '',
    requestedCrossesMidnight: false,
    requestedBreakMinutes: null,
    reason: '',
  }
  correctionVisible.value = true
}

const correctionValid = computed(() => {
  const f = correctionForm.value
  if (!f.reason.trim()) return false
  if (f.requestedAbsent) return true
  // Mirrors the server's own rule: a request must actually request
  // something, and times come as a pair.
  if (f.requestedStart && f.requestedEnd) return true
  return f.requestedBreakMinutes != null
})

async function saveCorrection() {
  correctionSaving.value = true
  try {
    const f = correctionForm.value
    await submitAttendanceCorrection({
      workDate: f.workDate,
      requestedAbsent: f.requestedAbsent,
      requestedStart: f.requestedAbsent ? null : (f.requestedStart || null),
      requestedEnd: f.requestedAbsent ? null : (f.requestedEnd || null),
      requestedCrossesMidnight: f.requestedCrossesMidnight,
      requestedBreakMinutes: f.requestedAbsent ? null : f.requestedBreakMinutes,
      reason: f.reason.trim(),
    })
    ElMessage.success(t('attendance.correctionSubmitted'))
    correctionVisible.value = false
    await loadMonth()
  } finally {
    correctionSaving.value = false
  }
}

async function withdraw(correction: AttendanceCorrection) {
  await withdrawAttendanceCorrection(correction.id)
  ElMessage.success(t('attendance.correctionWithdrawn'))
  await loadMonth()
}

function statusTagType(status: string) {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'pending') return 'warning'
  return 'info'
}

function recordStatusTagType(status: string) {
  if (status === 'admin_locked') return 'info'
  if (status === 'manager_confirmed') return 'success'
  return 'warning'
}
</script>

<template>
  <div class="my-attendance-view" v-loading="loading">
    <!-- 1. The clock itself -->
    <div class="card punch-card">
      <div class="punch-head">
        <div>
          <h3>{{ t('attendance.todayTitle') }}</h3>
          <p class="punch-date">{{ state?.workDate }}</p>
        </div>
        <span class="punch-status" :class="{ working: state?.clockedIn && !state?.clockedOut }">
          {{ statusText }}
        </span>
      </div>

      <p v-if="state && !state.selfPunchEnabled" class="punch-disabled-hint">
        {{ t('attendance.selfPunchDisabled') }}
      </p>

      <div v-else class="punch-grid">
        <el-button
          v-for="action in punchActions" :key="action.kind"
          class="punch-button" :class="`tone-${action.tone}`"
          :icon="action.icon"
          :disabled="!action.enabled"
          :loading="punching === action.kind"
          @click="punch(action.kind)"
        >
          {{ t(action.labelKey) }}
        </el-button>
      </div>

      <div v-if="todayPunches.length" class="punch-timeline">
        <span v-for="p in todayPunches" :key="p.id" class="punch-chip">
          {{ t(`attendance.kind.${p.kind}`) }} {{ punchTime(p.punchedAt) }}
        </span>
      </div>
    </div>

    <!-- 2. This month's own records -->
    <div class="card">
      <div class="section-head">
        <h3>{{ t('attendance.myRecordsTitle') }}</h3>
        <div class="section-actions">
          <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" @change="loadMonth" />
          <el-button type="primary" plain @click="openCorrection()">{{ t('attendance.requestCorrection') }}</el-button>
        </div>
      </div>
      <p class="section-hint">{{ t('attendance.myRecordsHint') }}</p>

      <el-table :data="records" class="desktop-table" :empty-text="t('attendance.noRecords')">
        <el-table-column :label="t('scheduling.workDate')" prop="workDate" width="120" />
        <el-table-column :label="t('attendance.actualStart')" width="100">
          <template #default="{ row }">{{ row.actualStart?.slice(0, 5) ?? '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('attendance.actualEnd')" width="100">
          <template #default="{ row }">{{ row.actualEnd?.slice(0, 5) ?? '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('attendance.breakMinutes')" width="100">
          <template #default="{ row }">{{ row.actualBreakMinutes }}{{ t('common.minutes') }}</template>
        </el-table-column>
        <el-table-column :label="t('scheduling.workedHours')" width="100">
          <template #default="{ row }">{{ row.actualEnd ? formatHours(row.workedMinutes) : '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('attendance.deviation')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.absent" class="deviation absent">{{ t('attendance.absent') }}</span>
            <template v-else>
              <span v-if="row.lateMinutes" class="deviation late">
                {{ t('attendance.lateBy', { minutes: row.lateMinutes }) }}
              </span>
              <span v-if="row.earlyLeaveMinutes" class="deviation early">
                {{ t('attendance.earlyBy', { minutes: row.earlyLeaveMinutes }) }}
              </span>
              <span v-if="!row.lateMinutes && !row.earlyLeaveMinutes" class="deviation ok">—</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="recordStatusTagType(row.status)">
              {{ t(`attendance.recordStatus.${row.status}`) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click="openCorrection(row.workDate)">
              {{ t('attendance.fix') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Phone: a table of 7 columns is unreadable at 375px, so each day
           becomes a card that keeps every value instead of hiding columns. -->
      <div class="mobile-cards">
        <div v-for="row in records" :key="row.id" class="record-card">
          <div class="record-card-head">
            <span class="record-date">{{ row.workDate }}</span>
            <el-tag size="small" :type="recordStatusTagType(row.status)">
              {{ t(`attendance.recordStatus.${row.status}`) }}
            </el-tag>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.actualStart') }}</span>
            <span>{{ row.actualStart?.slice(0, 5) ?? '—' }}</span>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.actualEnd') }}</span>
            <span>{{ row.actualEnd?.slice(0, 5) ?? '—' }}</span>
          </div>
          <div class="record-card-row">
            <span>{{ t('attendance.breakMinutes') }}</span>
            <span>{{ row.actualBreakMinutes }}{{ t('common.minutes') }}</span>
          </div>
          <div v-if="row.actualEnd" class="record-card-row">
            <span>{{ t('scheduling.workedHours') }}</span>
            <span>{{ formatHours(row.workedMinutes) }}</span>
          </div>
          <div v-if="row.absent || row.lateMinutes || row.earlyLeaveMinutes" class="record-card-row">
            <span>{{ t('attendance.deviation') }}</span>
            <span>
              <span v-if="row.absent" class="deviation absent">{{ t('attendance.absent') }}</span>
              <span v-if="row.lateMinutes" class="deviation late">{{ t('attendance.lateBy', { minutes: row.lateMinutes }) }}</span>
              <span v-if="row.earlyLeaveMinutes" class="deviation early">{{ t('attendance.earlyBy', { minutes: row.earlyLeaveMinutes }) }}</span>
            </span>
          </div>
          <el-button link type="primary" @click="openCorrection(row.workDate)">{{ t('attendance.fix') }}</el-button>
        </div>
        <p v-if="!records.length" class="empty-hint">{{ t('attendance.noRecords') }}</p>
      </div>
    </div>

    <!-- 3. My correction requests -->
    <div class="card">
      <h3>{{ t('attendance.myCorrectionsTitle') }}</h3>
      <div v-for="c in corrections" :key="c.id" class="correction-row">
        <div class="correction-main">
          <div class="correction-head">
            <span class="correction-date">{{ c.workDate }}</span>
            <el-tag size="small" :type="statusTagType(c.status)">
              {{ t(`attendance.correctionStatus.${c.status}`) }}
            </el-tag>
          </div>
          <div class="correction-detail">
            <template v-if="c.requestedAbsent">{{ t('attendance.absent') }}</template>
            <template v-else>{{ c.requestedStart ?? '—' }} – {{ c.requestedEnd ?? '—' }}</template>
          </div>
          <div class="correction-reason">{{ c.reason }}</div>
          <div v-if="c.decisionNote" class="correction-note">
            {{ t('attendance.decisionNote') }}: {{ c.decisionNote }}
          </div>
        </div>
        <el-button v-if="c.status === 'pending'" link type="danger" @click="withdraw(c)">
          {{ t('attendance.withdraw') }}
        </el-button>
      </div>
      <p v-if="!corrections.length" class="empty-hint">{{ t('attendance.noCorrections') }}</p>
    </div>

    <el-dialog v-model="correctionVisible" :title="t('attendance.requestCorrection')" class="correction-dialog">
      <el-form label-position="top">
        <el-form-item :label="t('scheduling.workDate')">
          <el-date-picker v-model="correctionForm.workDate" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="correctionForm.requestedAbsent">{{ t('attendance.requestAbsent') }}</el-checkbox>
        </el-form-item>
        <template v-if="!correctionForm.requestedAbsent">
          <el-form-item :label="t('attendance.actualStart')">
            <el-time-picker v-model="correctionForm.requestedStart" format="HH:mm" value-format="HH:mm" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('attendance.actualEnd')">
            <el-time-picker v-model="correctionForm.requestedEnd" format="HH:mm" value-format="HH:mm" style="width: 100%" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="correctionForm.requestedCrossesMidnight">
              {{ t('scheduling.crossesMidnight') }}
            </el-checkbox>
          </el-form-item>
          <el-form-item :label="t('attendance.breakMinutes')">
            <el-input-number v-model="correctionForm.requestedBreakMinutes" :min="0" :max="600" style="width: 100%" />
          </el-form-item>
        </template>
        <el-form-item :label="t('attendance.reason')" required>
          <el-input v-model="correctionForm.reason" type="textarea" :rows="3" :placeholder="t('attendance.reasonPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctionVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :disabled="!correctionValid" :loading="correctionSaving" @click="saveCorrection">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.card h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.section-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0 0 14px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.section-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.punch-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.punch-date {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.punch-status {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--surface-alt);
  border-radius: var(--radius-sm);
  padding: 6px 12px;
  white-space: nowrap;
}

.punch-status.working {
  color: var(--success);
}

.punch-disabled-hint {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}

/* Two columns at every width, including a 320px phone: four actions in one
   row would give each a ~70px target, and stacking all four pushes the
   clock-out button below the fold. */
.punch-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.punch-button {
  height: 64px;
  margin-left: 0 !important;
  font-size: 15px;
  font-weight: 600;
  /* A long label wraps inside the button instead of being clipped — the
     button is already tall enough for two lines. */
  white-space: normal;
  line-height: 1.2;
}

.punch-button.tone-in:not(.is-disabled) {
  color: var(--success);
  border-color: var(--success);
}

.punch-button.tone-out:not(.is-disabled) {
  color: var(--danger);
  border-color: var(--danger);
}

.punch-timeline {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.punch-chip {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--surface-alt);
  border-radius: 999px;
  padding: 3px 10px;
}

.deviation {
  font-size: 12.5px;
  margin-right: 8px;
}

.deviation.late,
.deviation.absent {
  color: var(--danger);
  font-weight: 600;
}

.deviation.early {
  color: var(--warning, #e6a23c);
  font-weight: 600;
}

.deviation.ok {
  color: var(--text-tertiary);
}

.correction-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.correction-row:last-child {
  border-bottom: none;
}

.correction-main {
  flex: 1;
  min-width: 0;
}

.correction-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.correction-date {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.correction-detail {
  font-size: 13px;
  color: var(--text-secondary);
}

/* A reason is free text an employee typed — it wraps and is shown in full,
   never truncated to one line, since it is the whole content of the row. */
.correction-reason,
.correction-note {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.empty-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
}

.mobile-cards {
  display: none;
}

.record-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
}

.record-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.record-date {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.record-card-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 13.5px;
  color: var(--text-secondary);
  padding: 2px 0;
}

.record-card-row span:last-child {
  color: var(--text-primary);
  text-align: right;
}

@media (max-width: 768px) {
  .card {
    padding: 16px 14px;
  }

  .desktop-table {
    display: none;
  }

  .mobile-cards {
    display: block;
  }

  .section-head {
    align-items: stretch;
  }

  .section-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .section-actions :deep(.el-button),
  .section-actions :deep(.el-date-editor) {
    width: 100%;
    min-width: 0;
    height: 44px;
  }
}
</style>
