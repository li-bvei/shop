<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Edit, Delete, Switch } from '@element-plus/icons-vue'
import {
  fetchAllStaff, createStaff, updateStaff, deleteStaff,
  fetchStaffTransfers, createStaffTransfer, TransferHasFutureShiftsError,
  type StaffMember, type StaffTransfer,
} from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName, todayJst } from '@/utils/format'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const staffList = ref<StaffMember[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  branchId: '',
  role: '',
  workArea: 'hall' as StaffMember['workArea'],
  phone: '',
  status: 'active' as StaffMember['status'],
  employmentType: 'regular_monthly' as StaffMember['employmentType'],
  hireDate: null as string | null,
  leaveDate: null as string | null,
  note: '',
  wageHourlyRate: 0,
  wageTransportationAmount: 0,
  wageEffectiveFrom: todayJst(),
  wageNote: '',
})

const employmentTypeOptions: { value: StaffMember['employmentType']; labelKey: string }[] = [
  { value: 'regular_monthly', labelKey: 'staff.employmentTypeRegularMonthly' },
  { value: 'hourly', labelKey: 'staff.employmentTypeHourly' },
  { value: 'temporary', labelKey: 'staff.employmentTypeTemporary' },
]

const rules: FormRules = {
  name: [{ required: true, message: t('staff.validateName'), trigger: 'blur' }],
  branchId: [{ required: true, message: t('staff.validateBranch'), trigger: 'change' }],
}

function branchName(branchId: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === branchId), locale.value, branchId)
}

function employmentTypeLabel(type: StaffMember['employmentType']) {
  const option = employmentTypeOptions.find((o) => o.value === type)
  return option ? t(option.labelKey) : type
}

async function load() {
  loading.value = true
  try {
    staffList.value = await fetchAllStaff()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  await load()
})

function resetForm() {
  form.name = ''
  form.branchId = isAdmin.value ? (branchStore.list[0]?.id ?? '') : (auth.branchId ?? '')
  form.role = ''
  form.workArea = 'hall'
  form.phone = ''
  form.status = 'active'
  form.employmentType = 'regular_monthly'
  form.hireDate = null
  form.leaveDate = null
  form.note = ''
  form.wageHourlyRate = 0
  form.wageTransportationAmount = 0
  form.wageEffectiveFrom = form.hireDate ?? todayJst()
  form.wageNote = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: StaffMember) {
  editingId.value = row.id
  form.name = row.name
  form.branchId = row.branchId
  form.role = row.role
  form.workArea = row.workArea
  form.phone = row.phone
  form.status = row.status
  form.employmentType = row.employmentType
  form.hireDate = row.hireDate
  form.leaveDate = row.leaveDate
  form.note = row.note
  form.wageHourlyRate = row.wageSetting?.hourlyRate ?? 0
  form.wageTransportationAmount = row.wageSetting?.transportationAmount ?? 0
  form.wageEffectiveFrom = row.wageSetting?.effectiveFrom ?? row.hireDate ?? todayJst()
  form.wageNote = row.wageSetting?.note ?? ''
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      const payload: Omit<StaffMember, 'id'> = {
        name: form.name, branchId: form.branchId, role: form.role, workArea: form.workArea,
        phone: form.phone, status: form.status, employmentType: form.employmentType,
        hireDate: form.hireDate, leaveDate: form.leaveDate, note: form.note,
        wageSetting: form.employmentType === 'regular_monthly' ? null : {
          hourlyRate: form.wageHourlyRate,
          transportationAmount: form.wageTransportationAmount,
          effectiveFrom: form.wageEffectiveFrom || form.hireDate || todayJst(),
          note: form.wageNote,
        },
      }
      if (editingId.value) {
        await updateStaff(editingId.value, payload)
      } else {
        await createStaff(payload)
      }
      ElMessage.success(t('common.savedSuccess'))
      dialogVisible.value = false
      await load()
    } finally {
      submitting.value = false
    }
  })
}

async function handleDelete(row: StaffMember) {
  try {
    await ElMessageBox.confirm(t('staff.deleteConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deleteStaff(row.id)
    ElMessage.success(t('common.deletedSuccess'))
    await load()
  } catch {
    // cancelled
  }
}

const transferDialogVisible = ref(false)
const transferSubmitting = ref(false)
const transferTarget = ref<StaffMember | null>(null)
const transferHistory = ref<StaffTransfer[]>([])
const transferHistoryLoading = ref(false)
const transferForm = reactive({
  toBranchId: '',
  effectiveDate: todayJst(),
  reason: '',
})

async function openTransfer(row: StaffMember) {
  transferTarget.value = row
  transferForm.toBranchId = branchStore.list.find((b) => b.id !== row.branchId)?.id ?? ''
  transferForm.effectiveDate = todayJst()
  transferForm.reason = ''
  transferDialogVisible.value = true
  transferHistoryLoading.value = true
  try {
    transferHistory.value = await fetchStaffTransfers(row.id)
  } finally {
    transferHistoryLoading.value = false
  }
}

async function submitTransfer(force = false) {
  if (!transferTarget.value) return
  if (!force && transferForm.toBranchId === transferTarget.value.branchId) {
    ElMessage.warning(t('staff.transferSameBranch'))
    return
  }
  if (!force) {
    try {
      await ElMessageBox.confirm(t('staff.transferConfirm'), t('staff.transferTitle'), {
        type: 'warning',
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
      })
    } catch {
      return
    }
  }
  transferSubmitting.value = true
  try {
    await createStaffTransfer({
      employeeId: transferTarget.value.id,
      toBranchId: transferForm.toBranchId,
      effectiveDate: transferForm.effectiveDate,
      reason: transferForm.reason,
      force,
    })
    ElMessage.success(t('staff.transferSuccess'))
    transferDialogVisible.value = false
    await load()
  } catch (err) {
    if (err instanceof TransferHasFutureShiftsError) {
      const lines = err.shifts.map((s) => s.workDate).join('\n')
      try {
        await ElMessageBox.confirm(
          `${t('staff.transferFutureShiftsHint')}\n${lines}`,
          t('staff.transferFutureShiftsTitle'),
          {
            type: 'warning',
            confirmButtonText: t('staff.transferFutureShiftsForceConfirm'),
            cancelButtonText: t('common.cancel'),
          },
        )
        await submitTransfer(true)
      } catch {
        // cancelled — leave dialog open
      }
    } else {
      throw err
    }
  } finally {
    transferSubmitting.value = false
  }
}
</script>

<template>
  <div class="staff-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('staff.pageTitle') }}</h3>
        <el-button type="primary" :icon="Plus" @click="openCreate">{{ t('staff.add') }}</el-button>
      </div>

      <el-table :data="staffList" v-loading="loading" :empty-text="t('staff.empty')">
        <el-table-column prop="name" :label="t('staff.name')" min-width="120" />
        <el-table-column :label="t('staff.branch')" width="110">
          <template #default="{ row }">{{ branchName(row.branchId) }}</template>
        </el-table-column>
        <el-table-column prop="role" :label="t('staff.role')" min-width="120" />
        <el-table-column :label="t('staff.workArea')" width="100">
          <template #default="{ row }">{{ t(row.workArea === 'kitchen' ? 'staff.workAreaKitchen' : 'staff.workAreaHall') }}</template>
        </el-table-column>
        <el-table-column prop="phone" :label="t('staff.phone')" min-width="140" />
        <el-table-column :label="t('staff.employmentType')" width="120">
          <template #default="{ row }">{{ employmentTypeLabel(row.employmentType) }}</template>
        </el-table-column>
        <el-table-column :label="t('staff.status')" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" round>
              {{ row.status === 'active' ? t('staff.statusActive') : t('staff.statusInactive') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="150" fixed="right">
          <template #default="{ row }">
            <el-button circle text :icon="Edit" size="small" @click="openEdit(row)" />
            <el-button v-if="isAdmin" circle text :icon="Switch" size="small" :title="t('staff.transfer')" @click="openTransfer(row)" />
            <el-button circle text :icon="Delete" size="small" @click="handleDelete(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? t('staff.edit') : t('staff.add')" width="440px">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item :label="t('staff.name')" prop="name">
          <el-input v-model="form.name" :placeholder="t('staff.namePlaceholder')" />
        </el-form-item>
        <el-form-item v-if="!editingId && isAdmin" :label="t('staff.branch')" prop="branchId">
          <el-select v-model="form.branchId" style="width: 100%">
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="editingId" :label="t('staff.branch')">
          <span class="branch-readonly">{{ branchName(form.branchId) }}</span>
        </el-form-item>
        <el-form-item :label="t('staff.role')">
          <el-input v-model="form.role" :placeholder="t('staff.rolePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('staff.workArea')">
          <el-radio-group v-model="form.workArea">
            <el-radio-button value="kitchen">{{ t('staff.workAreaKitchen') }}</el-radio-button>
            <el-radio-button value="hall">{{ t('staff.workAreaHall') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('staff.phone')">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item :label="t('staff.employmentType')">
          <el-select v-model="form.employmentType" style="width: 100%">
            <el-option v-for="o in employmentTypeOptions" :key="o.value" :value="o.value" :label="t(o.labelKey)" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('staff.hireDate')">
          <el-date-picker v-model="form.hireDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" clearable />
        </el-form-item>
        <el-form-item :label="t('staff.leaveDate')">
          <el-date-picker v-model="form.leaveDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" clearable />
        </el-form-item>
        <el-form-item :label="t('staff.note')">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
        <div v-if="form.employmentType !== 'regular_monthly'" class="wage-settings">
          <h4>{{ t('staff.wageSettings') }}</h4>
          <div class="wage-grid">
            <el-form-item :label="t('wages.hourlyRate')">
              <el-input-number v-model="form.wageHourlyRate" :min="1" :controls="false" />
            </el-form-item>
            <el-form-item :label="t('wages.transportationAmount2')">
              <el-input-number v-model="form.wageTransportationAmount" :min="0" :controls="false" />
            </el-form-item>
          </div>
          <el-form-item :label="t('wages.effectiveFrom')">
            <el-date-picker v-model="form.wageEffectiveFrom" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('staff.wageNote')">
            <el-input v-model="form.wageNote" />
          </el-form-item>
        </div>
        <el-form-item :label="t('staff.status')">
          <el-switch
            v-model="form.status"
            active-value="active"
            inactive-value="inactive"
            :active-text="t('staff.statusActive')"
            :inactive-text="t('staff.statusInactive')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="transferDialogVisible" :title="t('staff.transferTitle')" width="480px">
      <template v-if="transferTarget">
        <el-form label-position="top">
          <el-form-item :label="t('staff.name')">
            <span>{{ transferTarget.name }}</span>
          </el-form-item>
          <el-form-item :label="t('staff.branch')">
            <span class="branch-readonly">{{ branchName(transferTarget.branchId) }}</span>
          </el-form-item>
          <el-form-item :label="t('staff.transferToBranch')">
            <el-select v-model="transferForm.toBranchId" style="width: 100%">
              <el-option
                v-for="b in branchStore.list.filter((b) => b.id !== transferTarget!.branchId)"
                :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('staff.transferEffectiveDate')">
            <el-date-picker v-model="transferForm.effectiveDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" :clearable="false" />
          </el-form-item>
          <el-form-item :label="t('staff.transferReason')">
            <el-input v-model="transferForm.reason" :placeholder="t('staff.transferReasonPlaceholder')" />
          </el-form-item>
        </el-form>

        <div class="transfer-history">
          <h4>{{ t('staff.transferHistory') }}</h4>
          <div v-loading="transferHistoryLoading">
            <p v-if="!transferHistory.length" class="transfer-history-empty">{{ t('staff.transferHistoryEmpty') }}</p>
            <ul v-else class="transfer-history-list">
              <li v-for="h in transferHistory" :key="h.id">
                {{ h.effectiveDate }}：{{ h.fromBranchName }} → {{ h.toBranchName }}
                <span class="transfer-history-meta">（{{ h.changedByName }}，{{ new Date(h.changedAt).toLocaleString(locale) }}）</span>
              </li>
            </ul>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="transferDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="transferSubmitting" @click="submitTransfer(false)">
          {{ t('staff.transferSubmit') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.page-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.branch-readonly {
  font-size: 14px;
  color: var(--text-secondary);
}

.transfer-history {
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.transfer-history h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.transfer-history-empty {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}

.transfer-history-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 140px;
  overflow-y: auto;
}

.transfer-history-meta {
  color: var(--text-tertiary);
}
</style>
