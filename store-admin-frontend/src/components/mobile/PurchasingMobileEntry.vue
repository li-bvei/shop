<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowUp, Filter } from '@element-plus/icons-vue'
import { fetchSuppliers, type Supplier } from '@/api/suppliers'
import {
  createPurchase, deletePurchase, fetchPriceHistory, fetchPurchaseMonthTotal, fetchPurchases, updatePurchase,
  type PriceHistoryEntry, type PurchaseRecord,
} from '@/api/purchasing'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName, currentMonthJst, formatCurrency, todayJst } from '@/utils/format'
import { buildPurchasePayload, validatePurchaseRow, type PurchaseEntryRow } from '@/utils/purchaseEntry'
import MobileSheet from '@/components/mobile/MobileSheet.vue'
import PurchaseEntryFields from '@/components/mobile/PurchaseEntryFields.vue'

/**
 * Phone version of 仕入れ: one item at a time in a vertical form ("save and
 * continue" keeps the date and supplier of the last item), history as tappable
 * cards, editing in a bottom drawer, filters in a 絞り込み drawer. The desktop
 * keyboard-driven single-row entry in PurchasingView is untouched — this only
 * shows below the phone breakpoint, and reuses the same API calls and the same
 * validation/payload rules (utils/purchaseEntry.ts).
 */
const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const PAGE_SIZE = 20
const suppliers = ref<Supplier[]>([])
const records = ref<PurchaseRecord[]>([])
const totalCount = ref(0)
const monthTotal = ref(0)
const page = ref(1)
const loading = ref(false)

const filters = reactive({
  month: currentMonthJst() as string,
  branchId: isAdmin.value ? '' : (auth.branchId ?? ''),
  supplierId: '',
  itemName: '',
  priceChange: '' as '' | 'up' | 'down',
  ordering: '-date',
})
const activeFilterCount = computed(() => {
  let n = 0
  if (filters.month !== currentMonthJst()) n++
  if (isAdmin.value && filters.branchId) n++
  if (filters.supplierId) n++
  if (filters.itemName.trim()) n++
  if (filters.priceChange) n++
  if (filters.ordering !== '-date') n++
  return n
})

function query(pageNo: number) {
  return {
    branchId: filters.branchId || undefined, supplierId: filters.supplierId || undefined, month: filters.month || undefined,
    itemName: filters.itemName.trim() || undefined, priceChange: filters.priceChange || undefined,
    ordering: filters.ordering, page: pageNo, pageSize: PAGE_SIZE,
  }
}

// A slow earlier response must not overwrite a newer filter's list.
let loadSeq = 0
async function load(reset = true) {
  const seq = ++loadSeq
  loading.value = true
  try {
    if (reset) page.value = 1
    const [result, total] = await Promise.all([
      fetchPurchases(query(page.value)),
      reset
        ? fetchPurchaseMonthTotal({
          branchId: filters.branchId || undefined, supplierId: filters.supplierId || undefined,
          month: filters.month || undefined, itemName: filters.itemName.trim() || undefined,
        })
        : Promise.resolve(monthTotal.value),
    ])
    if (seq !== loadSeq) return
    records.value = reset ? result.results : [...records.value, ...result.results]
    totalCount.value = result.count
    monthTotal.value = total
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}
async function loadMore() {
  page.value += 1
  try {
    await load(false)
  } catch (err) {
    page.value -= 1
    throw err
  }
}
watch(() => filters.month, (month) => {
  if (!month) filters.priceChange = ''
})
const hasMore = computed(() => records.value.length < totalCount.value)

onMounted(async () => {
  await branchStore.ensureLoaded()
  suppliers.value = await fetchSuppliers()
  await load()
})

function supplierName(id: string) { return suppliers.value.find((s) => s.id === id)?.name ?? id }
function branchName(id: string) { return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id) }

// ---- new entry ("save and continue") ---------------------------------------
const row = ref<PurchaseEntryRow>({
  date: todayJst(), branchId: auth.branchId ?? '', supplierId: '', itemName: '', quantity: 1, unitPrice: 0, note: '',
})
const fields = ref<InstanceType<typeof PurchaseEntryFields>>()
const saving = ref(false)
const savedBadge = ref(false)
let badgeTimer: ReturnType<typeof setTimeout> | undefined

async function saveAndContinue() {
  const problem = validatePurchaseRow(row.value)
  if (problem) {
    ElMessage.warning(t(problem.key))
    if (problem.field === 'itemName') fields.value?.focusItemName()
    return
  }
  saving.value = true
  try {
    const payload = buildPurchasePayload(row.value)
    const wasNew = !!fields.value?.isNewItem
    await createPurchase(payload)
    if (wasNew) fields.value?.noteAdded(payload.itemName)
    // Date, branch and supplier stay for the next item of the same delivery.
    row.value.itemName = ''
    row.value.quantity = 1
    row.value.unitPrice = 0
    row.value.note = ''
    savedBadge.value = true
    clearTimeout(badgeTimer)
    badgeTimer = setTimeout(() => { savedBadge.value = false }, 2500)
    await nextTick()
    fields.value?.focusItemName()
    await load()
  } finally {
    saving.value = false
  }
}

// ---- edit drawer ---------------------------------------------------------------
const editOpen = ref(false)
const editId = ref<string | null>(null)
const editRow = ref<PurchaseEntryRow>({ date: '', branchId: '', supplierId: '', itemName: '', quantity: 1, unitPrice: 0, note: '' })

function openEdit(record: PurchaseRecord) {
  editId.value = record.id
  Object.assign(editRow.value, {
    date: record.date, branchId: record.branchId, supplierId: record.supplierId, itemName: record.itemName,
    quantity: record.quantity, unitPrice: record.unitPrice, note: record.note,
  })
  editOpen.value = true
}
async function saveEdit() {
  if (!editId.value) return
  const problem = validatePurchaseRow(editRow.value)
  if (problem) { ElMessage.warning(t(problem.key)); return }
  saving.value = true
  try {
    await updatePurchase(editId.value, buildPurchasePayload(editRow.value))
    ElMessage.success(t('common.savedSuccess'))
    editOpen.value = false
    await load()
  } finally {
    saving.value = false
  }
}
async function removeEdit() {
  if (!editId.value) return
  try {
    await ElMessageBox.confirm(t('purchasing.deleteConfirm'), t('common.confirm'), {
      type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'),
    })
    await deletePurchase(editId.value)
    ElMessage.success(t('common.deletedSuccess'))
    editOpen.value = false
    await load()
  } catch { /* cancelled */ }
}

// ---- filters ---------------------------------------------------------------------
const filterOpen = ref(false)
function applyFilters() { filterOpen.value = false; void load() }
function resetFilters() {
  Object.assign(filters, {
    month: currentMonthJst(), branchId: isAdmin.value ? '' : (auth.branchId ?? ''),
    supplierId: '', itemName: '', priceChange: '', ordering: '-date',
  })
}

// ---- price history -------------------------------------------------------------------
const historyOpen = ref(false)
const historyTarget = ref<PurchaseRecord | null>(null)
const historyEntries = ref<PriceHistoryEntry[]>([])
const historyLoading = ref(false)
async function openHistory(record: PurchaseRecord) {
  historyTarget.value = record
  historyEntries.value = []
  historyOpen.value = true
  historyLoading.value = true
  try {
    historyEntries.value = await fetchPriceHistory(record.branchId, record.supplierId, record.itemName)
  } finally {
    historyLoading.value = false
  }
}
</script>

<template>
  <div class="pme">
    <header class="pme-head">
      <h1 class="pme-title">{{ t('purchasing.pageTitle') }}</h1>
      <p class="pme-total">{{ t('purchasing.monthTotal') }}<strong>{{ formatCurrency(monthTotal) }}</strong></p>
    </header>

    <section v-if="!isAdmin" class="pme-card" aria-labelledby="pme-new">
      <h2 id="pme-new" class="pme-h">{{ t('purchasing.mNewTitle') }}</h2>
      <p class="pme-note">{{ t('purchasing.mCarryOver') }}</p>
      <PurchaseEntryFields ref="fields" v-model:row="row" :suppliers="suppliers" />
      <p v-if="savedBadge" class="pme-saved" role="status">{{ t('purchasing.savedPulse') }}</p>
      <button type="button" class="pme-btn pme-btn-primary" :disabled="saving" @click="saveAndContinue">{{ t('purchasing.mSaveNext') }}</button>
    </section>
    <p v-else class="pme-note pme-viewonly">{{ t('purchasing.mViewOnly') }}</p>

    <section class="pme-list" aria-labelledby="pme-records">
      <div class="pme-list-head">
        <h2 id="pme-records" class="pme-h">{{ t('purchasing.mRecordsTitle') }}<span class="pme-count">{{ t('purchasing.mCount', { count: totalCount }) }}</span></h2>
        <button type="button" class="pme-btn pme-btn-ghost pme-filter-btn" @click="filterOpen = true">
          <el-icon :size="20"><Filter /></el-icon>{{ t('purchasing.mFilter') }}
          <span v-if="activeFilterCount" class="pme-badge" :aria-label="t('purchasing.mFilterOn')">{{ activeFilterCount }}</span>
        </button>
      </div>

      <p v-if="!loading && !records.length" class="pme-note pme-empty">{{ t('purchasing.empty') }}</p>
      <article v-for="rec in records" :key="rec.id" class="pme-rec">
        <div class="pme-rec-top">
          <span class="pme-rec-date">{{ rec.date }}<template v-if="isAdmin"> ・ {{ branchName(rec.branchId) }}</template></span>
          <strong class="pme-rec-amount">{{ formatCurrency(rec.amount) }}</strong>
        </div>
        <div class="pme-rec-item">{{ rec.itemName }}</div>
        <div class="pme-rec-meta">{{ supplierName(rec.supplierId) }} ・ {{ rec.quantity }} × {{ formatCurrency(rec.unitPrice) }}</div>
        <p v-if="rec.priorPurchaseDirection" class="pme-rec-change" :class="`is-${rec.priorPurchaseDirection}`">
          <el-icon :size="18"><component :is="rec.priorPurchaseDirection === 'up' ? ArrowUp : ArrowDown" /></el-icon>
          {{ t(rec.priorPurchaseDirection === 'up' ? 'purchasing.mPriceUp' : 'purchasing.mPriceDown', { amount: formatCurrency(Math.abs(rec.priorPurchaseDeltaAmount ?? 0)) }) }}
        </p>
        <p v-if="rec.note" class="pme-rec-note">{{ rec.note }}</p>
        <div class="pme-rec-actions">
          <button type="button" class="pme-btn pme-btn-ghost" @click="openHistory(rec)">{{ t('purchasing.mPriceHistory') }}</button>
          <button v-if="!isAdmin" type="button" class="pme-btn pme-btn-ghost" @click="openEdit(rec)">{{ t('purchasing.mEditRecord') }}</button>
        </div>
      </article>
      <button v-if="hasMore" type="button" class="pme-btn pme-btn-ghost pme-more" :disabled="loading" @click="loadMore">{{ t('purchasing.mLoadMore') }}</button>
    </section>

    <MobileSheet v-model="editOpen" :title="t('purchasing.mEditTitle')" :close-label="t('nav.closeMenu')">
      <PurchaseEntryFields v-model:row="editRow" :suppliers="suppliers" />
      <template #footer>
        <div class="pme-sheet-actions">
          <button type="button" class="pme-btn pme-btn-danger" @click="removeEdit">{{ t('common.delete') }}</button>
          <button type="button" class="pme-btn pme-btn-primary" :disabled="saving" @click="saveEdit">{{ t('purchasing.mUpdate') }}</button>
        </div>
      </template>
    </MobileSheet>

    <MobileSheet v-model="filterOpen" :title="t('purchasing.mFilter')" :close-label="t('nav.closeMenu')">
      <div class="pme-filters">
        <div class="pme-field">
          <label class="pme-label" for="pme-f-month">{{ t('purchasing.mMonth') }}</label>
          <input id="pme-f-month" v-model="filters.month" class="pme-input" type="month">
        </div>
        <div v-if="isAdmin" class="pme-field">
          <label class="pme-label" for="pme-f-branch">{{ t('purchasing.branch') }}</label>
          <select id="pme-f-branch" v-model="filters.branchId" class="pme-input">
            <option value="">{{ t('purchasing.allBranches') }}</option>
            <option v-for="b in branchStore.list" :key="b.id" :value="b.id">{{ branchDisplayName(b, locale) }}</option>
          </select>
        </div>
        <div class="pme-field">
          <label class="pme-label" for="pme-f-supplier">{{ t('purchasing.supplier') }}</label>
          <select id="pme-f-supplier" v-model="filters.supplierId" class="pme-input">
            <option value="">{{ t('purchasing.allSuppliers') }}</option>
            <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <div class="pme-field">
          <label class="pme-label" for="pme-f-item">{{ t('purchasing.itemName') }}</label>
          <input id="pme-f-item" v-model="filters.itemName" class="pme-input" type="text" autocomplete="off">
        </div>
        <div class="pme-field">
          <label class="pme-label" for="pme-f-change">{{ t('purchasing.mFieldPriceChange') }}</label>
          <select id="pme-f-change" v-model="filters.priceChange" class="pme-input" :disabled="!filters.month">
            <option value="">{{ t('purchasing.priceChangeAny') }}</option>
            <option value="up">{{ t('purchasing.priceChangeUp') }}</option>
            <option value="down">{{ t('purchasing.priceChangeDown') }}</option>
          </select>
        </div>
        <div class="pme-field">
          <label class="pme-label" for="pme-f-sort">{{ t('purchasing.mFieldSort') }}</label>
          <select id="pme-f-sort" v-model="filters.ordering" class="pme-input">
            <option value="-date">{{ t('purchasing.sortDateDesc') }}</option>
            <option value="date">{{ t('purchasing.sortDateAsc') }}</option>
            <option value="-unit_price">{{ t('purchasing.sortPriceDesc') }}</option>
            <option value="unit_price">{{ t('purchasing.sortPriceAsc') }}</option>
          </select>
        </div>
      </div>
      <template #footer>
        <div class="pme-sheet-actions">
          <button type="button" class="pme-btn pme-btn-ghost" @click="resetFilters">{{ t('purchasing.mFilterReset') }}</button>
          <button type="button" class="pme-btn pme-btn-primary" @click="applyFilters">{{ t('purchasing.mFilterApply') }}</button>
        </div>
      </template>
    </MobileSheet>

    <MobileSheet v-model="historyOpen" :title="t('purchasing.priceHistoryTitle')" :close-label="t('nav.closeMenu')">
      <p v-if="historyTarget" class="pme-rec-item">{{ historyTarget.itemName }}</p>
      <p v-if="!historyLoading && !historyEntries.length" class="pme-note">{{ t('purchasing.noHistory') }}</p>
      <ul class="pme-history">
        <li v-for="h in historyEntries" :key="h.id">
          <span>{{ h.date }}</span>
          <span>{{ h.quantity }} × <strong>{{ formatCurrency(h.unitPrice) }}</strong></span>
        </li>
      </ul>
    </MobileSheet>
  </div>
</template>

<style scoped>
.pme { display: flex; flex-direction: column; gap: 16px; font-size: 16px; color: var(--text-primary); }
.pme-head { display: flex; flex-direction: column; gap: 4px; }
.pme-title { margin: 0; font-size: 22px; font-weight: 800; }
.pme-total { margin: 0; display: flex; align-items: baseline; justify-content: space-between; gap: 8px; font-size: 16px; color: var(--text-secondary); }
.pme-total strong { font-size: 22px; color: var(--text-primary); }
.pme-card { display: flex; flex-direction: column; gap: 16px; padding: 18px 16px; background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-soft); }
.pme-h { margin: 0; font-size: 20px; font-weight: 800; display: flex; align-items: baseline; gap: 10px; }
.pme-count { font-size: 16px; font-weight: 600; color: var(--text-secondary); }
.pme-note { margin: 0; font-size: 16px; color: var(--text-secondary); }
.pme-viewonly { padding: 12px 14px; background: var(--surface); border-radius: 12px; font-size: 16px; }
.pme-empty { text-align: center; padding: 24px 0; font-size: 16px; }
.pme-saved { margin: 0; padding: 12px 14px; border-radius: 12px; background: var(--success-light); color: var(--success); font-size: 17px; font-weight: 800; text-align: center; }
.pme-btn {
  min-height: 56px; padding: 0 18px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; box-sizing: border-box;
  font: inherit; font-size: 17px; font-weight: 800; border-radius: 14px; border: 2px solid transparent; cursor: pointer;
}
.pme-btn:disabled { opacity: 0.5; cursor: default; }
.pme-btn-primary { background: var(--accent); color: #fff; }
.pme-btn-ghost { background: var(--surface); color: var(--text-primary); border-color: var(--border-strong, #c9cdd1); }
.pme-btn-danger { background: var(--surface); color: var(--danger); border-color: var(--danger); }
.pme-list { display: flex; flex-direction: column; gap: 12px; }
.pme-list-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pme-filter-btn { min-height: 52px; position: relative; }
.pme-badge { min-width: 24px; height: 24px; padding: 0 6px; border-radius: 12px; background: var(--accent); color: #fff; font-size: 14px; display: inline-flex; align-items: center; justify-content: center; }
.pme-rec { display: flex; flex-direction: column; gap: 6px; padding: 16px; background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-soft); }
.pme-rec-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.pme-rec-date { font-size: 16px; color: var(--text-secondary); }
.pme-rec-amount { font-size: 20px; }
.pme-rec-item { font-size: 18px; font-weight: 800; word-break: break-word; }
.pme-rec-meta { font-size: 16px; color: var(--text-secondary); }
.pme-rec-change { margin: 0; display: flex; align-items: center; gap: 4px; font-size: 16px; font-weight: 700; }
.pme-rec-change.is-up { color: var(--danger); }
.pme-rec-change.is-down { color: var(--success); }
.pme-rec-note { margin: 0; font-size: 16px; color: var(--text-secondary); word-break: break-word; }
.pme-rec-actions { display: flex; gap: 8px; margin-top: 6px; }
.pme-rec-actions .pme-btn { flex: 1; min-height: 52px; font-size: 16px; padding: 0 8px; }
.pme-more { width: 100%; }
.pme-sheet-actions { display: grid; grid-template-columns: 1fr 1.6fr; gap: 10px; }
.pme-filters { display: flex; flex-direction: column; gap: 16px; }
.pme-field { display: flex; flex-direction: column; gap: 6px; }
.pme-label { font-size: 16px; font-weight: 700; }
.pme-input {
  width: 100%; box-sizing: border-box; min-height: 56px; padding: 0 14px; font: inherit; font-size: 18px; color: var(--text-primary);
  background: var(--surface); border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; outline: 0;
}
.pme-input:focus { border-color: var(--accent); }
.pme-history { list-style: none; margin: 0; padding: 0; }
.pme-history li { display: flex; justify-content: space-between; gap: 10px; min-height: 52px; align-items: center; border-bottom: 1px solid var(--border); font-size: 17px; }
</style>
