<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { ArrowDown, ArrowUp, Calendar, Delete, Download, Hide, Plus, Refresh, User, View } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import {
  createDabingPerson, createDabingRecord, createKyotoBatch, createKyotoPerson, createKyotoRecord,
  deleteDabingRecord, deleteKyotoRecord, fetchDabingPeople, fetchDabingRecords, fetchDabingStores,
  fetchKyotoBatches, fetchKyotoPeople, fetchKyotoRecords,
  type DabingPerson, type DabingRecord, type DabingStore, type KyotoDrawBatch, type KyotoPerson, type KyotoRecord,
} from '@/api/lottery'
import { todayJst } from '@/utils/format'
import { downloadTableExcel } from '@/utils/excelExport'

const { t } = useI18n()
const auth = useAuthStore()
type Module = 'dabing' | 'kyoto'
const activeModule = ref<Module>((localStorage.getItem('lottery_module') as Module) || 'dabing')
const loading = ref(false)
const saving = ref(false)
const downloading = ref(false)
const showPhones = ref(localStorage.getItem('lottery_show_phones') === 'true')

const dabingStores = ref<DabingStore[]>([])
const dabingPeople = ref<DabingPerson[]>([])
const dabingRecords = ref<DabingRecord[]>([])
const dabingDate = ref(todayJst())
const dabingStoreId = ref(localStorage.getItem('lottery_dabing_store') ?? '')
const dabingTime = ref(localStorage.getItem('lottery_dabing_time') ?? '')
const dabingOverviewStoreId = ref('all')
const dabingPersonId = ref('')
const dabingKeyword = ref('')

const kyotoPeople = ref<KyotoPerson[]>([])
const kyotoBatches = ref<KyotoDrawBatch[]>([])
const kyotoRecords = ref<KyotoRecord[]>([])
const kyotoBatchId = ref(localStorage.getItem('lottery_kyoto_batch') ?? '')
const kyotoPersonId = ref('')
const kyotoKeyword = ref('')
const expandedKyotoNames = ref<Record<string, boolean>>({})

const personDialog = ref(false)
const personModule = ref<Module>('dabing')
const personFormRef = ref<FormInstance>()
const personForm = reactive({ name: '', phone: '', contact: '', birthday: '', mobileModel: '', note: '' })
const batchDialog = ref(false)
const batchFormRef = ref<FormInstance>()
const batchForm = reactive({ drawStartDate: todayJst(), drawEndDate: todayJst(), publishDate: todayJst(), label: '' })

const personRules = computed<FormRules>(() => ({ name: [{ required: true, message: t('lottery.validateName'), trigger: 'blur' }] }))
const batchRules = computed<FormRules>(() => ({
  drawStartDate: [{ required: true, message: t('lottery.validateDate'), trigger: 'change' }],
  drawEndDate: [{ required: true, message: t('lottery.validateDate'), trigger: 'change' }],
  publishDate: [{ required: true, message: t('lottery.validateDate'), trigger: 'change' }],
}))

const overviewDabingStoreName = computed(() => dabingOverviewStoreId.value === 'all'
  ? t('lottery.allStores')
  : dabingStores.value.find((store) => store.id === dabingOverviewStoreId.value)?.name || '—')
const selectedKyotoBatch = computed(() => kyotoBatches.value.find((batch) => batch.id === kyotoBatchId.value))
const filteredDabingPeople = computed(() => filterPeople(dabingPeople.value, dabingKeyword.value))
const filteredKyotoPeople = computed(() => filterPeople(kyotoPeople.value, kyotoKeyword.value))

interface KyotoWinnerGroup {
  key: string
  name: string
  records: KyotoRecord[]
  phoneCount: number
}

const groupedKyotoRecords = computed<KyotoWinnerGroup[]>(() => {
  const groups = new Map<string, KyotoRecord[]>()
  for (const record of kyotoRecords.value) {
    const name = record.personName.trim() || t('lottery.unnamed')
    const key = name.toLocaleLowerCase()
    groups.set(key, [...(groups.get(key) || []), record])
  }
  return [...groups.entries()].map(([key, records]) => {
    const uniquePhones = new Set(records.map((record) => record.phone || record.phoneLastFour).filter(Boolean))
    return { key, name: records[0]?.personName.trim() || t('lottery.unnamed'), records, phoneCount: uniquePhones.size || records.length }
  })
})
const kyotoPhoneTotal = computed(() => groupedKyotoRecords.value.reduce((total, group) => total + group.phoneCount, 0))

function filterPeople<T extends { name: string; phone: string }>(people: T[], keyword: string) {
  const normalized = keyword.trim().toLowerCase()
  if (!normalized) return people
  return people.filter((person) => person.name.toLowerCase().includes(normalized) || person.phone.includes(normalized))
}

function selectModule(module: Module) {
  activeModule.value = module
  localStorage.setItem('lottery_module', module)
}

function formatPhone(phone: string, lastFour: string) {
  if (showPhones.value && phone) return phone
  if (lastFour) return `•••• ${lastFour}`
  return t('lottery.noPhone')
}

function toggleKyotoGroup(key: string) {
  expandedKyotoNames.value = { ...expandedKyotoNames.value, [key]: !expandedKyotoNames.value[key] }
}

function togglePhoneVisibility() {
  showPhones.value = !showPhones.value
  localStorage.setItem('lottery_show_phones', String(showPhones.value))
}

async function loadDabing() {
  const [stores, people] = await Promise.all([fetchDabingStores(), fetchDabingPeople()])
  dabingStores.value = stores
  dabingPeople.value = people
  if (!dabingStoreId.value || !stores.some((store) => store.id === dabingStoreId.value)) dabingStoreId.value = stores[0]?.id ?? ''
  await loadDabingRecords()
}

async function loadDabingRecords() {
  dabingRecords.value = await fetchDabingRecords({ date: dabingDate.value, storeId: dabingOverviewStoreId.value === 'all' ? undefined : dabingOverviewStoreId.value })
}

async function loadKyoto() {
  const [people, batches] = await Promise.all([fetchKyotoPeople(), fetchKyotoBatches()])
  kyotoPeople.value = people
  kyotoBatches.value = batches
  if (!kyotoBatchId.value || !batches.some((batch) => batch.id === kyotoBatchId.value)) {
    const today = todayJst()
    kyotoBatchId.value = batches.find((batch) => batch.publishDate === today)?.id ?? batches[0]?.id ?? ''
  }
  await loadKyotoRecords()
}

async function loadKyotoRecords() {
  kyotoRecords.value = await fetchKyotoRecords(kyotoBatchId.value || undefined)
  expandedKyotoNames.value = {}
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadDabing(), loadKyoto()])
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(dabingDate, loadDabingRecords)
watch(dabingStoreId, (value) => { if (value) localStorage.setItem('lottery_dabing_store', value) })
watch(dabingOverviewStoreId, loadDabingRecords)
watch(dabingTime, (value) => localStorage.setItem('lottery_dabing_time', value))
watch(kyotoBatchId, async (value) => {
  if (value) localStorage.setItem('lottery_kyoto_batch', value)
  await loadKyotoRecords()
})

function openPersonDialog(module: Module) {
  personModule.value = module
  Object.assign(personForm, { name: '', phone: '', contact: '', birthday: '', mobileModel: '', note: '' })
  personDialog.value = true
}

async function savePerson() {
  if (!personFormRef.value) return
  await personFormRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      if (personModule.value === 'dabing') {
        const person = await createDabingPerson({ name: personForm.name, phone: personForm.phone, contact: personForm.contact, birthday: personForm.birthday || null, mobileModel: personForm.mobileModel, note: personForm.note })
        dabingPeople.value = await fetchDabingPeople()
        dabingPersonId.value = person.id
      } else {
        const person = await createKyotoPerson({ name: personForm.name, phone: personForm.phone, note: personForm.note })
        kyotoPeople.value = await fetchKyotoPeople()
        kyotoPersonId.value = person.id
      }
      personDialog.value = false
      ElMessage.success(t('lottery.personSaved'))
    } finally {
      saving.value = false
    }
  })
}

async function saveDabingRecord() {
  if (!dabingDate.value || !dabingStoreId.value || !dabingPersonId.value) return ElMessage.warning(t('lottery.completeEntry'))
  saving.value = true
  try {
    await createDabingRecord({ storeId: dabingStoreId.value, personId: dabingPersonId.value, drawDate: dabingDate.value, drawTime: dabingTime.value })
    dabingPersonId.value = ''
    dabingKeyword.value = ''
    await loadDabingRecords()
    ElMessage.success(t('lottery.recordSaved'))
  } catch (error) {
    if (error instanceof ApiError && error.status === 400 && JSON.stringify(error.body).includes('record-already-exists')) ElMessage.warning(t('lottery.duplicateRecord'))
    else throw error
  } finally {
    saving.value = false
  }
}

async function saveKyotoRecord() {
  if (!kyotoBatchId.value || !kyotoPersonId.value) return ElMessage.warning(t('lottery.completeEntry'))
  saving.value = true
  try {
    await createKyotoRecord({ batchId: kyotoBatchId.value, personId: kyotoPersonId.value })
    kyotoPersonId.value = ''
    kyotoKeyword.value = ''
    await loadKyotoRecords()
    ElMessage.success(t('lottery.recordSaved'))
  } catch (error) {
    if (error instanceof ApiError && error.status === 400 && JSON.stringify(error.body).includes('record-already-exists')) ElMessage.warning(t('lottery.duplicateRecord'))
    else throw error
  } finally {
    saving.value = false
  }
}

async function removeDabingRecord(row: DabingRecord) {
  try {
    await ElMessageBox.confirm(t('lottery.deleteRecordConfirm'), t('common.confirm'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    await deleteDabingRecord(row.id)
    await loadDabingRecords()
    ElMessage.success(t('common.deletedSuccess'))
  } catch { /* cancelled */ }
}

async function removeKyotoRecord(row: KyotoRecord) {
  try {
    await ElMessageBox.confirm(t('lottery.deleteRecordConfirm'), t('common.confirm'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    await deleteKyotoRecord(row.id)
    await loadKyotoRecords()
    ElMessage.success(t('common.deletedSuccess'))
  } catch { /* cancelled */ }
}

function openBatchDialog() {
  Object.assign(batchForm, { drawStartDate: todayJst(), drawEndDate: todayJst(), publishDate: todayJst(), label: '' })
  batchDialog.value = true
}

async function saveBatch() {
  if (!batchFormRef.value) return
  await batchFormRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      const batch = await createKyotoBatch({ ...batchForm })
      kyotoBatches.value = await fetchKyotoBatches()
      kyotoBatchId.value = batch.id
      batchDialog.value = false
      ElMessage.success(t('lottery.batchSaved'))
    } finally {
      saving.value = false
    }
  })
}

async function exportDabing() {
  downloading.value = true
  try {
    await downloadTableExcel(`大饼中奖名单-${dabingDate.value}`, '大饼中奖名单', [
      { header: t('lottery.name'), key: 'name', width: 18 }, { header: t('lottery.phone'), key: 'phone', width: 18 },
      { header: t('lottery.store'), key: 'store', width: 14 }, { header: t('lottery.drawDate'), key: 'date', width: 14 },
      { header: t('lottery.drawTime'), key: 'time', width: 12 }, { header: t('lottery.mobileModel'), key: 'mobile', width: 18 },
    ], dabingRecords.value.map((row) => ({ name: row.personName, phone: row.phone, store: row.storeName, date: row.drawDate, time: row.drawTime, mobile: row.mobileModel })), 'landscape')
  } finally {
    downloading.value = false
  }
}

async function exportKyoto() {
  if (!selectedKyotoBatch.value) return
  downloading.value = true
  try {
    await downloadTableExcel(`京都爱电王中奖名单-${selectedKyotoBatch.value.displayLabel}`, '京都爱电王中奖名单', [
      { header: t('lottery.name'), key: 'name', width: 18 }, { header: t('lottery.phone'), key: 'phone', width: 20 },
      { header: t('lottery.drawPeriod'), key: 'period', width: 22 }, { header: t('lottery.publishDate'), key: 'publishDate', width: 16 },
    ], kyotoRecords.value.map((row) => ({ name: row.personName, phone: row.phone, period: `${row.drawStartDate}〜${row.drawEndDate}`, publishDate: row.publishDate })))
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <div class="lottery-view" v-loading="loading">
    <header class="lottery-hero"><div class="hero-copy"><span class="hero-kicker">LOTTERY WORKSPACE</span><h1>{{ t('lottery.pageTitle') }}</h1><p>{{ t('lottery.sharedWorkspace') }}</p></div><div class="operator-chip"><User :size="15" /> {{ auth.displayName || auth.account }}</div></header>
    <nav class="module-switcher" :aria-label="t('lottery.moduleSwitch')"><button type="button" class="module-choice dabing-choice" :class="{ active: activeModule === 'dabing' }" @click="selectModule('dabing')"><span class="choice-mark">大</span><span><strong>{{ t('lottery.dabing') }}</strong><small>{{ t('lottery.dabingShortHint') }}</small></span></button><button type="button" class="module-choice kyoto-choice" :class="{ active: activeModule === 'kyoto' }" @click="selectModule('kyoto')"><span class="choice-mark">愛</span><span><strong>{{ t('lottery.kyoto') }}</strong><small>{{ t('lottery.kyotoShortHint') }}</small></span></button></nav>

    <template v-if="activeModule === 'dabing'">
      <section class="entry-card card accent-dabing"><div class="section-heading"><div><span class="eyebrow">{{ t('lottery.quickEntry') }}</span><h2>{{ t('lottery.dabingEntryTitle') }}</h2></div><el-button text :icon="User" @click="openPersonDialog('dabing')">{{ t('lottery.addPerson') }}</el-button></div><div class="context-grid"><div><label>{{ t('lottery.drawDate') }}</label><el-date-picker v-model="dabingDate" type="date" value-format="YYYY-MM-DD" /></div><div><label>{{ t('lottery.store') }}</label><el-select v-model="dabingStoreId" :placeholder="t('lottery.selectStore')"><el-option v-for="store in dabingStores" :key="store.id" :label="store.name" :value="store.id" /></el-select></div><div><label>{{ t('lottery.drawTime') }}</label><el-input v-model="dabingTime" :placeholder="t('lottery.drawTimePlaceholder')" /></div></div><div class="quick-entry-row"><el-select v-model="dabingPersonId" filterable clearable :placeholder="t('lottery.namePlaceholder')" class="person-select"><el-option v-for="person in filteredDabingPeople" :key="person.id" :label="`${person.name}${person.phoneLastFour ? ` · ${person.phoneLastFour}` : ''}`" :value="person.id" /></el-select><el-button class="save-button" type="primary" :loading="saving" :disabled="!dabingPersonId" @click="saveDabingRecord">{{ t('lottery.saveRecord') }}</el-button></div><p class="entry-note">{{ t('lottery.dabingEntryHint') }}</p></section>
      <section class="card overview-card"><div class="section-heading"><div><span class="eyebrow">{{ t('lottery.overview') }}</span><h2>{{ dabingDate }} · {{ overviewDabingStoreName }}</h2></div><div class="heading-actions"><el-button text :icon="showPhones ? Hide : View" @click="togglePhoneVisibility">{{ showPhones ? t('lottery.hidePhones') : t('lottery.showPhones') }}</el-button><el-button text :icon="Refresh" @click="loadDabingRecords" /></div></div><div class="filter-row"><el-select v-model="dabingOverviewStoreId" class="overview-store-select"><el-option :label="t('lottery.allStores')" value="all" /><el-option v-for="store in dabingStores" :key="store.id" :label="store.name" :value="store.id" /></el-select><el-button type="primary" plain :icon="Download" :loading="downloading" @click="exportDabing">{{ t('lottery.exportExcel') }}</el-button></div><div class="stat-grid"><div class="stat"><strong>{{ dabingRecords.length }}</strong><span>{{ t('lottery.winnerCount') }}</span></div><div class="stat"><strong>{{ dabingStores.length }}</strong><span>{{ t('lottery.storeCount') }}</span></div><div class="stat"><strong>{{ dabingRecords.filter((row) => row.createdByName).length }}</strong><span>{{ t('lottery.multiUserRecords') }}</span></div></div><div v-if="dabingRecords.length" class="record-list"><article v-for="row in dabingRecords" :key="row.id" class="record-card"><div class="record-title"><strong>{{ row.personName }}</strong><span class="store-badge">{{ row.storeName }}</span></div><div class="record-detail"><span>{{ formatPhone(row.phone, row.phoneLastFour) }}</span><span v-if="row.mobileModel">{{ row.mobileModel }}</span><span v-if="row.drawTime">{{ row.drawTime }}</span></div><div class="record-footer"><span>{{ row.createdByName || t('lottery.importedRecord') }}</span><el-button text type="danger" :icon="Delete" @click="removeDabingRecord(row)" /></div></article></div><div v-else class="empty-state">{{ t('lottery.emptyRecords') }}</div></section>
    </template>

    <template v-else>
      <section class="entry-card card accent-kyoto"><div class="section-heading"><div><span class="eyebrow">{{ t('lottery.quickEntry') }}</span><h2>{{ t('lottery.kyotoEntryTitle') }}</h2></div><div class="heading-actions"><el-button text :icon="Plus" @click="openBatchDialog">{{ t('lottery.addBatch') }}</el-button><el-button text :icon="User" @click="openPersonDialog('kyoto')">{{ t('lottery.addPerson') }}</el-button></div></div><div v-if="kyotoBatches.length" class="context-grid one-line"><div><label>{{ t('lottery.drawBatch') }}</label><el-select v-model="kyotoBatchId" :placeholder="t('lottery.selectBatch')"><el-option v-for="batch in kyotoBatches" :key="batch.id" :label="`${batch.displayLabel} · ${batch.publishDate}`" :value="batch.id" /></el-select></div></div><div v-else class="empty-setup"><Calendar /><span>{{ t('lottery.noBatchHint') }}</span><el-button type="primary" plain @click="openBatchDialog">{{ t('lottery.addBatch') }}</el-button></div><div v-if="kyotoBatches.length" class="quick-entry-row"><el-select v-model="kyotoPersonId" filterable clearable :placeholder="t('lottery.namePlaceholder')" class="person-select"><el-option v-for="person in filteredKyotoPeople" :key="person.id" :label="`${person.name}${person.phoneLastFour ? ` · ${person.phoneLastFour}` : ''}`" :value="person.id" /></el-select><el-button class="save-button" type="primary" :loading="saving" :disabled="!kyotoPersonId" @click="saveKyotoRecord">{{ t('lottery.saveRecord') }}</el-button></div><p class="entry-note">{{ t('lottery.kyotoEntryHint') }}</p></section>
      <section class="card overview-card kyoto-overview"><div class="section-heading"><div><span class="eyebrow">{{ t('lottery.overview') }}</span><h2>{{ selectedKyotoBatch?.displayLabel || '—' }}</h2><p class="section-subtitle">{{ selectedKyotoBatch?.publishDate || '—' }} · {{ t('lottery.groupedByName') }}</p></div><div class="heading-actions"><el-button text :icon="showPhones ? Hide : View" @click="togglePhoneVisibility">{{ showPhones ? t('lottery.hidePhones') : t('lottery.showPhones') }}</el-button><el-button text :icon="Refresh" @click="loadKyotoRecords" /></div></div><div class="filter-row"><span class="privacy-note">{{ showPhones ? t('lottery.phoneVisible') : t('lottery.phoneHidden') }}</span><el-button type="primary" plain :icon="Download" :loading="downloading" :disabled="!selectedKyotoBatch" @click="exportKyoto">{{ t('lottery.exportExcel') }}</el-button></div><div class="stat-grid kyoto-stats"><div class="stat highlight"><strong>{{ groupedKyotoRecords.length }}</strong><span>{{ t('lottery.groupedWinnerCount') }}</span></div><div class="stat"><strong>{{ kyotoPhoneTotal }}</strong><span>{{ t('lottery.phoneCount') }}</span></div><div class="stat"><strong>{{ kyotoRecords.length }}</strong><span>{{ t('lottery.recordCount') }}</span></div></div><div v-if="groupedKyotoRecords.length" class="winner-list"><article v-for="group in groupedKyotoRecords" :key="group.key" class="winner-card" :class="{ expanded: expandedKyotoNames[group.key] }"><button type="button" class="winner-summary" @click="toggleKyotoGroup(group.key)"><span class="name-avatar">{{ group.name.slice(0, 1) }}</span><span class="winner-copy"><strong>{{ group.name }}</strong><small>{{ group.phoneCount }} {{ t('lottery.phoneCount') }} · {{ group.records.length }} {{ t('lottery.recordCount') }}</small></span><span class="expand-icon"><ArrowUp v-if="expandedKyotoNames[group.key]" /><ArrowDown v-else /></span></button><div v-if="expandedKyotoNames[group.key]" class="phone-list"><div v-for="row in group.records" :key="row.id" class="phone-row"><div><strong>{{ formatPhone(row.phone, row.phoneLastFour) }}</strong><small>{{ row.createdByName || t('lottery.importedRecord') }}</small></div><el-button text type="danger" :icon="Delete" @click="removeKyotoRecord(row)" /></div></div></article></div><div v-else class="empty-state">{{ t('lottery.emptyRecords') }}</div></section>
    </template>

    <el-dialog v-model="personDialog" :title="t('lottery.addPerson')" width="460px"><el-form ref="personFormRef" :model="personForm" :rules="personRules" label-position="top"><el-form-item :label="t('lottery.name')" prop="name"><el-input v-model="personForm.name" /></el-form-item><el-form-item :label="t('lottery.phone')"><el-input v-model="personForm.phone" /></el-form-item><el-form-item v-if="personModule === 'dabing'" :label="t('lottery.contact')"><el-input v-model="personForm.contact" /></el-form-item><el-form-item v-if="personModule === 'dabing'" :label="t('lottery.birthday')"><el-date-picker v-model="personForm.birthday" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item v-if="personModule === 'dabing'" :label="t('lottery.mobileModel')"><el-input v-model="personForm.mobileModel" /></el-form-item><el-form-item :label="t('common.note')"><el-input v-model="personForm.note" type="textarea" :rows="2" /></el-form-item></el-form><template #footer><el-button @click="personDialog = false">{{ t('common.cancel') }}</el-button><el-button type="primary" :loading="saving" @click="savePerson">{{ t('common.save') }}</el-button></template></el-dialog>
    <el-dialog v-model="batchDialog" :title="t('lottery.addBatch')" width="460px"><el-form ref="batchFormRef" :model="batchForm" :rules="batchRules" label-position="top"><el-form-item :label="t('lottery.drawStartDate')" prop="drawStartDate"><el-date-picker v-model="batchForm.drawStartDate" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item :label="t('lottery.drawEndDate')" prop="drawEndDate"><el-date-picker v-model="batchForm.drawEndDate" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item :label="t('lottery.publishDate')" prop="publishDate"><el-date-picker v-model="batchForm.publishDate" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item :label="t('lottery.batchLabel')"><el-input v-model="batchForm.label" :placeholder="t('lottery.batchLabelPlaceholder')" /></el-form-item></el-form><template #footer><el-button @click="batchDialog = false">{{ t('common.cancel') }}</el-button><el-button type="primary" :loading="saving" @click="saveBatch">{{ t('common.save') }}</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.lottery-view { display: flex; flex-direction: column; gap: 16px; max-width: 1120px; margin: 0 auto; }
.lottery-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; padding: 4px 2px 2px; }.hero-kicker, .eyebrow { color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }.hero-copy h1 { margin: 6px 0 4px; color: var(--text-primary); font-size: clamp(26px, 5vw, 38px); letter-spacing: -.04em; }.hero-copy p { margin: 0; color: var(--text-secondary); font-size: 13px; }.operator-chip { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); background: var(--surface); padding: 8px 12px; border-radius: 999px; box-shadow: var(--shadow-soft); font-size: 12px; white-space: nowrap; }
.module-switcher { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.module-choice { display: flex; align-items: center; gap: 12px; min-height: 74px; padding: 12px 16px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); color: var(--text-secondary); text-align: left; cursor: pointer; box-shadow: var(--shadow-soft); transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease; }.module-choice:hover { transform: translateY(-1px); }.module-choice.active { border-color: currentColor; box-shadow: 0 8px 24px rgba(18, 29, 52, .12); color: var(--text-primary); }.dabing-choice.active { color: #2367d1; background: linear-gradient(135deg, #eef5ff, var(--surface)); }.kyoto-choice.active { color: #b23b65; background: linear-gradient(135deg, #fff0f5, var(--surface)); }.choice-mark { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 13px; background: currentColor; color: white; font-size: 21px; font-weight: 800; }.module-choice span:last-child { display: flex; flex-direction: column; gap: 3px; }.module-choice strong { color: var(--text-primary); font-size: 15px; }.module-choice small { color: var(--text-secondary); font-size: 11px; }
.card { background: var(--surface); border-radius: 18px; padding: 20px 22px; box-shadow: var(--shadow-soft); border: 1px solid transparent; }.accent-dabing { border-top: 3px solid #2367d1; }.accent-kyoto { border-top: 3px solid #b23b65; }.section-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 18px; }.section-heading h2 { margin: 4px 0 0; color: var(--text-primary); font-size: 19px; }.section-subtitle { margin: 5px 0 0; color: var(--text-tertiary); font-size: 12px; }.heading-actions, .filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }.filter-row { justify-content: space-between; margin: -3px 0 16px; }.filter-row .el-button { margin-left: auto; }.context-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }.context-grid.one-line { grid-template-columns: minmax(260px, 500px); }.context-grid label { display: block; color: var(--text-secondary); font-size: 12px; margin-bottom: 6px; }.context-grid :deep(.el-date-editor), .context-grid :deep(.el-select), .context-grid :deep(.el-input) { width: 100%; }.quick-entry-row { display: flex; gap: 10px; }.person-select { flex: 1; }.save-button { min-width: 92px; }.entry-note, .privacy-note { color: var(--text-tertiary); font-size: 12px; margin: 12px 0 0; }.privacy-note { margin: 0; }
.overview-store-select { width: 140px; }.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }.stat { min-width: 0; padding: 13px 15px; background: var(--surface-alt); border-radius: 12px; }.stat.highlight { background: #fff0f5; }.stat strong { display: block; color: var(--text-primary); font-size: 24px; line-height: 1.1; }.stat span { display: block; color: var(--text-secondary); font-size: 11px; margin-top: 6px; }.record-list, .winner-list { display: flex; flex-direction: column; gap: 9px; }.record-card, .winner-card { border: 1px solid var(--border); border-radius: 13px; overflow: hidden; background: var(--surface); }.record-card { padding: 13px 14px 8px; }.record-title { display: flex; align-items: center; gap: 8px; }.record-title strong { color: var(--text-primary); font-size: 15px; }.store-badge { color: #2367d1; background: #eef5ff; border-radius: 999px; padding: 3px 8px; font-size: 11px; }.record-detail { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--text-secondary); font-size: 12px; margin-top: 10px; }.record-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 5px; color: var(--text-tertiary); font-size: 11px; }
.winner-summary { width: 100%; display: flex; align-items: center; gap: 11px; border: 0; padding: 14px; background: transparent; color: inherit; text-align: left; cursor: pointer; }.name-avatar { display: grid; place-items: center; width: 39px; height: 39px; flex: 0 0 39px; border-radius: 12px; background: #fff0f5; color: #b23b65; font-size: 18px; font-weight: 800; }.winner-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }.winner-copy strong { color: var(--text-primary); font-size: 16px; }.winner-copy small { color: var(--text-secondary); font-size: 12px; }.expand-icon { margin-left: auto; color: #b23b65; }.phone-list { border-top: 1px solid var(--border); padding: 4px 14px 6px 64px; background: var(--surface-alt); }.phone-row { display: flex; align-items: center; justify-content: space-between; min-height: 46px; border-bottom: 1px dashed var(--border); }.phone-row:last-child { border-bottom: 0; }.phone-row div { display: flex; flex-direction: column; gap: 3px; }.phone-row strong { color: var(--text-primary); font-size: 13px; letter-spacing: .02em; }.phone-row small { color: var(--text-tertiary); font-size: 11px; }.empty-state { padding: 26px 12px; color: var(--text-tertiary); text-align: center; }.empty-setup { display: flex; align-items: center; gap: 10px; color: var(--text-secondary); margin-bottom: 14px; }.empty-setup svg { color: #b23b65; width: 18px; }
@media (max-width: 720px) { .lottery-view { gap: 12px; }.lottery-hero { align-items: flex-start; flex-direction: column; gap: 9px; }.operator-chip { align-self: flex-start; }.module-choice { min-height: 68px; padding: 10px; gap: 9px; }.choice-mark { width: 36px; height: 36px; font-size: 18px; }.module-choice strong { font-size: 14px; }.module-choice small { font-size: 10px; }.card { padding: 16px 14px; border-radius: 15px; }.section-heading { flex-direction: column; gap: 9px; margin-bottom: 14px; }.section-heading .heading-actions { width: 100%; justify-content: flex-end; }.context-grid, .context-grid.one-line { grid-template-columns: 1fr; gap: 9px; }.quick-entry-row { flex-direction: column; }.save-button { width: 100%; min-height: 42px; }.filter-row { align-items: stretch; }.filter-row .el-button { margin-left: 0; }.overview-store-select { width: 100%; }.filter-row .overview-store-select + .el-button { flex: 1; }.stat-grid { gap: 7px; }.stat { padding: 11px 9px; }.stat strong { font-size: 20px; }.stat span { font-size: 10px; }.phone-list { padding-left: 64px; } }
</style>
