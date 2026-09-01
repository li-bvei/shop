<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'
import {
  createMilestone,
  createPrize,
  deleteMilestone,
  deletePrize,
  fetchMilestones,
  fetchPrizes,
  updateMilestone,
  updatePrize,
  type Milestone,
  type MilestonePayload,
  type Prize,
  type PrizePayload,
  type RewardType,
} from '@/api/promotions'

const props = defineProps<{ campaignId: string | null; campaignName: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
// Prize / milestone economics is a chain-level decision — branch accounts
// see the pool read-only (mirrors the server-side admin-only write rule).
const canEdit = computed(() => useAuthStore().role === 'admin')

const open = computed({
  get: () => props.campaignId !== null,
  set: (v) => {
    if (!v) emit('close')
  },
})

const rewardTypes: RewardType[] = [
  'cash_voucher', 'drink', 'dessert', 'side_dish', 'chef_special', 'points_refund',
]

const prizes = ref<Prize[]>([])
const milestones = ref<Milestone[]>([])
const loading = ref(false)

const totalWeight = computed(() => prizes.value.filter((p) => p.active).reduce((s, p) => s + p.weight, 0))

async function load() {
  if (!props.campaignId) return
  loading.value = true
  try {
    ;[prizes.value, milestones.value] = await Promise.all([
      fetchPrizes(props.campaignId),
      fetchMilestones(props.campaignId),
    ])
  } finally {
    loading.value = false
  }
}

watch(() => props.campaignId, load, { immediate: true })

// ---- Prize dialog -------------------------------------------------------

const prizeDialog = ref(false)
const editingPrizeId = ref<string | null>(null)
const savingPrize = ref(false)

const blankPrize = () => ({
  name: '',
  weight: 10,
  rewardType: 'drink' as RewardType,
  faceYen: 500,
  minSpendYen: 0,
  menuValueCapYen: 1200,
  refundPoints: 30,
  label: '',
  totalStock: null as number | null,
  dailyStock: null as number | null,
  voucherExpiresAfterDays: 30,
  requiresManualApproval: false,
  active: true,
})
const prizeForm = reactive(blankPrize())

const prizeIsVoucher = computed(() =>
  ['cash_voucher', 'drink', 'dessert', 'side_dish', 'chef_special'].includes(prizeForm.rewardType),
)

function openPrizeCreate() {
  editingPrizeId.value = null
  Object.assign(prizeForm, blankPrize())
  prizeDialog.value = true
}

function openPrizeEdit(p: Prize) {
  editingPrizeId.value = p.id
  const cfg = p.rewardConfig as Record<string, number | string>
  Object.assign(prizeForm, {
    ...blankPrize(),
    name: p.name,
    weight: p.weight,
    rewardType: p.rewardType,
    faceYen: Number(cfg.face_yen ?? 500),
    minSpendYen: Number(cfg.min_spend_yen ?? p.voucherMinSpendYen ?? 0),
    menuValueCapYen: Number(cfg.menu_value_cap_yen ?? 1200),
    refundPoints: Number(cfg.points ?? 30),
    label: String(cfg.label ?? ''),
    totalStock: p.totalStock,
    dailyStock: p.dailyStock,
    voucherExpiresAfterDays: p.voucherExpiresAfterDays,
    requiresManualApproval: p.requiresManualApproval,
    active: p.active,
  })
  prizeDialog.value = true
}

function buildRewardConfig(): Record<string, unknown> {
  switch (prizeForm.rewardType) {
    case 'cash_voucher':
      return { face_yen: prizeForm.faceYen, min_spend_yen: prizeForm.minSpendYen }
    case 'chef_special':
      return { menu_value_cap_yen: prizeForm.menuValueCapYen, label: prizeForm.label || undefined }
    case 'points_refund':
      return { points: prizeForm.refundPoints }
    default:
      return prizeForm.label ? { label: prizeForm.label } : {}
  }
}

async function savePrize() {
  if (!props.campaignId || !prizeForm.name.trim()) {
    ElMessage.warning(t('promotions.validateName'))
    return
  }
  savingPrize.value = true
  try {
    const payload: PrizePayload = {
      campaignId: props.campaignId,
      name: prizeForm.name.trim(),
      weight: prizeForm.weight,
      rewardType: prizeForm.rewardType,
      rewardConfig: buildRewardConfig(),
      totalStock: prizeForm.totalStock,
      dailyStock: prizeForm.dailyStock,
      voucherExpiresAfterDays: prizeForm.voucherExpiresAfterDays,
      voucherMinSpendYen: prizeForm.rewardType === 'cash_voucher' ? prizeForm.minSpendYen : 0,
      requiresManualApproval: prizeForm.requiresManualApproval,
      active: prizeForm.active,
    }
    if (editingPrizeId.value) await updatePrize(editingPrizeId.value, payload)
    else await createPrize(payload)
    prizeDialog.value = false
    ElMessage.success(t('common.savedSuccess'))
    await load()
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.messages()[0] || t('common.unexpectedError') : t('common.unexpectedError'))
  } finally {
    savingPrize.value = false
  }
}

async function removePrize(p: Prize) {
  try {
    await ElMessageBox.confirm(t('promotions.deletePrizeConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'),
    })
  } catch {
    return
  }
  await deletePrize(p.id)
  await load()
}

// ---- Milestone dialog --------------------------------------------------

const msDialog = ref(false)
const editingMsId = ref<string | null>(null)
const savingMs = ref(false)
const msForm = reactive({
  pointsThreshold: 300,
  rewardType: 'drink' as RewardType,
  faceYen: 500,
  label: '',
  displayLabel: '',
  voucherExpiresAfterDays: 45,
  active: true,
})
const msRewardTypes: RewardType[] = ['cash_voucher', 'drink', 'dessert', 'side_dish', 'chef_special']

function openMsCreate() {
  editingMsId.value = null
  Object.assign(msForm, {
    pointsThreshold: 300, rewardType: 'drink', faceYen: 500, label: '', displayLabel: '',
    voucherExpiresAfterDays: 45, active: true,
  })
  msDialog.value = true
}

function openMsEdit(m: Milestone) {
  editingMsId.value = m.id
  const cfg = m.rewardConfig as Record<string, number | string>
  Object.assign(msForm, {
    pointsThreshold: m.pointsThreshold,
    rewardType: m.rewardType,
    faceYen: Number(cfg.face_yen ?? 500),
    label: String(cfg.label ?? ''),
    displayLabel: m.displayLabel,
    voucherExpiresAfterDays: m.voucherExpiresAfterDays,
    active: m.active,
  })
  msDialog.value = true
}

async function saveMs() {
  if (!props.campaignId) return
  savingMs.value = true
  try {
    const config =
      msForm.rewardType === 'cash_voucher'
        ? { face_yen: msForm.faceYen }
        : msForm.label
          ? { label: msForm.label }
          : {}
    const payload: MilestonePayload = {
      campaignId: props.campaignId,
      pointsThreshold: msForm.pointsThreshold,
      rewardType: msForm.rewardType,
      rewardConfig: config,
      voucherExpiresAfterDays: msForm.voucherExpiresAfterDays,
      displayLabel: msForm.displayLabel,
      active: msForm.active,
    }
    if (editingMsId.value) await updateMilestone(editingMsId.value, payload)
    else await createMilestone(payload)
    msDialog.value = false
    ElMessage.success(t('common.savedSuccess'))
    await load()
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.messages()[0] || t('common.unexpectedError') : t('common.unexpectedError'))
  } finally {
    savingMs.value = false
  }
}

async function removeMs(m: Milestone) {
  try {
    await ElMessageBox.confirm(t('promotions.deleteMilestoneConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'),
    })
  } catch {
    return
  }
  await deleteMilestone(m.id)
  await load()
}

function pct(p: Prize) {
  return `${(p.probability * 100).toFixed(1)}%`
}
</script>

<template>
  <el-drawer v-model="open" :title="t('promotions.prizePoolFor', { name: campaignName })" size="640px">
    <div v-loading="loading" class="drawer-body">
      <p v-if="!canEdit" class="readonly-note">{{ t('promotions.prizeReadonly') }}</p>
      <div class="section-head">
        <h4>{{ t('promotions.prizes') }} <span class="weight-sum">{{ t('promotions.totalWeight', { n: totalWeight }) }}</span></h4>
        <el-button v-if="canEdit" size="small" type="primary" :icon="Plus" @click="openPrizeCreate">{{ t('promotions.addPrize') }}</el-button>
      </div>
      <el-table :data="prizes" size="small" :empty-text="t('promotions.noPrizes')">
        <el-table-column prop="name" :label="t('promotions.name')" min-width="130" />
        <el-table-column :label="t('promotions.prizeType')" width="110">
          <template #default="{ row }">{{ t(`promotions.rewardType.${row.rewardType}`) }}</template>
        </el-table-column>
        <el-table-column :label="t('promotions.weight')" width="80">
          <template #default="{ row }">{{ row.weight }}</template>
        </el-table-column>
        <el-table-column :label="t('promotions.probability')" width="80">
          <template #default="{ row }">{{ pct(row) }}</template>
        </el-table-column>
        <el-table-column :label="t('promotions.stock')" width="90">
          <template #default="{ row }">
            <span>{{ row.remainingStock ?? '∞' }}<template v-if="row.dailyStock"> · {{ row.dailyStock }}/d</template></span>
          </template>
        </el-table-column>
        <el-table-column v-if="canEdit" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openPrizeEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button size="small" text type="danger" @click="removePrize(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="section-head">
        <h4>{{ t('promotions.milestones') }}</h4>
        <el-button v-if="canEdit" size="small" type="primary" :icon="Plus" @click="openMsCreate">{{ t('promotions.addMilestone') }}</el-button>
      </div>
      <el-table :data="milestones" size="small" :empty-text="t('promotions.noMilestones')">
        <el-table-column :label="t('promotions.threshold')" width="90">
          <template #default="{ row }">{{ row.pointsThreshold }}</template>
        </el-table-column>
        <el-table-column :label="t('promotions.prizeType')" width="110">
          <template #default="{ row }">{{ t(`promotions.rewardType.${row.rewardType}`) }}</template>
        </el-table-column>
        <el-table-column prop="displayLabel" :label="t('promotions.label')" min-width="140" />
        <el-table-column v-if="canEdit" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openMsEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button size="small" text type="danger" @click="removeMs(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Prize dialog -->
    <el-dialog
      v-model="prizeDialog"
      :title="editingPrizeId ? t('promotions.editPrize') : t('promotions.addPrize')"
      width="480px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item :label="t('promotions.name')">
          <el-input v-model="prizeForm.name" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('promotions.prizeType')">
            <el-select v-model="prizeForm.rewardType" style="width: 100%">
              <el-option v-for="rt in rewardTypes" :key="rt" :value="rt" :label="t(`promotions.rewardType.${rt}`)" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('promotions.weight')">
            <el-input v-model.number="prizeForm.weight" type="number" />
          </el-form-item>
        </div>

        <template v-if="prizeForm.rewardType === 'cash_voucher'">
          <div class="form-grid">
            <el-form-item :label="t('promotions.faceYen')">
              <el-input v-model.number="prizeForm.faceYen" type="number" />
            </el-form-item>
            <el-form-item :label="t('promotions.minSpendYen')">
              <el-input v-model.number="prizeForm.minSpendYen" type="number" />
            </el-form-item>
          </div>
        </template>
        <el-form-item v-else-if="prizeForm.rewardType === 'chef_special'" :label="t('promotions.menuValueCapYen')">
          <el-input v-model.number="prizeForm.menuValueCapYen" type="number" />
        </el-form-item>
        <el-form-item v-else-if="prizeForm.rewardType === 'points_refund'" :label="t('promotions.refundPoints')">
          <el-input v-model.number="prizeForm.refundPoints" type="number" />
        </el-form-item>
        <el-form-item v-else :label="t('promotions.label')">
          <el-input v-model="prizeForm.label" :placeholder="t('promotions.labelPlaceholder')" />
        </el-form-item>

        <div class="form-grid">
          <el-form-item :label="t('promotions.totalStock')">
            <el-input v-model.number="prizeForm.totalStock" type="number" :placeholder="t('promotions.unlimited')" />
          </el-form-item>
          <el-form-item :label="t('promotions.dailyStock')">
            <el-input v-model.number="prizeForm.dailyStock" type="number" :placeholder="t('promotions.unlimited')" />
          </el-form-item>
        </div>
        <el-form-item v-if="prizeIsVoucher" :label="t('promotions.voucherExpiresAfterDays')">
          <el-input v-model.number="prizeForm.voucherExpiresAfterDays" type="number" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="prizeForm.requiresManualApproval">{{ t('promotions.requiresApproval') }}</el-checkbox>
          <el-checkbox v-model="prizeForm.active">{{ t('promotions.prizeActive') }}</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="prizeDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="savingPrize" @click="savePrize">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Milestone dialog -->
    <el-dialog
      v-model="msDialog"
      :title="editingMsId ? t('promotions.editMilestone') : t('promotions.addMilestone')"
      width="440px"
      append-to-body
    >
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item :label="t('promotions.threshold')">
            <el-input v-model.number="msForm.pointsThreshold" type="number" />
          </el-form-item>
          <el-form-item :label="t('promotions.prizeType')">
            <el-select v-model="msForm.rewardType" style="width: 100%">
              <el-option v-for="rt in msRewardTypes" :key="rt" :value="rt" :label="t(`promotions.rewardType.${rt}`)" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item v-if="msForm.rewardType === 'cash_voucher'" :label="t('promotions.faceYen')">
          <el-input v-model.number="msForm.faceYen" type="number" />
        </el-form-item>
        <el-form-item v-else :label="t('promotions.label')">
          <el-input v-model="msForm.label" :placeholder="t('promotions.labelPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('promotions.displayLabel')">
          <el-input v-model="msForm.displayLabel" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('promotions.voucherExpiresAfterDays')">
            <el-input v-model.number="msForm.voucherExpiresAfterDays" type="number" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="msForm.active">{{ t('promotions.prizeActive') }}</el-checkbox>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="msDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="savingMs" @click="saveMs">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<style scoped>
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 16px 0 6px;
}

.section-head h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.readonly-note {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0 0 8px;
}

.weight-sum {
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 400;
  margin-left: 6px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}
</style>
