<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import {
  fetchRiskEvents,
  fetchStaffPermissions,
  reviewRiskEvent,
  updateStaffPermission,
  type RiskEvent,
  type StaffPermission,
} from '@/api/promotions'

const { t } = useI18n()
const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')

const view = ref<'events' | 'permissions'>('events')

// ---- risk events -------------------------------------------------------

const events = ref<RiskEvent[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref('open')
const { loading, run } = useDelayedLoading()

async function loadEvents() {
  await run(async () => {
    const res = await fetchRiskEvents({
      status: statusFilter.value || undefined,
      page: page.value,
      pageSize: 50,
    })
    events.value = res.results
    total.value = res.count
  })
}

watch(page, loadEvents)
function applyFilter() {
  page.value = 1
  loadEvents()
}

const severityType = (s: string) => (s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'info')

function evidenceText(ev: RiskEvent) {
  return Object.entries(ev.evidence)
    .filter(([k]) => k !== 'rule')
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ')
}

async function review(ev: RiskEvent, status: 'reviewed' | 'confirmed' | 'dismissed') {
  let note = ''
  try {
    const r = await ElMessageBox.prompt(t('risk.reviewPrompt'), t(`risk.status_${status}`), {
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      inputPlaceholder: t('risk.notePlaceholder'),
    })
    note = r.value ?? ''
  } catch {
    return
  }
  try {
    await reviewRiskEvent(ev.id, status, note)
    ElMessage.success(t('common.savedSuccess'))
    await loadEvents()
  } catch {
    ElMessage.error(t('common.unexpectedError'))
  }
}

// ---- staff permissions (admin) ----------------------------------------

const perms = ref<StaffPermission[]>([])
const permsLoading = ref(false)

async function loadPerms() {
  if (!isAdmin.value) return
  permsLoading.value = true
  try {
    perms.value = await fetchStaffPermissions()
  } finally {
    permsLoading.value = false
  }
}

async function togglePerm(p: StaffPermission, field: 'canVerifySpend' | 'canRedeemVoucher', value: boolean) {
  try {
    const updated = await updateStaffPermission(p.userId, { [field]: value })
    Object.assign(p, updated)
    ElMessage.success(t('common.savedSuccess'))
  } catch {
    ElMessage.error(t('common.unexpectedError'))
    await loadPerms()
  }
}

watch(view, (v) => {
  if (v === 'permissions') loadPerms()
})

onMounted(loadEvents)
</script>

<template>
  <div>
    <div class="toolbar">
      <el-radio-group v-if="isAdmin" v-model="view" size="small">
        <el-radio-button value="events">{{ t('risk.tabEvents') }}</el-radio-button>
        <el-radio-button value="permissions">{{ t('risk.tabPermissions') }}</el-radio-button>
      </el-radio-group>

      <template v-if="view === 'events'">
        <el-select v-model="statusFilter" clearable :placeholder="t('common.status')" class="w-140" @change="applyFilter">
          <el-option value="open" :label="t('risk.statusOpen')" />
          <el-option value="reviewed" :label="t('risk.status_reviewed')" />
          <el-option value="confirmed" :label="t('risk.status_confirmed')" />
          <el-option value="dismissed" :label="t('risk.status_dismissed')" />
        </el-select>
        <el-button :icon="Refresh" @click="loadEvents" />
      </template>
    </div>

    <template v-if="view === 'events'">
      <el-table :data="events" v-loading="loading" :empty-text="t('risk.noEvents')">
        <el-table-column :label="t('promotions.time')" width="120">
          <template #default="{ row }">{{ new Date(row.createdAt).toLocaleDateString('ja-JP') }}</template>
        </el-table-column>
        <el-table-column :label="t('risk.type')" min-width="150">
          <template #default="{ row }">{{ t(`risk.type_${row.eventType}`, row.eventTypeDisplay) }}</template>
        </el-table-column>
        <el-table-column :label="t('risk.severity')" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="severityType(row.severity)">{{ t(`risk.sev_${row.severity}`) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('risk.subject')" min-width="140">
          <template #default="{ row }">
            <span v-if="row.customerName || row.customerPhone">{{ row.customerName || row.customerPhone }}</span>
            <span v-else-if="row.staffName">{{ t('risk.staffColon') }}{{ row.staffName }}</span>
            <span v-else>—</span>
            <span v-if="row.branchNameZh" class="muted"> · {{ row.branchNameZh }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('risk.evidence')" min-width="180">
          <template #default="{ row }"><span class="evidence">{{ evidenceText(row) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status !== 'open'" size="small" :type="row.status === 'confirmed' ? 'danger' : 'info'">
              {{ t(`risk.status_${row.status}`) }}
            </el-tag>
            <el-tag v-else size="small" type="warning">{{ t('risk.statusOpen') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="180" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'open'">
              <el-button size="small" text @click="review(row, 'dismissed')">{{ t('risk.dismiss') }}</el-button>
              <el-button size="small" text @click="review(row, 'reviewed')">{{ t('risk.ok') }}</el-button>
              <el-button size="small" text type="danger" @click="review(row, 'confirmed')">{{ t('risk.confirm') }}</el-button>
            </template>
            <span v-else-if="row.reviewNote" class="muted note">{{ row.reviewNote }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          :page-size="50"
          :total="total"
          layout="prev, pager, next, total"
          background
        />
      </div>
    </template>

    <template v-else>
      <p class="hint">{{ t('risk.permissionsHint') }}</p>
      <el-table :data="perms" v-loading="permsLoading" :empty-text="t('risk.noStaff')">
        <el-table-column prop="displayName" :label="t('promotions.custName')" min-width="120">
          <template #default="{ row }">{{ row.displayName || row.account }}</template>
        </el-table-column>
        <el-table-column prop="branchId" :label="t('promotions.branch')" width="120" />
        <el-table-column :label="t('risk.canVerify')" width="130">
          <template #default="{ row }">
            <el-switch :model-value="row.canVerifySpend" @update:model-value="(v: boolean) => togglePerm(row, 'canVerifySpend', v)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('risk.canRedeem')" width="130">
          <template #default="{ row }">
            <el-switch :model-value="row.canRedeemVoucher" @update:model-value="(v: boolean) => togglePerm(row, 'canRedeemVoucher', v)" />
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.w-140 {
  width: 140px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.muted {
  color: var(--text-tertiary);
}

.evidence {
  font-size: 12px;
  color: var(--text-secondary);
}

.note {
  font-size: 12px;
}

.hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0 0 12px;
}
</style>
