<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type InputInstance } from 'element-plus'
import { Edit, Delete, Close, MoreFilled, TrendCharts, Refresh, CircleCheckFilled } from '@element-plus/icons-vue'
import { fetchSuppliers, type Supplier } from '@/api/suppliers'
import {
  fetchPurchases,
  fetchAllPurchases,
  createPurchase,
  updatePurchase,
  deletePurchase,
  fetchPurchaseItemSuggestions,
  fetchPriceHistory,
  fetchSupplierPriceComparison,
  type PurchaseItemSuggestion,
  type PurchaseRecord,
  type PriceHistoryEntry,
  type SupplierPriceComparisonEntry,
} from '@/api/purchasing'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { formatCurrency, branchDisplayName, todayJst, currentMonthJst } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()

const isAdmin = computed(() => auth.role === 'admin')

const suppliers = ref<Supplier[]>([])
const purchases = ref<PurchaseRecord[]>([])
const totalCount = ref(0)
const monthTotal = ref(0)
const { loading, run } = useDelayedLoading()
const editingId = ref<string | null>(null)

const itemNameInput = ref<InputInstance>()
const savedPulse = ref(false)
let savedPulseTimer: ReturnType<typeof setTimeout> | undefined

interface SuggestionOption extends PurchaseItemSuggestion {
  value: string
}

const row = reactive({
  date: todayJst(),
  branchId: auth.branchId ?? '',
  supplierId: '',
  itemName: '',
  quantity: 1,
  unitPrice: 0,
  note: '',
})

const amountPreview = computed(() => row.quantity * row.unitPrice)

// ---- Filters + server-side pagination ------------------------------------

const filters = reactive({
  month: currentMonthJst() as string | null,
  branchId: isAdmin.value ? '' : (auth.branchId ?? ''),
  supplierId: '',
  itemName: '',
  priceChange: '' as '' | 'up' | 'down',
  ordering: '-date',
})
const currentPage = ref(1)
const pageSize = 20

function branchName(branchId: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === branchId), locale.value, branchId)
}

function supplierName(supplierId: string) {
  return suppliers.value.find((s) => s.id === supplierId)?.name ?? supplierId
}

async function fetchData() {
  const [page, allForTotal] = await Promise.all([
    fetchPurchases({
      branchId: filters.branchId || undefined,
      supplierId: filters.supplierId || undefined,
      month: filters.month || undefined,
      itemName: filters.itemName || undefined,
      priceChange: filters.priceChange || undefined,
      ordering: filters.ordering,
      page: currentPage.value,
      pageSize,
    }),
    // Total reflects every matching record, not just the current page —
    // bounded by the same filters (typically a single month), so this
    // never approaches the full 5000+ record table.
    fetchAllPurchases({
      branchId: filters.branchId || undefined,
      supplierId: filters.supplierId || undefined,
      month: filters.month || undefined,
      itemName: filters.itemName || undefined,
    }),
  ])
  purchases.value = page.results
  totalCount.value = page.count
  monthTotal.value = allForTotal.reduce((sum, p) => sum + p.amount, 0)
}

async function load() {
  await run(fetchData)
}

// After adding/deleting a single row the user's attention is still on the
// entry form (often mid rapid-Enter data entry), not the table below — a
// full-table loading mask on every one of these background refreshes reads
// as flicker, not feedback, so these never toggle the loading flag at all.
async function refreshSilently() {
  await fetchData()
}

function applyFilters() {
  currentPage.value = 1
  load()
}

function resetFilters() {
  filters.month = currentMonthJst()
  filters.branchId = isAdmin.value ? '' : (auth.branchId ?? '')
  filters.supplierId = ''
  filters.itemName = ''
  filters.priceChange = ''
  filters.ordering = '-date'
  applyFilters()
}

watch(() => filters.month, (month) => {
  if (!month) filters.priceChange = ''
})

watch(currentPage, load)

onMounted(async () => {
  await branchStore.ensureLoaded()
  suppliers.value = await fetchSuppliers()
  await load()
})

function focusItemName() {
  nextTick(() => itemNameInput.value?.focus())
}

function resetRow() {
  // Date, branch and supplier stay put — a single delivery usually adds
  // several lines for the same branch/supplier, so re-picking them every
  // row would defeat the point of a spreadsheet-style entry.
  row.itemName = ''
  row.quantity = 1
  row.unitPrice = 0
  row.note = ''
  focusItemName()
}

function cancelEdit() {
  editingId.value = null
  resetRow()
}

function startEdit(record: PurchaseRecord) {
  editingId.value = record.id
  row.date = record.date
  row.branchId = record.branchId
  row.supplierId = record.supplierId
  row.itemName = record.itemName
  row.quantity = record.quantity
  row.unitPrice = record.unitPrice
  row.note = record.note
  focusItemName()
}

async function querySuggestions(queryString: string, cb: (results: SuggestionOption[]) => void) {
  if (!row.supplierId) {
    cb([])
    return
  }
  const results = await fetchPurchaseItemSuggestions(row.supplierId, queryString)
  cb(results.map((s) => ({ ...s, value: s.itemName })))
}

function handleSelectSuggestion(suggestion: SuggestionOption) {
  row.itemName = suggestion.itemName
  row.unitPrice = suggestion.lastUnitPrice
}

// IME input methods (Japanese/Chinese) use Enter to confirm kanji/character
// conversion, not to submit — without this guard, confirming a candidate
// mid-composition also fires our row-submit handler and commits a half-typed
// item name. `isComposing` is only reliable at keydown (by keyup it has
// often already flipped false), so this must bind to @keydown, not @keyup.
function handleRowEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  commitRow()
}

async function commitRow() {
  if (!row.branchId) {
    ElMessage.warning(t('purchasing.validateBranch'))
    return
  }
  if (!row.supplierId) {
    ElMessage.warning(t('purchasing.validateSupplier'))
    return
  }
  if (!row.itemName.trim()) {
    ElMessage.warning(t('purchasing.validateItemName'))
    focusItemName()
    return
  }

  const payload = {
    date: row.date,
    branchId: row.branchId,
    supplierId: row.supplierId,
    itemName: row.itemName.trim(),
    quantity: row.quantity,
    unitPrice: row.unitPrice,
    note: row.note,
  }

  if (editingId.value) {
    await updatePurchase(editingId.value, payload)
    editingId.value = null
  } else {
    await createPurchase(payload)
  }
  triggerSavedPulse()
  resetRow()
  await refreshSilently()
}

// Brief inline confirmation next to the entry row — a full ElMessage toast
// would be overkill for something the user does dozens of times per
// delivery, and stealing focus for it would break the rapid Enter-to-add
// flow, so this just fades a small badge in and back out on its own.
function triggerSavedPulse() {
  savedPulse.value = false
  nextTick(() => {
    savedPulse.value = true
    clearTimeout(savedPulseTimer)
    savedPulseTimer = setTimeout(() => { savedPulse.value = false }, 1400)
  })
}

async function handleDelete(record: PurchaseRecord) {
  try {
    await ElMessageBox.confirm(t('purchasing.deleteConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deletePurchase(record.id)
    ElMessage.success(t('common.deletedSuccess'))
    if (editingId.value === record.id) cancelEdit()
    await refreshSilently()
  } catch {
    // cancelled
  }
}

// ---- Price history + cross-supplier comparison drawer --------------------

const historyDrawerVisible = ref(false)
const { loading: historyLoading, run: runHistoryLoad } = useDelayedLoading()
const historyTarget = ref<PurchaseRecord | null>(null)
const historyEntries = ref<PriceHistoryEntry[]>([])
const comparisonEntries = ref<SupplierPriceComparisonEntry[]>([])

async function openPriceHistory(record: PurchaseRecord) {
  historyTarget.value = record
  historyDrawerVisible.value = true
  await runHistoryLoad(async () => {
    const [history, comparison] = await Promise.all([
      fetchPriceHistory(record.branchId, record.supplierId, record.itemName),
      fetchSupplierPriceComparison(record.branchId, record.itemName),
    ])
    historyEntries.value = history
    comparisonEntries.value = comparison
  })
}

</script>

<template>
  <div class="purchasing-view">
    <div class="card">
      <div class="page-header">
        <div>
          <h3>{{ t('purchasing.pageTitle') }}</h3>
          <span class="month-total">{{ t('purchasing.monthTotal') }} {{ formatCurrency(monthTotal) }}</span>
        </div>
        <span v-if="editingId" class="cancel-edit" @click="cancelEdit">
          <el-icon><Close /></el-icon>{{ t('common.cancel') }}
        </span>
      </div>

      <div v-if="!isAdmin" class="entry-table">
        <div class="entry-head">
          <span class="c-date">{{ t('purchasing.date') }}</span>
          <span class="c-supplier">{{ t('purchasing.supplier') }}</span>
          <span class="c-item">{{ t('purchasing.itemName') }}</span>
          <span class="c-qty">{{ t('purchasing.quantity') }}</span>
          <span class="c-price">{{ t('purchasing.unitPrice') }}</span>
          <span class="c-amount">{{ t('purchasing.amountAuto') }}</span>
          <span class="c-note">{{ t('purchasing.note') }}</span>
        </div>
        <div class="entry-row">
          <div class="c-date">
            <el-date-picker
              v-model="row.date"
              type="date"
              :clearable="false"
              value-format="YYYY-MM-DD"
            />
          </div>
          <el-select v-model="row.supplierId" :placeholder="t('purchasing.supplierPlaceholder')" class="c-supplier" @change="focusItemName">
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
          <div class="c-item">
            <el-autocomplete
              ref="itemNameInput"
              v-model="row.itemName"
              :placeholder="t('purchasing.itemNamePlaceholder')"
              :fetch-suggestions="querySuggestions"
              @select="handleSelectSuggestion"
              @keydown.enter="handleRowEnter"
            >
              <template #default="{ item }">
                <div class="suggestion-item">
                  <span>{{ item.itemName }}</span>
                  <span class="suggestion-meta">{{ formatCurrency(item.lastUnitPrice) }}</span>
                </div>
              </template>
            </el-autocomplete>
          </div>
          <el-input v-model.number="row.quantity" type="number" class="c-qty" @keydown.enter="handleRowEnter" />
          <el-input v-model.number="row.unitPrice" type="number" class="c-price" @keydown.enter="handleRowEnter">
            <template #prefix>¥</template>
          </el-input>
          <el-input :model-value="amountPreview" disabled class="c-amount">
            <template #prefix>¥</template>
          </el-input>
          <el-input v-model="row.note" class="c-note" @keydown.enter="handleRowEnter" />
        </div>
        <div class="entry-hint">
          {{ t('purchasing.enterHint') }}
          <transition name="saved-pulse">
            <span v-if="savedPulse" class="saved-pulse-badge">
              <el-icon><CircleCheckFilled /></el-icon>{{ t('purchasing.savedPulse') }}
            </span>
          </transition>
        </div>
      </div>

      <div class="filter-bar">
        <el-date-picker
          v-model="filters.month"
          type="month"
          value-format="YYYY-MM"
          clearable
          :placeholder="t('purchasing.filterMonth')"
          class="f-month"
          @change="applyFilters"
        />
        <el-select v-if="isAdmin" v-model="filters.branchId" clearable :placeholder="t('purchasing.allBranches')" class="f-branch" @change="applyFilters">
          <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
        </el-select>
        <el-select v-model="filters.supplierId" clearable :placeholder="t('purchasing.allSuppliers')" class="f-supplier" @change="applyFilters">
          <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
        </el-select>
        <el-input
          v-model="filters.itemName"
          :placeholder="t('purchasing.filterItemNamePlaceholder')"
          clearable
          class="f-item"
          @keydown.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-select
          v-model="filters.priceChange"
          :disabled="!filters.month"
          :placeholder="t('purchasing.priceChangeAny')"
          class="f-price-change"
          @change="applyFilters"
        >
          <el-option value="" :label="t('purchasing.priceChangeAny')" />
          <el-option value="up" :label="t('purchasing.priceChangeUp')" />
          <el-option value="down" :label="t('purchasing.priceChangeDown')" />
        </el-select>
        <el-select v-model="filters.ordering" class="f-sort" @change="applyFilters">
          <el-option value="-date" :label="t('purchasing.sortDateDesc')" />
          <el-option value="date" :label="t('purchasing.sortDateAsc')" />
          <el-option value="-unit_price" :label="t('purchasing.sortPriceDesc')" />
          <el-option value="unit_price" :label="t('purchasing.sortPriceAsc')" />
        </el-select>
        <el-button :icon="Refresh" @click="resetFilters">{{ t('common.reset') }}</el-button>
      </div>

      <el-table :data="purchases" v-loading="loading" :empty-text="t('purchasing.empty')" class="purchase-table">
        <el-table-column prop="date" :label="t('purchasing.date')" width="120" />
        <el-table-column v-if="isAdmin" :label="t('purchasing.branch')" width="110">
          <template #default="{ row: r }">{{ branchName(r.branchId) }}</template>
        </el-table-column>
        <el-table-column :label="t('purchasing.supplier')" min-width="140">
          <template #default="{ row: r }">{{ supplierName(r.supplierId) }}</template>
        </el-table-column>
        <el-table-column :label="t('purchasing.itemName')" min-width="160">
          <template #default="{ row: r }">
            <span class="item-name-link" @click="openPriceHistory(r)">{{ r.itemName }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" :label="t('purchasing.quantity')" width="90" />
        <el-table-column :label="t('purchasing.unitPrice')" width="130">
          <template #default="{ row: r }">
            <div>{{ formatCurrency(r.unitPrice) }}</div>
            <div v-if="r.priceDirection && r.priceDeltaAmount !== null" class="price-change-detail" :class="r.priceDirection">
              {{ t('purchasing.comparedWithPreviousMonth') }}
              {{ r.priceDeltaAmount >= 0 ? '+' : '−' }}{{ formatCurrency(Math.round(Math.abs(r.priceDeltaAmount))) }}
              <span v-if="r.priceDeltaPercent !== null">（{{ r.priceDeltaPercent >= 0 ? '+' : '' }}{{ r.priceDeltaPercent.toFixed(1) }}%）</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchasing.amountAuto')" width="120">
          <template #default="{ row: r }">{{ formatCurrency(r.amount) }}</template>
        </el-table-column>
        <el-table-column type="expand" width="42">
          <template #default="{ row: r }">
            <div class="record-note-detail"><strong>{{ t('purchasing.note') }}：</strong>{{ r.note || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="88" fixed="right">
          <template #default="{ row: r }">
            <el-button circle text :icon="TrendCharts" size="small" @click="openPriceHistory(r)" />
            <el-dropdown v-if="!isAdmin" trigger="click">
              <el-button circle text :icon="MoreFilled" size="small" @click.stop />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item :icon="Edit" @click="startEdit(r)">{{ t('common.edit') }}</el-dropdown-item>
                  <el-dropdown-item :icon="Delete" @click="handleDelete(r)">{{ t('common.delete') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="totalCount"
          layout="prev, pager, next, total"
          background
        />
      </div>
    </div>

    <el-drawer v-model="historyDrawerVisible" :title="t('purchasing.priceHistoryTitle')" size="420px">
      <div v-loading="historyLoading">
        <template v-if="historyTarget">
          <p class="drawer-subject">
            {{ historyTarget.itemName }}　·　{{ supplierName(historyTarget.supplierId) }}　·　{{ branchName(historyTarget.branchId) }}
          </p>

          <h4 class="drawer-section-title">{{ t('purchasing.priceHistoryTitle') }}</h4>
          <el-table :data="historyEntries" size="small" :empty-text="t('purchasing.noHistory')">
            <el-table-column prop="date" :label="t('purchasing.date')" width="110" />
            <el-table-column prop="quantity" :label="t('purchasing.quantity')" width="80" />
            <el-table-column :label="t('purchasing.unitPrice')" width="100">
              <template #default="{ row: h }">{{ formatCurrency(h.unitPrice) }}</template>
            </el-table-column>
          </el-table>

          <h4 class="drawer-section-title">{{ t('purchasing.supplierComparisonTitle') }}</h4>
          <el-table :data="comparisonEntries" size="small" :empty-text="t('purchasing.noHistory')">
            <el-table-column prop="supplierName" :label="t('purchasing.supplier')" min-width="120" />
            <el-table-column :label="t('purchasing.latestPrice')" width="100">
              <template #default="{ row: c }">{{ c.latestUnitPrice !== null ? formatCurrency(c.latestUnitPrice) : '—' }}</template>
            </el-table-column>
            <el-table-column :label="t('purchasing.avgPrice')" width="100">
              <template #default="{ row: c }">{{ c.avgUnitPrice !== null ? formatCurrency(Math.round(c.avgUnitPrice)) : '—' }}</template>
            </el-table-column>
            <el-table-column prop="recordCount" :label="t('purchasing.recordCount')" width="70" />
          </el-table>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.page-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.month-total {
  font-size: 12px;
  color: var(--text-tertiary);
}

.cancel-edit {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 120ms ease;
}

.cancel-edit:hover {
  color: var(--text-primary);
}

.entry-table {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-alt);
  padding: 10px 12px 6px;
  margin-bottom: 20px;
}

.entry-head,
.entry-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.entry-head {
  padding: 0 2px 6px;
}

.entry-head span {
  font-size: 11.5px;
  color: var(--text-tertiary);
}

.entry-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  padding: 6px 2px 2px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.saved-pulse-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--success);
  background: var(--success-light);
  padding: 2px 9px;
  border-radius: 20px;
}

.saved-pulse-enter-active {
  transition: opacity 0.18s ease-out, transform 0.18s ease-out;
}

.saved-pulse-leave-active {
  transition: opacity 0.28s ease-out;
}

.saved-pulse-enter-from {
  opacity: 0;
  transform: translateY(-2px) scale(0.92);
}

.saved-pulse-leave-to {
  opacity: 0;
}

.c-date {
  flex: 1.3 1.3 0;
  min-width: 0;
}

.c-branch {
  flex: 1 1 0;
  min-width: 0;
}

.c-supplier {
  flex: 1.4 1.4 0;
  min-width: 0;
}

.c-item {
  flex: 1.6 1.6 0;
  min-width: 0;
}

.c-qty {
  flex: 0.7 0.7 0;
  min-width: 0;
}

.c-price {
  flex: 1 1 0;
  min-width: 0;
}

.c-amount {
  flex: 1 1 0;
  min-width: 0;
}

.c-note {
  flex: 0.8 0.8 0;
  min-width: 0;
}

.price-change-detail {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.25;
  color: var(--text-tertiary);
}

.price-change-detail.up {
  color: var(--danger);
}

.price-change-detail.down {
  color: var(--success);
}

.record-note-detail {
  padding: 8px 18px;
  color: var(--text-secondary);
  font-size: 12px;
}

.entry-row :deep(.el-input__wrapper),
.entry-row :deep(.el-select) {
  width: 100%;
}

.c-date :deep(.el-date-editor),
.c-item :deep(.el-autocomplete) {
  width: 100%;
}

.suggestion-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.suggestion-meta {
  color: var(--text-tertiary);
  font-size: 12px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.f-month {
  width: 140px;
}

.f-branch,
.f-supplier {
  width: 140px;
}

.f-item {
  width: 180px;
}

.f-price-change,
.f-sort {
  width: 130px;
}

.item-name-link {
  cursor: pointer;
}

.item-name-link:hover {
  text-decoration: underline;
}

.purchase-table {
  margin-top: 4px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.drawer-subject {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 16px;
}

.drawer-section-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 18px 0 8px;
}
</style>
