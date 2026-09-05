<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchPlatformOrganizations,
  fetchOrganizationUsers,
  setOrganizationFeature,
  setPlatformUserActive,
  type PlatformOrg,
  type PlatformUser,
} from '@/api/platform'
import { useDelayedLoading } from '@/composables/useDelayedLoading'

const { t, locale } = useI18n()
const { loading, run } = useDelayedLoading()
const orgs = ref<PlatformOrg[]>([])
const savingKey = ref('')
const usersByOrg = reactive<Record<number, PlatformUser[]>>({})
const expandedOrg = ref<number | null>(null)

function orgName(o: PlatformOrg) {
  return locale.value === 'ja' ? o.nameJa : o.nameZh
}
function featureName(f: { name_zh: string; name_ja: string }) {
  return locale.value === 'ja' ? f.name_ja : f.name_zh
}
function roleLabel(role: string) {
  return t(`platformFeatures.role.${role}`)
}

async function load() {
  await run(async () => {
    orgs.value = await fetchPlatformOrganizations()
  })
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

async function toggleAccounts(org: PlatformOrg) {
  if (expandedOrg.value === org.id) {
    expandedOrg.value = null
    return
  }
  expandedOrg.value = org.id
  if (!usersByOrg[org.id]) {
    try {
      usersByOrg[org.id] = await fetchOrganizationUsers(org.id)
    } catch {
      ElMessage.error(t('platformFeatures.loadUsersFailed'))
    }
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

onMounted(load)
</script>

<template>
  <div class="platform-features" v-loading="loading">
    <div class="card intro">
      <h2>{{ t('platformFeatures.title') }}</h2>
      <p>{{ t('platformFeatures.intro') }}</p>
    </div>

    <div v-for="org in orgs" :key="org.id" class="card org-card">
      <div class="org-head">
        <div>
          <span class="org-name">{{ orgName(org) }}</span>
          <span class="org-meta">{{ org.code }} · {{ t('platformFeatures.branchCount', { n: org.branchCount }) }}</span>
        </div>
        <el-button size="small" text @click="toggleAccounts(org)">
          {{ expandedOrg === org.id ? t('platformFeatures.hideAccounts') : t('platformFeatures.showAccounts') }}
        </el-button>
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

      <div v-if="expandedOrg === org.id" class="accounts">
        <div class="accounts-head">{{ t('platformFeatures.accountsTitle') }}</div>
        <div v-for="u in usersByOrg[org.id] ?? []" :key="u.id" class="account-row">
          <div class="account-info">
            <span class="account-name">{{ u.account }}</span>
            <el-tag size="small" round>{{ roleLabel(u.role) }}</el-tag>
            <el-tag v-if="u.isSuperuser" size="small" type="warning" round>{{ t('platformFeatures.role.superuser') }}</el-tag>
          </div>
          <el-switch
            :model-value="u.isActive"
            :loading="savingKey === `u:${u.id}`"
            :active-text="t('platformFeatures.userActive')"
            :inactive-text="t('platformFeatures.userInactive')"
            inline-prompt
            @update:model-value="(v: boolean) => toggleUser(org, u, v)"
          />
        </div>
        <p v-if="(usersByOrg[org.id] ?? []).length === 0" class="empty">—</p>
      </div>
    </div>
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
  margin-bottom: 12px;
}

.org-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.org-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 10px;
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

.accounts {
  margin-top: 14px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.accounts-head {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.account-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 4px;
  border-bottom: 1px solid var(--border);
}

.account-info {
  display: flex;
  align-items: center;
  gap: 8px;
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
