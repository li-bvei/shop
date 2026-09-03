<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, EditPen, Delete, Key, Rank, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import {
  fetchPaymentMethods,
  renamePaymentMethod,
  deletePaymentMethod,
  addPaymentMethod,
  reorderPaymentMethods,
  type PaymentMethodDef,
} from '@/api/masterData'
import {
  fetchAccounts,
  createAccount,
  updateAccount,
  deleteAccount,
  adminResetPassword,
  changeOwnPassword,
  fetchOrganization,
  updateOrganization,
  type CreateAccountPayload,
  type AccountRecord,
  type AccountRole,
} from '@/api/accounts'
import { fetchAllStaff, type StaffMember } from '@/api/staff'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName } from '@/utils/format'
import LangSwitch from '@/components/LangSwitch.vue'
import ThemeSwitch from '@/components/ThemeSwitch.vue'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const paymentMethods = ref<PaymentMethodDef[]>([])
const loading = ref(false)

// Brand logo shown on the customer-facing loyalty pages (admin only).
const orgLogoInput = ref('')
const orgLogoSaved = ref('')
const orgSaving = ref(false)

async function loadOrg() {
  if (!isAdmin.value) return
  try {
    const org = await fetchOrganization()
    orgLogoInput.value = org.logoUrl
    orgLogoSaved.value = org.logoUrl
  } catch {
    /* non-critical */
  }
}

async function saveOrgLogo() {
  orgSaving.value = true
  try {
    const org = await updateOrganization({ logoUrl: orgLogoInput.value.trim() })
    orgLogoInput.value = org.logoUrl
    orgLogoSaved.value = org.logoUrl
    ElMessage.success(t('common.savedSuccess'))
  } catch {
    ElMessage.error(t('common.unexpectedError'))
  } finally {
    orgSaving.value = false
  }
}
// Admin picks which branch's payment methods to manage; branch accounts are
// implicitly scoped to their own — payment methods are per-branch master
// data now, same as purchasing/staff.
const paymentMethodBranchId = ref('')
const effectivePaymentBranchId = computed(() => (isAdmin.value ? paymentMethodBranchId.value : (auth.branchId ?? '')))

function paymentMethodLabel(method: PaymentMethodDef) {
  return method.customName || (method.i18nKey ? t(method.i18nKey) : '')
}

async function loadPaymentMethods() {
  if (!effectivePaymentBranchId.value) return
  loading.value = true
  try {
    paymentMethods.value = await fetchPaymentMethods(effectivePaymentBranchId.value)
  } finally {
    loading.value = false
  }
}

watch(paymentMethodBranchId, loadPaymentMethods)

const accounts = ref<AccountRecord[]>([])
const allStaff = ref<StaffMember[]>([])

async function loadAccounts() {
  accounts.value = await fetchAccounts()
}

// Employees who don't already have a staff-role login account — the
// backend rejects a second account for the same employee outright, so this
// keeps the picker from offering a choice that would just 400 on submit.
const availableStaffForAccount = computed(() => {
  const linkedIds = new Set(
    accounts.value
      .filter((a) => a.staffMemberId && a.id !== accountEditingId.value)
      .map((a) => a.staffMemberId),
  )
  return allStaff.value.filter((s) => !linkedIds.has(s.id))
})

function staffMemberLabel(staffMemberId: string | null) {
  if (!staffMemberId) return ''
  return allStaff.value.find((s) => s.id === staffMemberId)?.name ?? staffMemberId
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  if (isAdmin.value) paymentMethodBranchId.value = branchStore.list[0]?.id ?? ''
  await loadPaymentMethods()
  if (isAdmin.value) {
    await loadAccounts()
    allStaff.value = await fetchAllStaff()
    await loadOrg()
  }
})

async function handleRename(method: PaymentMethodDef) {
  try {
    const { value } = await ElMessageBox.prompt(
      t('dailyReport.addPaymentMethodPlaceholder'),
      t('dailyReport.renamePaymentMethod'),
      {
        inputValue: paymentMethodLabel(method),
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        inputValidator: (value: string) => !!value?.trim(),
      },
    )
    await renamePaymentMethod(method.id, value.trim())
    await loadPaymentMethods()
  } catch {
    // cancelled
  }
}

async function handleDelete(method: PaymentMethodDef) {
  try {
    await ElMessageBox.confirm(t('dailyReport.deletePaymentMethodConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deletePaymentMethod(method.id)
    await loadPaymentMethods()
  } catch {
    // cancelled
  }
}

async function handleAdd() {
  try {
    const { value } = await ElMessageBox.prompt(
      t('dailyReport.addPaymentMethodPlaceholder'),
      t('dailyReport.addPaymentMethod'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        inputValidator: (value: string) => !!value?.trim(),
      },
    )
    await addPaymentMethod(effectivePaymentBranchId.value, value.trim())
    await loadPaymentMethods()
  } catch {
    // cancelled
  }
}

// --- drag-to-reorder ---
// Plain HTML5 drag-and-drop on the row list itself (no extra dependency) —
// the row order is reshuffled optimistically on drop, then persisted
// atomically; a failed save reloads from the server so the UI never drifts
// from what's actually stored.
const draggingId = ref<number | null>(null)
const dragOverId = ref<number | null>(null)

function handleDragStart(method: PaymentMethodDef) {
  draggingId.value = method.id
}

function handleDragOver(method: PaymentMethodDef) {
  dragOverId.value = method.id
}

function handleDragLeave(method: PaymentMethodDef) {
  if (dragOverId.value === method.id) dragOverId.value = null
}

async function persistOrder(list: PaymentMethodDef[]) {
  paymentMethods.value = list
  try {
    paymentMethods.value = await reorderPaymentMethods(effectivePaymentBranchId.value, list.map((m) => m.id))
  } catch {
    ElMessage.error(t('settings.paymentMethodReorderError'))
    await loadPaymentMethods()
  }
}

async function handleDrop(target: PaymentMethodDef) {
  dragOverId.value = null
  const sourceId = draggingId.value
  draggingId.value = null
  if (sourceId === null || sourceId === target.id) return

  const list = [...paymentMethods.value]
  const fromIndex = list.findIndex((m) => m.id === sourceId)
  const toIndex = list.findIndex((m) => m.id === target.id)
  if (fromIndex === -1 || toIndex === -1) return
  const [moved] = list.splice(fromIndex, 1)
  list.splice(toIndex, 0, moved!)
  await persistOrder(list)
}

// Keyboard-reachable equivalent of the drag handle — native HTML5
// drag-and-drop has no keyboard path at all, so this is the only way a
// keyboard-only user can reorder the list.
async function moveMethod(method: PaymentMethodDef, direction: -1 | 1) {
  const list = [...paymentMethods.value]
  const index = list.findIndex((m) => m.id === method.id)
  const targetIndex = index + direction
  if (index === -1 || targetIndex < 0 || targetIndex >= list.length) return
  const [moved] = list.splice(index, 1)
  list.splice(targetIndex, 0, moved!)
  await persistOrder(list)
}

// --- 分店管理 ---

const branchDialogVisible = ref(false)
const branchEditingId = ref<string | null>(null)
const branchSubmitting = ref(false)
const branchFormRef = ref<FormInstance>()
const branchForm = reactive({ nameZh: '', nameJa: '' })
const branchRules: FormRules = {
  nameZh: [{ required: true, message: t('settings.validateBranchNameZh'), trigger: 'blur' }],
  nameJa: [{ required: true, message: t('settings.validateBranchNameJa'), trigger: 'blur' }],
}

function openCreateBranch() {
  branchEditingId.value = null
  branchForm.nameZh = ''
  branchForm.nameJa = ''
  branchDialogVisible.value = true
}

function openEditBranch(branch: { id: string; nameZh: string; nameJa: string }) {
  branchEditingId.value = branch.id
  branchForm.nameZh = branch.nameZh
  branchForm.nameJa = branch.nameJa
  branchDialogVisible.value = true
}

async function handleSubmitBranch() {
  if (!branchFormRef.value) return
  await branchFormRef.value.validate(async (valid) => {
    if (!valid) return
    branchSubmitting.value = true
    try {
      if (branchEditingId.value) {
        await branchStore.update(branchEditingId.value, branchForm.nameZh, branchForm.nameJa)
      } else {
        await branchStore.add(branchForm.nameZh, branchForm.nameJa)
      }
      ElMessage.success(t('common.savedSuccess'))
      branchDialogVisible.value = false
    } finally {
      branchSubmitting.value = false
    }
  })
}

async function handleDeleteBranch(branch: { id: string; nameZh: string }) {
  try {
    await ElMessageBox.confirm(t('settings.deleteBranchConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await branchStore.remove(branch.id)
    ElMessage.success(t('common.deletedSuccess'))
  } catch (err) {
    if (err instanceof Error && err.message === 'branch-has-accounts') {
      ElMessage.warning(t('settings.deleteBranchHasAccounts'))
    }
    // otherwise: cancelled
  }
}

// --- 账号管理 ---

const accountDialogVisible = ref(false)
const accountEditingId = ref<number | null>(null)
const accountSubmitting = ref(false)
const accountFormRef = ref<FormInstance>()
const accountForm = reactive<{
  account: string
  password: string
  displayName: string
  role: AccountRole
  branchId: string | null
  staffMemberId: string | null
}>({
  account: '',
  password: '',
  displayName: '',
  role: 'branch',
  branchId: null,
  staffMemberId: null,
})
const accountRules = computed<FormRules>(() => ({
  account: [{ required: true, message: t('settings.validateAccountName'), trigger: 'blur' }],
  // Password is only entered when creating — editing an existing account
  // goes through the dedicated 重置密码 action instead.
  password: accountEditingId.value
    ? []
    : [{ required: true, message: t('settings.validatePassword'), trigger: 'blur' }],
  displayName: [{ required: true, message: t('settings.validateDisplayName'), trigger: 'blur' }],
  branchId: accountForm.role === 'branch'
    ? [{ required: true, message: t('settings.validateAccountBranch'), trigger: 'change' }]
    : [],
  staffMemberId: accountForm.role === 'staff'
    ? [{ required: true, message: t('settings.validateAccountStaffMember'), trigger: 'change' }]
    : [],
}))

function accountBranchLabel(branchId: string | null) {
  if (!branchId) return t('settings.accountRoleAdmin')
  return branchDisplayName(branchStore.list.find((b) => b.id === branchId), locale.value, branchId)
}

function openCreateAccount() {
  accountEditingId.value = null
  accountForm.account = ''
  accountForm.password = ''
  accountForm.displayName = ''
  accountForm.role = 'branch'
  accountForm.branchId = branchStore.list[0]?.id ?? null
  accountForm.staffMemberId = null
  accountDialogVisible.value = true
}

function openEditAccount(record: AccountRecord) {
  accountEditingId.value = record.id
  accountForm.account = record.account
  accountForm.displayName = record.displayName
  accountForm.role = record.role
  accountForm.branchId = record.branchId
  accountForm.staffMemberId = record.staffMemberId
  accountDialogVisible.value = true
}

async function handleSubmitAccount() {
  if (!accountFormRef.value) return
  await accountFormRef.value.validate(async (valid) => {
    if (!valid) return
    accountSubmitting.value = true
    try {
      if (accountEditingId.value) {
        await updateAccount(accountEditingId.value, {
          displayName: accountForm.displayName,
          branchId: accountForm.branchId,
        })
      } else {
        const payload: CreateAccountPayload = {
          account: accountForm.account,
          password: accountForm.password,
          displayName: accountForm.displayName,
          role: accountForm.role,
          branchId: accountForm.role === 'branch' ? accountForm.branchId : null,
          staffMemberId: accountForm.role === 'staff' ? accountForm.staffMemberId : undefined,
        }
        await createAccount(payload)
      }
      ElMessage.success(t('common.savedSuccess'))
      accountDialogVisible.value = false
      await loadAccounts()
    } catch (err) {
      if (err instanceof Error && err.message === 'employee-already-has-account') {
        ElMessage.warning(t('settings.employeeAlreadyHasAccount'))
      } else if (err instanceof Error && err.message === 'account-exists') {
        ElMessage.warning(t('settings.accountExists'))
      }
    } finally {
      accountSubmitting.value = false
    }
  })
}

async function handleDeleteAccount(record: AccountRecord) {
  try {
    await ElMessageBox.confirm(t('settings.deleteAccountConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deleteAccount(record.id)
    ElMessage.success(t('common.deletedSuccess'))
    await loadAccounts()
  } catch (err) {
    if (err instanceof Error && err.message === 'cannot-delete-self') {
      ElMessage.warning(t('settings.cannotDeleteSelf'))
    } else if (err instanceof Error && err.message === 'cannot-delete-last-admin') {
      ElMessage.warning(t('settings.cannotDeleteLastAdmin'))
    }
    // otherwise: cancelled
  }
}

async function handleResetPassword(record: AccountRecord) {
  try {
    const { value } = await ElMessageBox.prompt(
      t('settings.newPasswordPlaceholder'),
      t('settings.resetPasswordTitle', { account: record.account }),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        inputType: 'password',
        inputValidator: (value: string) => !!value?.trim() && value.trim().length >= 6,
        inputErrorMessage: t('settings.validatePasswordLength'),
      },
    )
    await adminResetPassword(record.id, value.trim())
    ElMessage.success(t('settings.passwordResetSuccess'))
  } catch {
    // cancelled
  }
}

// --- 修改密码（所有登录用户对自己的账号） ---

const passwordFormRef = ref<FormInstance>()
const passwordSubmitting = ref(false)
const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const passwordRules = computed<FormRules>(() => ({
  oldPassword: [{ required: true, message: t('settings.validateOldPassword'), trigger: 'blur' }],
  newPassword: [
    { required: true, message: t('settings.validateNewPassword'), trigger: 'blur' },
    { min: 6, message: t('settings.validatePasswordLength'), trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: t('settings.validateConfirmPassword'), trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        callback(value === passwordForm.newPassword ? undefined : new Error(t('settings.passwordMismatch')))
      },
      trigger: 'blur',
    },
  ],
}))

async function handleChangePassword() {
  if (!passwordFormRef.value) return
  await passwordFormRef.value.validate(async (valid) => {
    if (!valid) return
    passwordSubmitting.value = true
    try {
      await changeOwnPassword(passwordForm.oldPassword, passwordForm.newPassword)
      ElMessage.success(t('settings.passwordChangedSuccess'))
      passwordForm.oldPassword = ''
      passwordForm.newPassword = ''
      passwordForm.confirmPassword = ''
      passwordFormRef.value?.clearValidate()
    } catch (err) {
      if (err instanceof Error && err.message === 'invalid-old-password') {
        ElMessage.error(t('settings.invalidOldPassword'))
      }
    } finally {
      passwordSubmitting.value = false
    }
  })
}
</script>

<template>
  <div class="settings-view">
    <div class="card">
      <h3>{{ t('settings.preferenceSection') }}</h3>
      <p class="section-hint">{{ t('settings.preferenceHint') }}</p>
      <div class="preference-row">
        <span class="preference-label">{{ t('settings.languageLabel') }}</span>
        <LangSwitch />
      </div>
      <div class="preference-row">
        <span class="preference-label">{{ t('settings.themeLabel') }}</span>
        <ThemeSwitch />
      </div>
    </div>

    <div v-if="isAdmin" class="card">
      <h3>{{ t('settings.brandSection') }}</h3>
      <p class="section-hint">{{ t('settings.brandHint') }}</p>
      <div class="brand-row">
        <img v-if="orgLogoInput" :src="orgLogoInput" alt="" class="brand-preview" />
        <div v-else class="brand-preview brand-preview-empty">{{ t('settings.brandNoLogo') }}</div>
        <div class="brand-input">
          <el-input
            v-model="orgLogoInput"
            :placeholder="t('settings.brandLogoPlaceholder')"
            clearable
          />
          <el-button type="primary" :loading="orgSaving" :disabled="orgLogoInput === orgLogoSaved" @click="saveOrgLogo">
            {{ t('common.save') }}
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="!isAdmin" class="card">
      <h3>{{ t('settings.branchInfoSection') }}</h3>
      <p class="section-hint">{{ t('settings.branchInfoHint') }}</p>
      <div class="branch-list">
        <span v-for="b in branchStore.list" :key="b.id" class="branch-pill">{{ branchDisplayName(b, locale) }}</span>
      </div>
    </div>

    <div v-if="isAdmin" class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('settings.branchManageSection') }}</h3>
          <p class="section-hint">{{ t('settings.branchManageHint') }}</p>
        </div>
        <el-button type="primary" :icon="Plus" @click="openCreateBranch">{{ t('settings.addBranch') }}</el-button>
      </div>
      <el-table :data="branchStore.list">
        <el-table-column :label="t('settings.branchNameZh')" prop="nameZh" />
        <el-table-column :label="t('settings.branchNameJa')" prop="nameJa" />
        <el-table-column :label="t('common.actions')" width="110" fixed="right">
          <template #default="{ row }">
            <el-button circle text :icon="EditPen" size="small" @click="openEditBranch(row)" />
            <el-button circle text :icon="Delete" size="small" @click="handleDeleteBranch(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="isAdmin" class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('settings.accountManageSection') }}</h3>
          <p class="section-hint">{{ t('settings.accountManageHint') }}</p>
        </div>
        <el-button type="primary" :icon="Plus" @click="openCreateAccount">{{ t('settings.addAccount') }}</el-button>
      </div>
      <el-table :data="accounts">
        <el-table-column :label="t('settings.accountName')" prop="account" />
        <el-table-column :label="t('settings.displayName')" prop="displayName" />
        <el-table-column :label="t('settings.accountRole')" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'warning' : row.role === 'staff' ? 'success' : 'info'" round>
              {{
                row.role === 'admin' ? t('settings.accountRoleAdmin')
                  : row.role === 'staff' ? t('settings.accountRoleStaff')
                  : t('settings.accountRoleBranch')
              }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('settings.accountBranch')" min-width="140">
          <template #default="{ row }">
            {{ accountBranchLabel(row.branchId) }}
            <span v-if="row.role === 'staff'" class="staff-member-hint">（{{ staffMemberLabel(row.staffMemberId) }}）</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="140" fixed="right">
          <template #default="{ row }">
            <el-button circle text :icon="Key" size="small" @click="handleResetPassword(row)" />
            <el-button circle text :icon="EditPen" size="small" @click="openEditAccount(row)" />
            <el-button circle text :icon="Delete" size="small" @click="handleDeleteAccount(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('settings.paymentMethodSection') }}</h3>
          <p class="section-hint">{{ t('settings.paymentMethodHint') }}</p>
        </div>
        <el-button type="primary" :icon="Plus" @click="handleAdd">{{ t('dailyReport.addPaymentMethod') }}</el-button>
      </div>
      <el-select v-if="isAdmin" v-model="paymentMethodBranchId" class="branch-picker">
        <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
      </el-select>
      <p class="section-hint payment-method-drag-hint">{{ t('settings.paymentMethodDragHint') }}</p>
      <div class="payment-method-list" v-loading="loading">
        <div
          v-for="(method, index) in paymentMethods"
          :key="method.id"
          class="payment-method-row"
          :class="{ 'is-drag-over': dragOverId === method.id }"
          draggable="true"
          @dragstart="handleDragStart(method)"
          @dragover.prevent="handleDragOver(method)"
          @dragleave="handleDragLeave(method)"
          @drop.prevent="handleDrop(method)"
        >
          <span v-if="dragOverId === method.id" class="drop-indicator" aria-hidden="true" />
          <el-icon class="drag-handle"><Rank /></el-icon>
          <span class="method-name">{{ paymentMethodLabel(method) }}</span>
          <span v-if="method.protected" class="protected-badge">{{ t('settings.paymentMethodProtected') }}</span>
          <span class="move-buttons">
            <el-button
              circle text :icon="ArrowUp" size="small"
              :disabled="index === 0"
              :aria-label="t('settings.paymentMethodMoveUp')"
              @click="moveMethod(method, -1)"
            />
            <el-button
              circle text :icon="ArrowDown" size="small"
              :disabled="index === paymentMethods.length - 1"
              :aria-label="t('settings.paymentMethodMoveDown')"
              @click="moveMethod(method, 1)"
            />
          </span>
          <span class="method-actions">
            <template v-if="!method.protected">
              <el-button circle text :icon="EditPen" size="small" @click="handleRename(method)" />
              <el-button circle text :icon="Delete" size="small" @click="handleDelete(method)" />
            </template>
          </span>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>{{ t('settings.changePasswordSection') }}</h3>
      <p class="section-hint">{{ t('settings.changePasswordHint') }}</p>
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top" class="password-form">
        <el-form-item :label="t('settings.oldPassword')" prop="oldPassword">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('settings.newPassword')" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('settings.confirmPassword')" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="passwordSubmitting" @click="handleChangePassword">
          {{ t('settings.changePasswordSubmit') }}
        </el-button>
      </el-form>
    </div>

    <el-dialog
      v-model="branchDialogVisible"
      :title="branchEditingId ? t('settings.editBranch') : t('settings.addBranch')"
      width="420px"
    >
      <el-form ref="branchFormRef" :model="branchForm" :rules="branchRules" label-position="top">
        <el-form-item :label="t('settings.branchNameZh')" prop="nameZh">
          <el-input v-model="branchForm.nameZh" />
        </el-form-item>
        <el-form-item :label="t('settings.branchNameJa')" prop="nameJa">
          <el-input v-model="branchForm.nameJa" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="branchDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="branchSubmitting" @click="handleSubmitBranch">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="accountDialogVisible"
      :title="accountEditingId ? t('settings.editAccount') : t('settings.addAccount')"
      width="420px"
    >
      <el-form ref="accountFormRef" :model="accountForm" :rules="accountRules" label-position="top">
        <el-form-item :label="t('settings.accountName')" prop="account">
          <el-input v-model="accountForm.account" :disabled="!!accountEditingId" />
        </el-form-item>
        <el-form-item v-if="!accountEditingId" :label="t('settings.password')" prop="password">
          <el-input v-model="accountForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('settings.displayName')" prop="displayName">
          <el-input v-model="accountForm.displayName" />
        </el-form-item>
        <el-form-item :label="t('settings.accountRole')">
          <el-radio-group v-model="accountForm.role" :disabled="!!accountEditingId">
            <el-radio-button value="branch">{{ t('settings.accountRoleBranch') }}</el-radio-button>
            <el-radio-button value="staff">{{ t('settings.accountRoleStaff') }}</el-radio-button>
            <el-radio-button value="admin">{{ t('settings.accountRoleAdmin') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item
          v-if="accountForm.role === 'branch'"
          :label="t('settings.accountBranch')"
          prop="branchId"
        >
          <el-select v-model="accountForm.branchId" style="width: 100%">
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="accountForm.role === 'staff'"
          :label="t('settings.accountStaffMember')"
          prop="staffMemberId"
        >
          <el-select v-model="accountForm.staffMemberId" style="width: 100%" :disabled="!!accountEditingId">
            <el-option
              v-for="s in availableStaffForAccount"
              :key="s.id"
              :value="s.id"
              :label="`${s.name}（${branchDisplayName(branchStore.list.find((b) => b.id === s.branchId), locale, s.branchId)}）`"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="accountSubmitting" @click="handleSubmitAccount">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 720px;
}

.settings-view .card h3 {
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

.preference-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-top: 1px solid var(--border);
}

.brand-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.brand-preview {
  width: 72px;
  height: 72px;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: 8px;
  flex-shrink: 0;
}

.brand-preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 4px;
  box-sizing: border-box;
}

.brand-input {
  display: flex;
  gap: 8px;
  flex: 1;
}

.preference-label {
  font-size: 13.5px;
  color: var(--text-primary);
}

.branch-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.branch-pill {
  font-size: 12.5px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  padding: 6px 14px;
  border-radius: 20px;
  color: var(--text-secondary);
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.branch-picker {
  width: 200px;
  margin-bottom: 14px;
}

.payment-method-drag-hint {
  margin: -6px 0 10px;
}

.payment-method-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.payment-method-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: grab;
}

.payment-method-row.is-drag-over {
  border-color: var(--accent);
  background: var(--surface-alt);
}

.drop-indicator {
  position: absolute;
  left: 8px;
  right: 8px;
  top: -4px;
  height: 2px;
  border-radius: 1px;
  background: var(--accent);
}

.drag-handle {
  color: var(--text-tertiary);
  cursor: grab;
}

.move-buttons {
  display: flex;
  align-items: center;
  gap: 2px;
}

.method-name {
  flex: 1;
  font-size: 13.5px;
  color: var(--text-primary);
}

.protected-badge {
  font-size: 11px;
  color: var(--text-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 1px 8px;
}

.method-actions {
  display: flex;
  align-items: center;
  min-width: 64px;
  justify-content: flex-end;
}

.staff-member-hint {
  color: var(--text-tertiary);
  font-size: 12px;
}

.password-form {
  max-width: 320px;
}
</style>
