<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus, Refresh } from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { ApiError } from '@/api/http'
import CampaignPrizesDrawer from '@/components/CampaignPrizesDrawer.vue'
import CampaignReportPanel from '@/components/CampaignReportPanel.vue'
import RiskEventsPanel from '@/components/RiskEventsPanel.vue'
import {
  adjustCustomerPoints,
  createCampaign,
  deleteCampaign,
  deleteCustomer,
  fetchCampaignCheckins,
  fetchCampaignDraws,
  fetchCampaigns,
  fetchCampaignVerifications,
  fetchCampaignVouchers,
  fetchCustomer,
  fetchCustomers,
  updateCampaign,
  voidVerification,
  type Campaign,
  type CampaignPayload,
  type CampaignStatus,
  type CheckInRow,
  type Customer,
  type CustomerDetail,
  type LotteryDrawRow,
  type SpendVerification,
  type VoucherRow,
} from '@/api/promotions'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

type Tab = 'campaigns' | 'customers' | 'records' | 'risk' | 'report'
const tab = ref<Tab>('campaigns')

const reportCampaignId = ref('')

// The store-QR sticker must point at the SPA's own /pc/register route —
// served wherever the frontend is served, which is same-origin as the API
// in production and localhost:5175 in dev (NOT the API port).
const appBaseUrl = `${window.location.origin}${import.meta.env.BASE_URL}`.replace(/\/$/, '')

function branchName(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

// ===== Campaigns ==========================================================

const campaigns = ref<Campaign[]>([])
const { loading: campaignsLoading, run: runCampaigns } = useDelayedLoading()

async function loadCampaigns() {
  await runCampaigns(async () => {
    campaigns.value = await fetchCampaigns()
  })
}

const campaignDialog = ref(false)
const campaignFormRef = ref<FormInstance>()
const editingCampaignId = ref<string | null>(null)
const savingCampaign = ref(false)

const blankCampaign = (): CampaignPayload => ({
  branchId: isAdmin.value ? '' : (auth.branchId ?? ''),
  name: '',
  description: '',
  status: 'draft',
  startsAt: null,
  endsAt: null,
  activeWeekdays: '1234567',
  activeDateFrom: null,
  activeDateTo: null,
  priority: 0,
  pointsPer1000yen: 10,
  pointsPerDraw: 100,
  pointsPerVoucher: 100,
  voucherYenPerUnit: 100,
  pointsExpireMonths: 12,
  directDrawThresholdYen: null,
  maxDrawsPerVerification: 1,
  maxDrawsPerCustomerPerDay: 10,
  stampTarget: 5,
  businessDayCutover: '05:00',
  checkinRewardEnabled: false,
  checkinRewardType: 'drink',
  checkinRewardConfig: {},
  checkinRewardExpiresAfterDays: 1,
})
const campaignForm = reactive<CampaignPayload>(blankCampaign())

// ISO weekday digits (1=Mon..7=Sun) <-> a checkbox array
const WEEKDAY_KEYS = ['1', '2', '3', '4', '5', '6', '7'] as const
const weekdayLabelKeys: Record<(typeof WEEKDAY_KEYS)[number], string> = {
  '1': 'promotions.wdMon', '2': 'promotions.wdTue', '3': 'promotions.wdWed',
  '4': 'promotions.wdThu', '5': 'promotions.wdFri', '6': 'promotions.wdSat', '7': 'promotions.wdSun',
}
const activeWeekdayArray = computed<string[]>({
  get: () => WEEKDAY_KEYS.filter((d) => campaignForm.activeWeekdays.includes(d)),
  set: (arr) => {
    const next = WEEKDAY_KEYS.filter((d) => arr.includes(d)).join('')
    campaignForm.activeWeekdays = next || '1234567'
  },
})
const checkinRewardLabel = computed<string>({
  get: () => String((campaignForm.checkinRewardConfig as Record<string, unknown>).label ?? ''),
  set: (v) => { campaignForm.checkinRewardConfig = { ...campaignForm.checkinRewardConfig, label: v } },
})
const rewardTypeOptions = ['drink', 'dessert', 'side_dish'] as const

const campaignRules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('promotions.validateName'), trigger: 'blur' }],
  branchId: isAdmin.value
    ? [{ required: true, message: t('promotions.validateBranch'), trigger: 'change' }]
    : [],
}))

const statusOptions: CampaignStatus[] = ['draft', 'active', 'paused', 'ended']

function openCampaignCreate() {
  editingCampaignId.value = null
  Object.assign(campaignForm, blankCampaign())
  campaignDialog.value = true
}

function openCampaignEdit(row: Campaign) {
  editingCampaignId.value = row.id
  Object.assign(campaignForm, {
    branchId: row.branchId,
    name: row.name,
    description: row.description,
    status: row.status,
    startsAt: row.startsAt,
    endsAt: row.endsAt,
    activeWeekdays: row.activeWeekdays || '1234567',
    activeDateFrom: row.activeDateFrom,
    activeDateTo: row.activeDateTo,
    priority: row.priority,
    pointsPer1000yen: row.pointsPer1000yen,
    pointsPerDraw: row.pointsPerDraw,
    pointsPerVoucher: row.pointsPerVoucher,
    voucherYenPerUnit: row.voucherYenPerUnit,
    pointsExpireMonths: row.pointsExpireMonths,
    directDrawThresholdYen: row.directDrawThresholdYen,
    maxDrawsPerVerification: row.maxDrawsPerVerification,
    maxDrawsPerCustomerPerDay: row.maxDrawsPerCustomerPerDay,
    stampTarget: row.stampTarget,
    businessDayCutover: row.businessDayCutover?.slice(0, 5) ?? '05:00',
    checkinRewardEnabled: row.checkinRewardEnabled,
    checkinRewardType: row.checkinRewardType || 'drink',
    checkinRewardConfig: row.checkinRewardConfig ?? {},
    checkinRewardExpiresAfterDays: row.checkinRewardExpiresAfterDays,
  })
  campaignDialog.value = true
}

async function saveCampaign() {
  if (!campaignFormRef.value) return
  await campaignFormRef.value.validate(async (valid) => {
    if (!valid) return
    savingCampaign.value = true
    try {
      const payload: CampaignPayload = { ...campaignForm }
      if (!isAdmin.value) delete payload.branchId
      if (editingCampaignId.value) await updateCampaign(editingCampaignId.value, payload)
      else await createCampaign(payload)
      campaignDialog.value = false
      ElMessage.success(t('common.savedSuccess'))
      await loadCampaigns()
    } catch (err) {
      ElMessage.error(errText(err))
    } finally {
      savingCampaign.value = false
    }
  })
}

async function removeCampaign(row: Campaign) {
  try {
    await ElMessageBox.confirm(t('promotions.deleteCampaignConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
  } catch {
    return
  }
  try {
    await deleteCampaign(row.id)
    ElMessage.success(t('common.deletedSuccess'))
    await loadCampaigns()
  } catch (err) {
    if (err instanceof ApiError && JSON.stringify(err.body).includes('campaign-has-history')) {
      ElMessage.error(t('promotions.campaignHasHistory'))
    } else {
      ElMessage.error(errText(err))
    }
  }
}

// ---- prize pool drawer ----
const prizesCampaign = ref<{ id: string; name: string } | null>(null)

// ---- store QR ----
const qrDialog = ref(false)
const qrCampaign = ref<Campaign | null>(null)
const qrDataUrl = ref('')

const registerUrl = computed(() =>
  qrCampaign.value?.storeToken ? `${appBaseUrl}/pc/register?t=${qrCampaign.value.storeToken}` : '',
)

async function openQr(row: Campaign) {
  qrCampaign.value = row
  qrDialog.value = true
  qrDataUrl.value = row.storeToken
    ? await QRCode.toDataURL(`${appBaseUrl}/pc/register?t=${row.storeToken}`, { width: 320, margin: 2 })
    : ''
}

function downloadQr() {
  if (!qrDataUrl.value || !qrCampaign.value) return
  const a = document.createElement('a')
  a.href = qrDataUrl.value
  a.download = `store-qr-${qrCampaign.value.branchId}-${qrCampaign.value.id}.png`
  a.click()
}

async function copyRegisterUrl() {
  try {
    await navigator.clipboard.writeText(registerUrl.value)
    ElMessage.success(t('promotions.urlCopied'))
  } catch {
    ElMessage.warning(registerUrl.value)
  }
}

// ===== Customers ==========================================================

const customers = ref<Customer[]>([])
const customerTotal = ref(0)
const customerPage = ref(1)
const customerSearch = ref('')
const customerStatus = ref('')
const { loading: customersLoading, run: runCustomers } = useDelayedLoading()

async function loadCustomers() {
  await runCustomers(async () => {
    const page = await fetchCustomers({
      search: customerSearch.value || undefined,
      status: customerStatus.value || undefined,
      page: customerPage.value,
      pageSize: 50,
    })
    customers.value = page.results
    customerTotal.value = page.count
  })
}

function applyCustomerSearch() {
  customerPage.value = 1
  loadCustomers()
}

watch(customerPage, loadCustomers)

const customerDrawer = ref(false)
const customerDetail = ref<CustomerDetail | null>(null)
const detailLoading = ref(false)

async function openCustomer(row: Customer) {
  customerDrawer.value = true
  detailLoading.value = true
  try {
    customerDetail.value = await fetchCustomer(row.id)
  } finally {
    detailLoading.value = false
  }
}

const adjustDialog = ref(false)
const adjustForm = reactive({ delta: 0, note: '' })
const savingAdjust = ref(false)

function openAdjust() {
  adjustForm.delta = 0
  adjustForm.note = ''
  adjustDialog.value = true
}

async function saveAdjust() {
  if (!customerDetail.value) return
  if (!adjustForm.delta || !adjustForm.note.trim()) {
    ElMessage.warning(t('promotions.adjustValidate'))
    return
  }
  savingAdjust.value = true
  try {
    await adjustCustomerPoints(customerDetail.value.id, Math.round(adjustForm.delta), adjustForm.note.trim())
    adjustDialog.value = false
    ElMessage.success(t('common.savedSuccess'))
    customerDetail.value = await fetchCustomer(customerDetail.value.id)
    await loadCustomers()
  } catch (err) {
    ElMessage.error(errText(err))
  } finally {
    savingAdjust.value = false
  }
}

async function removeCustomer() {
  if (!customerDetail.value) return
  try {
    await ElMessageBox.confirm(
      t('promotions.deleteCustomerConfirm', { phone: customerDetail.value.phone }),
      t('promotions.deleteCustomerTitle'),
      { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') },
    )
  } catch {
    return
  }
  try {
    await deleteCustomer(customerDetail.value.id)
    ElMessage.success(t('promotions.customerDeleted'))
    customerDrawer.value = false
    customerDetail.value = null
    await loadCustomers()
  } catch (err) {
    ElMessage.error(errText(err))
  }
}

// ===== Records ===========================================================

type RecordKind = 'verifications' | 'checkins' | 'draws' | 'vouchers'
const recordCampaignId = ref('')
const recordKind = ref<RecordKind>('verifications')
const recordDate = ref('')
const recordStatus = ref('')
const verifications = ref<SpendVerification[]>([])
const checkins = ref<CheckInRow[]>([])
const draws = ref<LotteryDrawRow[]>([])
const vouchers = ref<VoucherRow[]>([])
const recordTotal = ref(0)
const recordPage = ref(1)
const { loading: recordsLoading, run: runRecords } = useDelayedLoading()

const activeCampaignOptions = computed(() => campaigns.value)

async function loadRecords() {
  if (!recordCampaignId.value) {
    verifications.value = []
    checkins.value = []
    draws.value = []
    vouchers.value = []
    recordTotal.value = 0
    return
  }
  await runRecords(async () => {
    const cid = recordCampaignId.value
    const status = recordStatus.value || undefined
    const page = recordPage.value
    if (recordKind.value === 'verifications') {
      const p = await fetchCampaignVerifications({ campaignId: cid, status, page, pageSize: 50 })
      verifications.value = p.results
      recordTotal.value = p.count
    } else if (recordKind.value === 'checkins') {
      const p = await fetchCampaignCheckins(cid, { localDate: recordDate.value || undefined, page, pageSize: 50 })
      checkins.value = p.results
      recordTotal.value = p.count
    } else if (recordKind.value === 'draws') {
      const p = await fetchCampaignDraws(cid, { status, page, pageSize: 50 })
      draws.value = p.results
      recordTotal.value = p.count
    } else {
      const p = await fetchCampaignVouchers(cid, { status, page, pageSize: 50 })
      vouchers.value = p.results
      recordTotal.value = p.count
    }
  })
}

function applyRecordFilters() {
  recordPage.value = 1
  loadRecords()
}

watch(recordPage, loadRecords)
watch([recordCampaignId, recordKind], applyRecordFilters)
function preferredCampaignId() {
  return (campaigns.value.find((c) => c.status === 'active') ?? campaigns.value[0])?.id ?? ''
}

watch(tab, (value) => {
  customerDrawer.value = false
  if (value === 'customers') {
    loadCustomers()
  } else if (value === 'records') {
    if (!recordCampaignId.value) recordCampaignId.value = preferredCampaignId()
    else loadRecords()
  } else if (value === 'report') {
    if (!reportCampaignId.value) reportCampaignId.value = preferredCampaignId()
  }
})

async function handleVoid(row: SpendVerification) {
  try {
    const { value } = await ElMessageBox.prompt(t('promotions.voidPrompt'), t('promotions.voidTitle'), {
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      inputValidator: (v) => (v && v.trim() ? true : t('promotions.voidReasonRequired')),
    })
    await voidVerification(row.id, (value ?? '').trim())
    ElMessage.success(t('promotions.voidDone'))
    await loadRecords()
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    ElMessage.error(errText(err))
  }
}

// ===== shared ============================================================

function errText(err: unknown) {
  if (err instanceof ApiError) return err.messages()[0] || t('common.unexpectedError')
  return t('common.unexpectedError')
}

function shortDateTime(iso: string) {
  if (!iso) return '—'
  const dt = new Date(iso)
  return Number.isNaN(dt.getTime())
    ? iso
    : new Intl.DateTimeFormat('ja-JP', {
        month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo',
      }).format(dt)
}

function shortDate(iso: string) {
  if (!iso) return '—'
  const dt = new Date(iso)
  return Number.isNaN(dt.getTime())
    ? iso
    : new Intl.DateTimeFormat('ja-JP', {
        year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'Asia/Tokyo',
      }).format(dt)
}

function reasonLabel(reason: string) {
  return t(`promotions.reason.${reason}`, reason)
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  await loadCampaigns()
})
</script>

<template>
  <div class="promotions-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('promotions.pageTitle') }}</h3>
        <el-radio-group v-model="tab" size="small">
          <el-radio-button value="campaigns">{{ t('promotions.tabCampaigns') }}</el-radio-button>
          <el-radio-button value="customers">{{ t('promotions.tabCustomers') }}</el-radio-button>
          <el-radio-button value="records">{{ t('promotions.tabRecords') }}</el-radio-button>
          <el-radio-button value="risk">{{ t('promotions.tabRisk') }}</el-radio-button>
          <el-radio-button value="report">{{ t('promotions.tabReport') }}</el-radio-button>
        </el-radio-group>
      </div>

      <!-- ============ Campaigns ============ -->
      <template v-if="tab === 'campaigns'">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="openCampaignCreate">{{ t('promotions.newCampaign') }}</el-button>
          <el-button :icon="Refresh" @click="loadCampaigns" />
        </div>
        <el-table :data="campaigns" v-loading="campaignsLoading" :empty-text="t('promotions.noCampaigns')">
          <el-table-column :label="t('promotions.branch')" min-width="120">
            <template #default="{ row }">{{ branchName(row.branchId) }}</template>
          </el-table-column>
          <el-table-column prop="name" :label="t('promotions.name')" min-width="160" />
          <el-table-column :label="t('common.status')" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'active' ? 'success' : row.status === 'paused' ? 'warning' : 'info'">
                {{ t(`promotions.status.${row.status}`) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.earnRate')" width="130">
            <template #default="{ row }">¥1,000 → {{ row.pointsPer1000yen }}pt</template>
          </el-table-column>
          <el-table-column :label="t('promotions.stampTarget')" width="90">
            <template #default="{ row }">{{ row.stampTarget ?? '—' }}</template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="270" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text @click="openCampaignEdit(row)">{{ t('common.edit') }}</el-button>
              <el-button size="small" text @click="prizesCampaign = { id: row.id, name: row.name }">
                {{ t('promotions.prizes') }}
              </el-button>
              <el-button v-if="row.status === 'active'" size="small" text @click="openQr(row)">
                {{ t('promotions.storeQr') }}
              </el-button>
              <el-button size="small" text type="danger" @click="removeCampaign(row)">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- ============ Customers ============ -->
      <template v-else-if="tab === 'customers'">
        <div class="toolbar">
          <el-input
            v-model="customerSearch"
            :placeholder="t('promotions.searchCustomer')"
            clearable
            class="search-input"
            @keydown.enter="applyCustomerSearch"
            @clear="applyCustomerSearch"
          />
          <el-select v-model="customerStatus" clearable :placeholder="t('common.status')" class="status-select" @change="applyCustomerSearch">
            <el-option value="active" :label="t('promotions.custActive')" />
            <el-option value="blocked" :label="t('promotions.custBlocked')" />
          </el-select>
          <el-button :icon="Refresh" @click="loadCustomers" />
        </div>
        <el-table :data="customers" v-loading="customersLoading" :empty-text="t('promotions.noCustomers')" @row-click="openCustomer">
          <el-table-column prop="name" :label="t('promotions.custName')" min-width="120">
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="phone" :label="t('promotions.phone')" min-width="130" />
          <el-table-column :label="t('promotions.points')" width="90">
            <template #default="{ row }">{{ row.pointsBalance.toLocaleString('ja-JP') }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.stamps')" width="80">
            <template #default="{ row }">{{ row.stampCount }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.lastSeen')" width="140">
            <template #default="{ row }">{{ shortDateTime(row.lastSeenAt) }}</template>
          </el-table-column>
        </el-table>
        <div class="pagination-row">
          <el-pagination
            v-model:current-page="customerPage"
            :page-size="50"
            :total="customerTotal"
            layout="prev, pager, next, total"
            background
          />
        </div>
      </template>

      <!-- ============ Records ============ -->
      <template v-else-if="tab === 'records'">
        <div class="toolbar">
          <el-select v-model="recordCampaignId" :placeholder="t('promotions.selectCampaign')" class="campaign-select">
            <el-option
              v-for="c in activeCampaignOptions"
              :key="c.id"
              :value="c.id"
              :label="`${branchName(c.branchId)} · ${c.name}`"
            />
          </el-select>
          <el-radio-group v-model="recordKind" size="small">
            <el-radio-button value="verifications">{{ t('promotions.recVerifications') }}</el-radio-button>
            <el-radio-button value="checkins">{{ t('promotions.recCheckins') }}</el-radio-button>
            <el-radio-button value="draws">{{ t('promotions.recDraws') }}</el-radio-button>
            <el-radio-button value="vouchers">{{ t('promotions.recVouchers') }}</el-radio-button>
          </el-radio-group>
          <el-date-picker
            v-if="recordKind === 'checkins'"
            v-model="recordDate"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="t('promotions.filterDate')"
            @change="applyRecordFilters"
          />
          <el-select
            v-if="recordKind === 'verifications'"
            v-model="recordStatus"
            clearable
            :placeholder="t('common.status')"
            class="status-select"
            @change="applyRecordFilters"
          >
            <el-option value="accepted" :label="t('promotions.status.active')" />
            <el-option value="voided" :label="t('promotions.voided')" />
          </el-select>
          <el-select
            v-if="recordKind === 'draws'"
            v-model="recordStatus"
            clearable
            :placeholder="t('common.status')"
            class="status-select"
            @change="applyRecordFilters"
          >
            <el-option value="won" :label="t('promotions.drawWon')" />
            <el-option value="refund" :label="t('promotions.drawRefund')" />
          </el-select>
          <el-select
            v-if="recordKind === 'vouchers'"
            v-model="recordStatus"
            clearable
            :placeholder="t('common.status')"
            class="status-select"
            @change="applyRecordFilters"
          >
            <el-option value="active" :label="t('promotions.voucherActive')" />
            <el-option value="redeemed" :label="t('promotions.voucherRedeemed')" />
            <el-option value="expired" :label="t('promotions.voucherExpired')" />
            <el-option value="void" :label="t('promotions.voided')" />
          </el-select>
        </div>

        <el-table
          v-if="recordKind === 'verifications'"
          :data="verifications"
          v-loading="recordsLoading"
          :empty-text="t('promotions.noRecords')"
        >
          <el-table-column :label="t('promotions.time')" width="130">
            <template #default="{ row }">{{ shortDateTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.custName')" min-width="120">
            <template #default="{ row }">
              {{ row.customerDeleted ? t('promotions.customerErased') : (row.customerName || row.customerPhone || '—') }}
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.amount')" width="110">
            <template #default="{ row }">¥{{ row.amountYen.toLocaleString('ja-JP') }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.pointsGranted')" width="90">
            <template #default="{ row }">+{{ row.pointsGranted }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.operator')" min-width="100">
            <template #default="{ row }">{{ row.verifiedByName || '—' }}</template>
          </el-table-column>
          <el-table-column :label="t('common.status')" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'voided' ? 'info' : 'success'">
                {{ row.status === 'voided' ? t('promotions.voided') : t('promotions.status.active') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="isAdmin" :label="t('common.actions')" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status !== 'voided'"
                size="small"
                text
                type="danger"
                @click="handleVoid(row)"
              >
                {{ t('promotions.void') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-table
          v-else-if="recordKind === 'checkins'"
          :data="checkins"
          v-loading="recordsLoading"
          :empty-text="t('promotions.noRecords')"
        >
          <el-table-column prop="localDate" :label="t('promotions.businessDay')" width="130" />
          <el-table-column :label="t('promotions.time')" width="130">
            <template #default="{ row }">{{ shortDateTime(row.checkedInAt) }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.custName')" min-width="120">
            <template #default="{ row }">{{ row.customerName || row.customerPhone || '—' }}</template>
          </el-table-column>
        </el-table>

        <el-table
          v-else-if="recordKind === 'draws'"
          :data="draws"
          v-loading="recordsLoading"
          :empty-text="t('promotions.noRecords')"
        >
          <el-table-column :label="t('promotions.time')" width="130">
            <template #default="{ row }">{{ shortDateTime(row.drawnAt) }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.custName')" min-width="110">
            <template #default="{ row }">
              {{ row.customerDeleted ? t('promotions.customerErased') : (row.customerName || row.customerPhone || '—') }}
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.drawSource')" width="90">
            <template #default="{ row }">{{ t(`promotions.drawSource_${row.source}`) }}</template>
          </el-table-column>
          <el-table-column :label="t('promotions.prizeResult')" min-width="140">
            <template #default="{ row }">
              <span v-if="row.status === 'won'">{{ row.prizeName }}</span>
              <span v-else class="muted">{{ t('promotions.drawRefund') }} +{{ row.pointsRefunded }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.pointsSpent')" width="90">
            <template #default="{ row }">{{ row.pointsSpent || '—' }}</template>
          </el-table-column>
        </el-table>

        <el-table
          v-else
          :data="vouchers"
          v-loading="recordsLoading"
          :empty-text="t('promotions.noRecords')"
        >
          <el-table-column prop="redemptionCode" :label="t('promotions.voucherCode')" width="110" />
          <el-table-column prop="label" :label="t('promotions.label')" min-width="150" />
          <el-table-column :label="t('promotions.custName')" min-width="110">
            <template #default="{ row }">
              {{ row.customerDeleted ? t('promotions.customerErased') : (row.customerName || row.customerPhone || '—') }}
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.voucherSource')" width="100">
            <template #default="{ row }">{{ t(`promotions.voucherSource_${row.source}`) }}</template>
          </el-table-column>
          <el-table-column :label="t('common.status')" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'redeemed' ? 'success' : row.status === 'active' ? 'primary' : 'info'">
                {{ t(`promotions.voucher${row.status.charAt(0).toUpperCase()}${row.status.slice(1)}`) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('promotions.expiresAt')" width="120">
            <template #default="{ row }">{{ shortDate(row.expiresAt) }}</template>
          </el-table-column>
        </el-table>

        <div class="pagination-row">
          <el-pagination
            v-model:current-page="recordPage"
            :page-size="50"
            :total="recordTotal"
            layout="prev, pager, next, total"
            background
          />
        </div>
      </template>

      <!-- ============ Risk ============ -->
      <RiskEventsPanel v-else-if="tab === 'risk'" />

      <!-- ============ Report ============ -->
      <template v-else-if="tab === 'report'">
        <div class="toolbar">
          <el-select v-model="reportCampaignId" :placeholder="t('promotions.selectCampaign')" class="campaign-select">
            <el-option
              v-for="c in activeCampaignOptions"
              :key="c.id"
              :value="c.id"
              :label="`${branchName(c.branchId)} · ${c.name}`"
            />
          </el-select>
        </div>
        <CampaignReportPanel v-if="reportCampaignId" :campaign-id="reportCampaignId" />
      </template>
    </div>

    <!-- ============ Campaign dialog ============ -->
    <el-dialog
      v-model="campaignDialog"
      :title="editingCampaignId ? t('promotions.editCampaign') : t('promotions.newCampaign')"
      width="560px"
    >
      <el-form ref="campaignFormRef" :model="campaignForm" :rules="campaignRules" label-position="top">
        <el-form-item v-if="isAdmin" :label="t('promotions.branch')" prop="branchId">
          <el-select v-model="campaignForm.branchId" :placeholder="t('promotions.validateBranch')" style="width: 100%">
            <el-option
              v-for="b in branchStore.list"
              :key="b.id"
              :value="b.id"
              :label="branchDisplayName(b, locale)"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('promotions.name')" prop="name">
          <el-input v-model="campaignForm.name" />
        </el-form-item>
        <el-form-item :label="t('common.note')">
          <el-input v-model="campaignForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('common.status')">
            <el-select v-model="campaignForm.status" style="width: 100%">
              <el-option v-for="s in statusOptions" :key="s" :value="s" :label="t(`promotions.status.${s}`)" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('promotions.businessDayCutover')">
            <el-time-picker v-model="campaignForm.businessDayCutover" value-format="HH:mm" format="HH:mm" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('promotions.startsAt')">
            <el-date-picker
              v-model="campaignForm.startsAt"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              :placeholder="t('promotions.timeOpenEnded')"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item :label="t('promotions.endsAt')">
            <el-date-picker
              v-model="campaignForm.endsAt"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              :placeholder="t('promotions.timeOpenEnded')"
              style="width: 100%"
            />
          </el-form-item>

          <el-form-item :label="t('promotions.activeWeekdays')" class="span-2">
            <el-checkbox-group v-model="activeWeekdayArray">
              <el-checkbox v-for="d in WEEKDAY_KEYS" :key="d" :value="d">{{ t(weekdayLabelKeys[d]) }}</el-checkbox>
            </el-checkbox-group>
            <span class="field-hint">{{ t('promotions.activeWeekdaysHint') }}</span>
          </el-form-item>
          <el-form-item :label="t('promotions.activeDateFrom')">
            <el-date-picker
              v-model="campaignForm.activeDateFrom"
              type="date"
              value-format="YYYY-MM-DD"
              :placeholder="t('promotions.activeDateAny')"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item :label="t('promotions.activeDateTo')">
            <el-date-picker
              v-model="campaignForm.activeDateTo"
              type="date"
              value-format="YYYY-MM-DD"
              :placeholder="t('promotions.activeDateAny')"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item :label="t('promotions.priority')">
            <el-input v-model.number="campaignForm.priority" type="number" min="0" />
            <span class="field-hint">{{ t('promotions.priorityHint') }}</span>
          </el-form-item>

          <el-form-item :label="t('promotions.checkinReward')" class="span-2">
            <el-switch v-model="campaignForm.checkinRewardEnabled" />
            <span class="field-hint">{{ t('promotions.checkinRewardHint') }}</span>
          </el-form-item>
          <template v-if="campaignForm.checkinRewardEnabled">
            <el-form-item :label="t('promotions.checkinRewardType')">
              <el-select v-model="campaignForm.checkinRewardType" style="width: 100%">
                <el-option
                  v-for="rt in rewardTypeOptions"
                  :key="rt"
                  :value="rt"
                  :label="t(`promotions.rewardType_${rt}`)"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('promotions.checkinRewardExpiresDays')">
              <el-input v-model.number="campaignForm.checkinRewardExpiresAfterDays" type="number" min="1" />
            </el-form-item>
            <el-form-item :label="t('promotions.checkinRewardLabel')" class="span-2">
              <el-input v-model="checkinRewardLabel" :placeholder="t('promotions.checkinRewardLabelPlaceholder')" />
            </el-form-item>
          </template>

          <el-form-item :label="t('promotions.earnRateLabel')">
            <el-input v-model.number="campaignForm.pointsPer1000yen" type="number" />
          </el-form-item>
          <el-form-item :label="t('promotions.stampTargetLabel')">
            <el-input
              v-model.number="campaignForm.stampTarget"
              type="number"
              :placeholder="t('promotions.stampDisabled')"
            />
          </el-form-item>
          <el-form-item :label="t('promotions.pointsExpireMonths')">
            <el-input v-model.number="campaignForm.pointsExpireMonths" type="number" />
          </el-form-item>
          <el-form-item :label="t('promotions.maxDrawsPerDay')">
            <el-input v-model.number="campaignForm.maxDrawsPerCustomerPerDay" type="number" />
          </el-form-item>
          <el-form-item :label="t('promotions.maxDrawsPerVerification')">
            <el-input v-model.number="campaignForm.maxDrawsPerVerification" type="number" />
          </el-form-item>
        </div>
        <p class="phase-note">{{ t('promotions.phase2Note') }}</p>
      </el-form>
      <template #footer>
        <el-button @click="campaignDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="savingCampaign" @click="saveCampaign">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- ============ Store QR dialog ============ -->
    <el-dialog v-model="qrDialog" :title="t('promotions.storeQrTitle')" width="380px">
      <div class="qr-dialog">
        <img v-if="qrDataUrl" :src="qrDataUrl" :alt="t('promotions.storeQr')" class="qr-img" />
        <p class="qr-url">{{ registerUrl }}</p>
        <div class="qr-actions">
          <el-button @click="copyRegisterUrl">{{ t('promotions.copyUrl') }}</el-button>
          <el-button type="primary" @click="downloadQr">{{ t('promotions.downloadPng') }}</el-button>
        </div>
        <p class="qr-note">{{ t('promotions.storeQrNote') }}</p>
      </div>
    </el-dialog>

    <!-- ============ Customer drawer ============ -->
    <el-drawer v-model="customerDrawer" :title="t('promotions.customerDetail')" size="440px">
      <div v-if="detailLoading" class="drawer-loading">{{ t('guest.loading') }}</div>
      <div v-else-if="customerDetail" class="customer-detail">
        <div class="detail-head">
          <span class="detail-name">{{ customerDetail.name || '—' }}</span>
          <span class="detail-phone">{{ customerDetail.phone }}</span>
          <span v-if="customerDetail.birthdayMd" class="detail-meta">{{ t('promotions.birthday') }}: {{ customerDetail.birthdayMd }}</span>
        </div>
        <div class="detail-stats">
          <div><strong>{{ customerDetail.pointsBalance.toLocaleString('ja-JP') }}</strong><span>{{ t('promotions.points') }}</span></div>
          <div><strong>{{ customerDetail.stampCount }}</strong><span>{{ t('promotions.stamps') }}</span></div>
        </div>

        <div v-if="isAdmin" class="detail-actions">
          <el-button size="small" @click="openAdjust">{{ t('promotions.adjustPoints') }}</el-button>
          <el-button size="small" type="danger" :icon="Delete" @click="removeCustomer">
            {{ t('promotions.deleteCustomer') }}
          </el-button>
        </div>

        <h4 class="detail-section">{{ t('promotions.ledger') }}</h4>
        <ul v-if="customerDetail.recentLedger.length" class="ledger">
          <li v-for="row in customerDetail.recentLedger" :key="row.id">
            <div>
              <span class="ledger-reason">{{ reasonLabel(row.reason) }}</span>
              <span class="ledger-date">{{ shortDateTime(row.createdAt) }}</span>
              <span v-if="row.note" class="ledger-note">{{ row.note }}</span>
            </div>
            <span class="ledger-delta" :class="{ minus: row.delta < 0 }">{{ row.delta > 0 ? '+' : '' }}{{ row.delta }}</span>
          </li>
        </ul>
        <p v-else class="empty">{{ t('promotions.ledgerEmpty') }}</p>
      </div>
    </el-drawer>

    <!-- ============ Adjust points dialog ============ -->
    <el-dialog v-model="adjustDialog" :title="t('promotions.adjustPoints')" width="420px">
      <el-form label-position="top">
        <el-form-item :label="t('promotions.adjustDelta')">
          <el-input v-model.number="adjustForm.delta" type="number" :placeholder="t('promotions.adjustDeltaHint')" />
        </el-form-item>
        <el-form-item :label="t('promotions.adjustNote')">
          <el-input v-model="adjustForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="savingAdjust" @click="saveAdjust">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <CampaignPrizesDrawer
      :campaign-id="prizesCampaign?.id ?? null"
      :campaign-name="prizesCampaign?.name ?? ''"
      @close="prizesCampaign = null"
    />
  </div>
</template>

<style scoped>
.promotions-view {
  max-width: 1100px;
}

.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}

.page-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.search-input {
  width: 220px;
}

.status-select {
  width: 130px;
}

.campaign-select {
  width: 260px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.form-grid .span-2 {
  grid-column: 1 / -1;
}

.field-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  line-height: 1.4;
  margin-top: 2px;
}

.phase-note {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 4px 0 0;
}

.qr-dialog {
  text-align: center;
}

.qr-img {
  width: 260px;
  height: 260px;
}

.qr-url {
  font-size: 11px;
  color: var(--text-tertiary);
  word-break: break-all;
  margin: 10px 0;
}

.qr-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}

.qr-note {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin: 14px 0 0;
}

.drawer-loading {
  padding: 30px;
  text-align: center;
  color: var(--text-tertiary);
}

.detail-head {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.detail-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-phone {
  font-size: 13px;
  color: var(--text-secondary);
}

.detail-meta {
  font-size: 12px;
  color: var(--text-tertiary);
}

.detail-stats {
  display: flex;
  gap: 28px;
  margin: 16px 0;
}

.detail-stats strong {
  display: block;
  font-size: 22px;
  color: var(--text-primary);
}

.detail-stats span {
  font-size: 11px;
  color: var(--text-secondary);
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.detail-section {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 10px 0 8px;
}

.ledger {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ledger li {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}

.ledger li div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ledger-reason {
  font-size: 13px;
  color: var(--text-primary);
}

.ledger-date {
  font-size: 11px;
  color: var(--text-tertiary);
}

.ledger-note {
  font-size: 11px;
  color: var(--text-secondary);
}

.ledger-delta {
  font-size: 15px;
  font-weight: 600;
  color: var(--success);
}

.ledger-delta.minus {
  color: var(--danger);
}

.empty {
  font-size: 12.5px;
  color: var(--text-tertiary);
  text-align: center;
  padding: 12px 0;
}

@media (max-width: 640px) {
  .search-input,
  .campaign-select {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
