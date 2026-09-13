<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, EditPen, Delete, Key } from '@element-plus/icons-vue'
import {
  fetchPlatformOrganizations,
  fetchOrganizationUsers,
  setOrganizationFeature,
  setPlatformUserActive,
  createPlatformOrganization,
  updatePlatformOrganization,
  fetchPlatformBranches,
  createPlatformBranch,
  updatePlatformBranch,
  deletePlatformBranch,
  createPlatformUser,
  updatePlatformUser,
  deletePlatformUser,
  resetPlatformUserPassword,
  type PlatformOrg,
  type PlatformUser,
  type PlatformBranch,
} from '@/api/platform'
import { useDelayedLoading } from '@/composables/useDelayedLoading'

const { t, locale } = useI18n()
const { loading, run } = useDelayedLoading()
const orgs = ref<PlatformOrg[]>([])
const savingKey = ref('')
const usersByOrg = reactive<Record<number, PlatformUser[]>>({})
const branchesByOrg = reactive<Record<number, PlatformBranch[]>>({})
const expandedAccountsOrg = ref<number | null>(null)
const expandedBranchesOrg = ref<number | null>(null)

function orgName(o: PlatformOrg) {
  return locale.value === 'ja' ? o.nameJa : o.nameZh
}
function featureName(f: { name_zh: string; name_ja: string }) {
  return locale.value === 'ja' ? f.name_ja : f.name_zh
}
function roleLabel(role: string) {
  return t(`platformFeatures.role.${role}`)
}
function branchLabel(branchId: string | null, orgId: number) {
  if (!branchId) return t('platformFeatures.role.admin')
  return branchesByOrg[orgId]?.find((b) => b.id === branchId)?.nameZh ?? branchId
}

async function load() {
  await run(async () => {
    orgs.value = await fetchPlatformOrganizations()
  })
}

async function ensureBranchesLoaded(orgId: number) {
  if (!branchesByOrg[orgId]) {
    branchesByOrg[orgId] = await fetchPlatformBranches(orgId)
  }
}

async function toggleFeature(org: PlatformOrg, feature: string, enabled: boolean) {
  const key = `f:${org.id}:${feature}`
  savingKey.value = key
  try {
    const updated = await setOrganizationFeature(org.id, feature, enabled)
    const i = orgs.value.findIndex((o) => o.id === org.id)
    if (i !== -1) orgs.value[i] = updated
    ElMessage.success(t('platformFeatures.saved'))
  } catch {
    ElMessage.error(t('platformFeatures.saveFailed'))
    await load()
  } finally {
    savingKey.value = ''
  }
}

async function toggleOrgActive(org: PlatformOrg, active: boolean) {
  if (!active) {
    try {
      await ElMessageBox.confirm(
        t('platformFeatures.suspendOrgConfirm', { org: orgName(org) }),
        t('common.confirm'),
        { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
      )
    } catch {
      return
    }
  }
  const key = `org-active:${org.id}`
  savingKey.value = key
  try {
    await updatePlatformOrganization(org.id, { active })
    org.active = active
    ElMessage.success(t('platformFeatures.saved'))
  } catch {
    ElMessage.error(t('platformFeatures.saveFailed'))
  } finally {
    savingKey.value = ''
  }
}

async function handleRenameOrg(org: PlatformOrg) {
  try {
    const { value: nameZh } = await ElMessageBox.prompt(
      t('platformFeatures.renameOrgZhPlaceholder'), t('platformFeatures.renameOrgTitle'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputValue: org.nameZh },
    )
    const { value: nameJa } = await ElMessageBox.prompt(
      t('platformFeatures.renameOrgJaPlaceholder'), t('platformFeatures.renameOrgTitle'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputValue: org.nameJa },
    )
    const updated = await updatePlatformOrganization(org.id, { nameZh, nameJa })
    org.nameZh = updated.nameZh
    org.nameJa = updated.nameJa
    ElMessage.success(t('common.savedSuccess'))
  } catch {
    // cancelled
  }
}

async function toggleAccounts(org: PlatformOrg) {
  if (expandedAccountsOrg.value === org.id) {
    expandedAccountsOrg.value = null
    return
  }
  expandedAccountsOrg.value = org.id
  await ensureBranchesLoaded(org.id)
  if (!usersByOrg[org.id]) {
    try {
      usersByOrg[org.id] = await fetchOrganizationUsers(org.id)
    } catch {
      ElMessage.error(t('platformFeatures.loadUsersFailed'))
    }
  }
}

async function toggleBranches(org: PlatformOrg) {
  if (expandedBranchesOrg.value === org.id) {
    expandedBranchesOrg.value = null
    return
  }
  expandedBranchesOrg.value = org.id
  try {
    await ensureBranchesLoaded(org.id)
  } catch {
    ElMessage.error(t('common.unexpectedError'))
  }
}

async function toggleUser(org: PlatformOrg, user: PlatformUser, nextActive: boolean) {
  if (!nextActive) {
    try {
      await ElMessageBox.confirm(
        t('platformFeatures.disableUserConfirm', { account: user.account }),
        t('common.confirm'),
        { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
      )
    } catch {
      return
    }
  }
  const key = `u:${user.id}`
  savingKey.value = key
  try {
    const updated = await setPlatformUserActive(user.id, nextActive)
    const list = usersByOrg[org.id]
    const i = list?.findIndex((u) => u.id === user.id) ?? -1
    if (list && i !== -1) list[i] = updated
    ElMessage.success(nextActive ? t('platformFeatures.userEnabled') : t('platformFeatures.userDisabled'))
  } catch (err) {
    const msg = err instanceof Error ? err.message : ''
    if (msg.includes('currently logged in')) ElMessage.warning(t('platformFeatures.cannotDisableSelf'))
    else if (msg.includes('at least one active admin')) ElMessage.warning(t('platformFeatures.cannotDisableLastAdmin'))
    else ElMessage.error(t('platformFeatures.saveFailed'))
  } finally {
    savingKey.value = ''
  }
}

// ---- Account create/edit/delete/reset-password ---------------------------
// Deliberately admin/branch roles only — a staff-role login links to one
// specific employee record, which the platform super admin has no
// cross-tenant view into (that's each chain's own Settings screen). Not
// needed for the onboarding-a-new-store use case this is for.

const accountDialogVisible = ref(false)
const accountDialogOrg = ref<PlatformOrg | null>(null)
const accountEditingId = ref<number | null>(null)
const accountSubmitting = ref(false)
const accountFormRef = ref<FormInstance>()
const accountForm = reactive<{ account: string; password: string; displayName: string; role: 'admin' | 'branch'; branchId: string | null }>({
  account: '', password: '', displayName: '', role: 'branch', branchId: null,
})
const accountRules = computed<FormRules>(() => ({
  account: [{ required: true, message: t('settings.validateAccountName'), trigger: 'blur' }],
  password: accountEditingId.value ? [] : [{ required: true, message: t('settings.validatePassword'), trigger: 'blur' }],
  displayName: [{ required: true, message: t('settings.validateDisplayName'), trigger: 'blur' }],
  branchId: accountForm.role === 'branch'
    ? [{ required: true, message: t('settings.validateAccountBranch'), trigger: 'change' }]
    : [],
}))

function openCreateAccount(org: PlatformOrg) {
  accountDialogOrg.value = org
  accountEditingId.value = null
  accountForm.account = ''
  accountForm.password = ''
  accountForm.displayName = ''
  accountForm.role = 'branch'
  accountForm.branchId = branchesByOrg[org.id]?.[0]?.id ?? null
  accountDialogVisible.value = true
}

function openEditAccount(org: PlatformOrg, user: PlatformUser) {
  if (user.role === 'staff') return
  accountDialogOrg.value = org
  accountEditingId.value = user.id
  accountForm.account = user.account
  accountForm.displayName = user.displayName
  accountForm.role = user.role
  accountForm.branchId = user.branchId
  accountDialogVisible.value = true
}

async function handleSubmitAccount() {
  if (!accountFormRef.value || !accountDialogOrg.value) return
  const org = accountDialogOrg.value
  await accountFormRef.value.validate(async (valid) => {
    if (!valid) return
    accountSubmitting.value = true
    try {
      if (accountEditingId.value) {
        const updated = await updatePlatformUser(accountEditingId.value, {
          displayName: accountForm.displayName, branchId: accountForm.branchId,
        })
        const list = usersByOrg[org.id]
        const i = list?.findIndex((u) => u.id === accountEditingId.value) ?? -1
        if (list && i !== -1) list[i] = updated
      } else {
        const created = await createPlatformUser(org.id, {
          account: accountForm.account, password: accountForm.password, displayName: accountForm.displayName,
          role: accountForm.role, branchId: accountForm.role === 'branch' ? accountForm.branchId : null,
        })
        usersByOrg[org.id] = [...(usersByOrg[org.id] ?? []), created]
      }
      ElMessage.success(t('common.savedSuccess'))
      accountDialogVisible.value = false
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('account-exists')) ElMessage.warning(t('settings.accountExists'))
      else ElMessage.error(t('common.saveFailed'))
    } finally {
      accountSubmitting.value = false
    }
  })
}

async function handleDeleteAccount(org: PlatformOrg, user: PlatformUser) {
  try {
    await ElMessageBox.confirm(t('settings.deleteAccountConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
    })
    await deletePlatformUser(user.id)
    usersByOrg[org.id] = (usersByOrg[org.id] ?? []).filter((u) => u.id !== user.id)
    ElMessage.success(t('common.deletedSuccess'))
  } catch (err) {
    const msg = err instanceof Error ? err.message : ''
    if (msg.includes('at least one admin')) ElMessage.warning(t('settings.cannotDeleteLastAdmin'))
    // otherwise: cancelled, or a real error already shown by the global handler
  }
}

async function handleResetPassword(user: PlatformUser) {
  try {
    const { value } = await ElMessageBox.prompt(
      t('settings.newPasswordPlaceholder'), t('settings.resetPasswordTitle', { account: user.account }),
      {
        confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputType: 'password',
        inputValidator: (value: string) => !!value?.trim() && value.trim().length >= 6,
        inputErrorMessage: t('settings.validatePasswordLength'),
      },
    )
    await resetPlatformUserPassword(user.id, value.trim())
    ElMessage.success(t('settings.passwordResetSuccess'))
  } catch {
    // cancelled
  }
}

// ---- Branch create/edit/delete --------------------------------------------

const branchDialogVisible = ref(false)
const branchDialogOrg = ref<PlatformOrg | null>(null)
const branchEditingId = ref<string | null>(null)
const branchSubmitting = ref(false)
const branchFormRef = ref<FormInstance>()
const branchForm = reactive({ code: '', nameZh: '', nameJa: '' })
const branchRules: FormRules = {
  code: [{ required: true, message: t('platformFeatures.validateBranchCode'), trigger: 'blur' }],
  nameZh: [{ required: true, message: t('settings.validateBranchNameZh'), trigger: 'blur' }],
  nameJa: [{ required: true, message: t('settings.validateBranchNameJa'), trigger: 'blur' }],
}

function openCreateBranch(org: PlatformOrg) {
  branchDialogOrg.value = org
  branchEditingId.value = null
  branchForm.code = ''
  branchForm.nameZh = ''
  branchForm.nameJa = ''
  branchDialogVisible.value = true
}

function openEditBranch(org: PlatformOrg, branch: PlatformBranch) {
  branchDialogOrg.value = org
  branchEditingId.value = branch.id
  branchForm.code = branch.code
  branchForm.nameZh = branch.nameZh
  branchForm.nameJa = branch.nameJa
  branchDialogVisible.value = true
}

async function handleSubmitBranch() {
  if (!branchFormRef.value || !branchDialogOrg.value) return
  const org = branchDialogOrg.value
  await branchFormRef.value.validate(async (valid) => {
    if (!valid) return
    branchSubmitting.value = true
    try {
      if (branchEditingId.value) {
        const updated = await updatePlatformBranch(branchEditingId.value, {
          nameZh: branchForm.nameZh, nameJa: branchForm.nameJa,
        })
        const list = branchesByOrg[org.id]
        const i = list?.findIndex((b) => b.id === branchEditingId.value) ?? -1
        if (list && i !== -1) list[i] = updated
      } else {
        const created = await createPlatformBranch(org.id, branchForm)
        branchesByOrg[org.id] = [...(branchesByOrg[org.id] ?? []), created]
        org.branchCount += 1
      }
      ElMessage.success(t('common.savedSuccess'))
      branchDialogVisible.value = false
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('branch-code-already-exists')) ElMessage.warning(t('platformFeatures.branchCodeExists'))
      else ElMessage.error(t('common.saveFailed'))
    } finally {
      branchSubmitting.value = false
    }
  })
}

async function handleDeleteBranch(org: PlatformOrg, branch: PlatformBranch) {
  try {
    await ElMessageBox.confirm(t('settings.deleteBranchConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
    })
    await deletePlatformBranch(branch.id)
    branchesByOrg[org.id] = (branchesByOrg[org.id] ?? []).filter((b) => b.id !== branch.id)
    org.branchCount -= 1
    ElMessage.success(t('common.deletedSuccess'))
  } catch (err) {
    const msg = err instanceof Error ? err.message : ''
    if (msg.includes('branch-has-accounts')) ElMessage.warning(t('settings.deleteBranchHasAccounts'))
    // otherwise: cancelled
  }
}

// ---- New tenant ------------------------------------------------------------

const newOrgDialogVisible = ref(false)
const newOrgSubmitting = ref(false)
const newOrgFormRef = ref<FormInstance>()
const newOrgIncludeBranch = ref(false)
const newOrgIncludeAdmin = ref(false)
const newOrgForm = reactive({
  code: '', nameZh: '', nameJa: '',
  branchCode: '', branchNameZh: '', branchNameJa: '',
  adminAccount: '', adminPassword: '',
})
const newOrgRules = computed<FormRules>(() => ({
  code: [{ required: true, message: t('platformFeatures.validateOrgCode'), trigger: 'blur' }],
  nameZh: [{ required: true, message: t('settings.validateBranchNameZh'), trigger: 'blur' }],
  nameJa: [{ required: true, message: t('settings.validateBranchNameJa'), trigger: 'blur' }],
  branchCode: newOrgIncludeBranch.value ? [{ required: true, message: t('platformFeatures.validateBranchCode'), trigger: 'blur' }] : [],
  branchNameZh: newOrgIncludeBranch.value ? [{ required: true, message: t('settings.validateBranchNameZh'), trigger: 'blur' }] : [],
  branchNameJa: newOrgIncludeBranch.value ? [{ required: true, message: t('settings.validateBranchNameJa'), trigger: 'blur' }] : [],
  adminAccount: newOrgIncludeAdmin.value ? [{ required: true, message: t('settings.validateAccountName'), trigger: 'blur' }] : [],
  adminPassword: newOrgIncludeAdmin.value ? [{ required: true, message: t('settings.validatePassword'), trigger: 'blur' }] : [],
}))

function openNewOrg() {
  newOrgForm.code = ''
  newOrgForm.nameZh = ''
  newOrgForm.nameJa = ''
  newOrgForm.branchCode = ''
  newOrgForm.branchNameZh = ''
  newOrgForm.branchNameJa = ''
  newOrgForm.adminAccount = ''
  newOrgForm.adminPassword = ''
  newOrgIncludeBranch.value = true
  newOrgIncludeAdmin.value = true
  newOrgDialogVisible.value = true
}

async function handleSubmitNewOrg() {
  if (!newOrgFormRef.value) return
  await newOrgFormRef.value.validate(async (valid) => {
    if (!valid) return
    newOrgSubmitting.value = true
    try {
      const created = await createPlatformOrganization({
        code: newOrgForm.code, nameZh: newOrgForm.nameZh, nameJa: newOrgForm.nameJa,
        ...(newOrgIncludeBranch.value ? {
          branchCode: newOrgForm.branchCode, branchNameZh: newOrgForm.branchNameZh, branchNameJa: newOrgForm.branchNameJa,
        } : {}),
        ...(newOrgIncludeAdmin.value ? {
          adminAccount: newOrgForm.adminAccount, adminPassword: newOrgForm.adminPassword,
        } : {}),
      })
      orgs.value = [...orgs.value, created]
      ElMessage.success(t('common.savedSuccess'))
      newOrgDialogVisible.value = false
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('organization-code-already-exists')) ElMessage.warning(t('platformFeatures.orgCodeExists'))
      else if (msg.includes('admin-account-already-exists')) ElMessage.warning(t('settings.accountExists'))
      else ElMessage.error(t('common.saveFailed'))
    } finally {
      newOrgSubmitting.value = false
    }
  })
}

onMounted(load)
</script>

<template>
  <div class="platform-features" v-loading="loading">
    <div class="card intro">
      <div class="intro-row">
        <div>
          <h2>{{ t('platformFeatures.title') }}</h2>
          <p>{{ t('platformFeatures.intro') }}</p>
        </div>
        <el-button type="primary" :icon="Plus" @click="openNewOrg">{{ t('platformFeatures.newOrg') }}</el-button>
      </div>
    </div>

    <div v-for="org in orgs" :key="org.id" class="card org-card">
      <div class="org-head">
        <div>
          <span class="org-name">{{ orgName(org) }}</span>
          <el-button circle text :icon="EditPen" size="small" @click="handleRenameOrg(org)" />
          <span class="org-meta">{{ org.code }} · {{ t('platformFeatures.branchCount', { n: org.branchCount }) }}</span>
          <el-tag v-if="!org.active" size="small" type="danger" round>{{ t('platformFeatures.suspended') }}</el-tag>
        </div>
        <div class="org-actions">
          <el-switch
            :model-value="org.active"
            :loading="savingKey === `org-active:${org.id}`"
            :active-text="t('platformFeatures.orgActive')"
            :inactive-text="t('platformFeatures.orgSuspended')"
            inline-prompt
            @update:model-value="(v: boolean) => toggleOrgActive(org, v)"
          />
          <el-button size="small" text @click="toggleBranches(org)">
            {{ expandedBranchesOrg === org.id ? t('platformFeatures.hideBranches') : t('platformFeatures.showBranches') }}
          </el-button>
          <el-button size="small" text @click="toggleAccounts(org)">
            {{ expandedAccountsOrg === org.id ? t('platformFeatures.hideAccounts') : t('platformFeatures.showAccounts') }}
          </el-button>
        </div>
      </div>

      <div class="feature-grid">
        <label v-for="f in org.features" :key="f.feature" class="feature-row">
          <span class="feature-name">{{ featureName(f) }}</span>
          <el-switch
            :model-value="f.enabled"
            :loading="savingKey === `f:${org.id}:${f.feature}`"
            @update:model-value="(v: boolean) => toggleFeature(org, f.feature, v)"
          />
        </label>
      </div>

      <div v-if="expandedBranchesOrg === org.id" class="sub-section">
        <div class="sub-section-head">
          <span>{{ t('platformFeatures.branchesTitle') }}</span>
          <el-button size="small" :icon="Plus" text @click="openCreateBranch(org)">{{ t('settings.addBranch') }}</el-button>
        </div>
        <div v-for="b in branchesByOrg[org.id] ?? []" :key="b.id" class="sub-row">
          <span class="sub-row-name">{{ b.nameZh }}（{{ b.nameJa }}）</span>
          <span class="sub-row-meta">{{ t('platformFeatures.accountCount', { n: b.accountCount }) }}</span>
          <span class="sub-row-actions">
            <el-button circle text :icon="EditPen" size="small" @click="openEditBranch(org, b)" />
            <el-button circle text :icon="Delete" size="small" @click="handleDeleteBranch(org, b)" />
          </span>
        </div>
        <p v-if="(branchesByOrg[org.id] ?? []).length === 0" class="empty">—</p>
      </div>

      <div v-if="expandedAccountsOrg === org.id" class="sub-section">
        <div class="sub-section-head">
          <span>{{ t('platformFeatures.accountsTitle') }}</span>
          <el-button size="small" :icon="Plus" text @click="openCreateAccount(org)">{{ t('settings.addAccount') }}</el-button>
        </div>
        <div v-for="u in usersByOrg[org.id] ?? []" :key="u.id" class="account-row">
          <div class="account-info">
            <span class="account-name">{{ u.account }}</span>
            <el-tag size="small" round>{{ roleLabel(u.role) }}</el-tag>
            <el-tag v-if="u.isSuperuser" size="small" type="warning" round>{{ t('platformFeatures.role.superuser') }}</el-tag>
            <span v-if="u.role === 'branch'" class="sub-row-meta">{{ branchLabel(u.branchId, org.id) }}</span>
          </div>
          <div class="account-row-actions">
            <el-switch
              :model-value="u.isActive"
              :loading="savingKey === `u:${u.id}`"
              :active-text="t('platformFeatures.userActive')"
              :inactive-text="t('platformFeatures.userInactive')"
              inline-prompt
              @update:model-value="(v: boolean) => toggleUser(org, u, v)"
            />
            <template v-if="u.role !== 'staff'">
              <el-button circle text :icon="Key" size="small" @click="handleResetPassword(u)" />
              <el-button circle text :icon="EditPen" size="small" @click="openEditAccount(org, u)" />
              <el-button circle text :icon="Delete" size="small" @click="handleDeleteAccount(org, u)" />
            </template>
          </div>
        </div>
        <p v-if="(usersByOrg[org.id] ?? []).length === 0" class="empty">—</p>
      </div>
    </div>

    <el-dialog v-model="newOrgDialogVisible" :title="t('platformFeatures.newOrg')" width="480px">
      <el-form ref="newOrgFormRef" :model="newOrgForm" :rules="newOrgRules" label-position="top">
        <el-form-item :label="t('platformFeatures.orgCode')" prop="code">
          <el-input v-model="newOrgForm.code" placeholder="e.g. kansai-group" />
        </el-form-item>
        <el-form-item :label="t('settings.brandNameZh')" prop="nameZh">
          <el-input v-model="newOrgForm.nameZh" />
        </el-form-item>
        <el-form-item :label="t('settings.brandNameJa')" prop="nameJa">
          <el-input v-model="newOrgForm.nameJa" />
        </el-form-item>

        <el-checkbox v-model="newOrgIncludeBranch">{{ t('platformFeatures.includeFirstBranch') }}</el-checkbox>
        <template v-if="newOrgIncludeBranch">
          <el-form-item :label="t('platformFeatures.orgCode')" prop="branchCode">
            <el-input v-model="newOrgForm.branchCode" placeholder="e.g. honten" />
          </el-form-item>
          <el-form-item :label="t('settings.branchNameZh')" prop="branchNameZh">
            <el-input v-model="newOrgForm.branchNameZh" />
          </el-form-item>
          <el-form-item :label="t('settings.branchNameJa')" prop="branchNameJa">
            <el-input v-model="newOrgForm.branchNameJa" />
          </el-form-item>
        </template>

        <el-checkbox v-model="newOrgIncludeAdmin">{{ t('platformFeatures.includeFirstAdmin') }}</el-checkbox>
        <template v-if="newOrgIncludeAdmin">
          <el-form-item :label="t('settings.accountName')" prop="adminAccount">
            <el-input v-model="newOrgForm.adminAccount" />
          </el-form-item>
          <el-form-item :label="t('settings.password')" prop="adminPassword">
            <el-input v-model="newOrgForm.adminPassword" type="password" show-password />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="newOrgDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="newOrgSubmitting" @click="handleSubmitNewOrg">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="branchDialogVisible" :title="branchEditingId ? t('settings.editBranch') : t('settings.addBranch')" width="420px">
      <el-form ref="branchFormRef" :model="branchForm" :rules="branchRules" label-position="top">
        <el-form-item :label="t('platformFeatures.orgCode')" prop="code">
          <el-input v-model="branchForm.code" :disabled="!!branchEditingId" />
        </el-form-item>
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

    <el-dialog v-model="accountDialogVisible" :title="accountEditingId ? t('settings.editAccount') : t('settings.addAccount')" width="420px">
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
            <el-radio-button value="admin">{{ t('settings.accountRoleAdmin') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="accountForm.role === 'branch'" :label="t('settings.accountBranch')" prop="branchId">
          <el-select v-model="accountForm.branchId" style="width: 100%">
            <el-option v-for="b in (accountDialogOrg ? branchesByOrg[accountDialogOrg.id] : []) ?? []" :key="b.id" :value="b.id" :label="b.nameZh" />
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
.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 18px 20px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.intro-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.intro h2 {
  font-size: 16px;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.intro p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.org-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.org-head > div:first-child {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.org-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.org-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.org-meta {
  font-size: 12px;
  color: var(--text-tertiary);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px 20px;
}

.feature-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.feature-name {
  font-size: 13px;
  color: var(--text-primary);
}

.sub-section {
  margin-top: 14px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.sub-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.sub-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border);
}

.sub-row-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.sub-row-meta {
  font-size: 12px;
  color: var(--text-tertiary);
}

.sub-row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.account-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  gap: 8px;
}

.account-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.account-row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.account-name {
  font-size: 13px;
  color: var(--text-primary);
}

.empty {
  color: var(--text-tertiary);
  font-size: 13px;
  margin: 4px 0 0;
}
</style>
