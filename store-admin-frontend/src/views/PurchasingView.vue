<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type AutocompleteInstance } from 'element-plus'
import {
  Edit, Delete, Close, MoreFilled, TrendCharts, Refresh, CircleCheckFilled, MagicStick,
} from '@element-plus/icons-vue'
import { fetchSuppliers, type Supplier } from '@/api/suppliers'
import {
  fetchPurchases,
  fetchPurchaseMonthTotal,
  createPurchase,
  updatePurchase,
  deletePurchase,
  fetchPurchaseItemSuggestions,
  fetchPriceHistory,
  fetchSupplierPriceComparison,
  bulkReplacePurchases,
  type PurchaseItemSuggestion,
  type PurchaseRecord,
  type PriceHistoryEntry,
  type SupplierPriceComparisonEntry,
  type BulkReplacePreviewRow,
  type BulkReplaceMatch,
  type BulkReplaceWith,
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

const itemNameInput = ref<AutocompleteInstance>()
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
  const [page, total] = await Promise.all([
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
    // Summed DB-side — this used to mean paging through every matching
    // record client-side just to add up a total (the main cost behind the
    // multi-second filter/page delay this page used to have).
    fetchPurchaseMonthTotal({
      branchId: filters.branchId || undefined,
      supplierId: filters.supplierId || undefined,
      month: filters.month || undefined,
      itemName: filters.itemName || undefined,
    }),
  ])
  purchases.value = page.results
  totalCount.value = page.count
  monthTotal.value = total
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

// Used only right after a row is submitted, when the field auto-refocuses
// empty for rapid successive entry. A plain focus() here would trigger
// el-autocomplete's own trigger-on-focus behavior and pop the full recent-
// items list open the instant the row is submitted — not something the
// user asked for, just a side effect of the field regaining focus. Forcing
// `activated` back off right after cancels that specific auto-open without
// touching trigger-on-focus itself, so a genuine click into the field
// afterward still opens the browse dropdown normally (that click's own
// focus event sets `activated` true again on its own).
function focusItemNameSilently() {
  nextTick(() => {
    itemNameInput.value?.focus()
    if (itemNameInput.value) itemNameInput.value.activated = false
  })
}

function resetRow() {
  // Date, branch and supplier stay put — a single delivery usually adds
  // several lines for the same branch/supplier, so re-picking them every
  // row would defeat the point of a spreadsheet-style entry.
  row.itemName = ''
  row.quantity = 1
  row.unitPrice = 0
  row.note = ''
  focusItemNameSilently()
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

// Item names this supplier has actually been paid for before, for one
// specific purpose: telling the "新商品" hint apart from an ordinary known
// item while typing (see isNewItem below). Populated from the same
// suggestion query, not a separate request.
const knownItemNames = ref<Set<string>>(new Set())

async function querySuggestions(queryString: string, cb: (results: SuggestionOption[]) => void) {
  if (!row.supplierId) {
    cb([])
    return
  }
  const results = await fetchPurchaseItemSuggestions(row.supplierId, queryString)
  if (!queryString) knownItemNames.value = new Set(results.map((s) => s.itemName))
  cb(results.map((s) => ({ ...s, value: s.itemName })))
}

watch(() => row.supplierId, async (supplierId) => {
  knownItemNames.value = supplierId
    ? new Set((await fetchPurchaseItemSuggestions(supplierId)).map((s) => s.itemName))
    : new Set()
})

const isNewItem = computed(() => {
  const name = row.itemName.trim()
  return !!name && !knownItemNames.value.has(name)
})

function handleSelectSuggestion(suggestion: SuggestionOption) {
  row.itemName = suggestion.itemName
  row.unitPrice = suggestion.lastUnitPrice
}

// IME input methods (Japanese/Chinese) use Enter to confirm kanji/character
// conversion, not to submit — without this guard, confirming a candidate
// mid-composition also fires our row-submit handler and commits a half-typed
// item name. `isComposing` is only reliable at keydown (by keyup it has
// often already flipped false), so this must bind to @keydown, not @keyup.
// The lastCompositionEndAt check is a second layer for browsers where the
// very keydown that ends composition can still report isComposing:false —
// a real, separate Enter press essentially never lands inside that window.
const lastCompositionEndAt = ref(0)
function handleCompositionEnd() {
  lastCompositionEndAt.value = Date.now()
}
function handleRowEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  if (Date.now() - lastCompositionEndAt.value < 80) return
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
  if (!row.quantity || row.quantity <= 0) {
    ElMessage.warning(t('purchasing.validateQuantity'))
    return
  }
  if (!row.unitPrice || row.unitPrice <= 0) {
    ElMessage.warning(t('purchasing.validateUnitPrice'))
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
    // A brand-new item name just got added to this supplier's history —
    // refresh the known-names set so isNewItem doesn't still flag it as
    // new on the very next row (resetRow's focus deliberately suppresses
    // el-autocomplete's own fetch, so nothing else would do this).
    if (isNewItem.value) {
      knownItemNames.value = new Set([...knownItemNames.value, payload.itemName])
    }
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

// ---- Batch find-and-replace (fixing one repeated wrong date/supplier) ----
// Match conditions combine (AND) so a specific bad delivery — "everything
// on 2026-08-15 from supplier X" — can be pinned down precisely; date alone
// or supplier alone usually matches far more rows than intended.

const bulkReplaceDialogVisible = ref(false)
const bulkReplaceSubmitting = ref(false)
const bulkReplaceForm = reactive({
  matchDate: '',
  matchDateFrom: '',
  matchDateTo: '',
  matchSupplierId: '',
  matchItemName: '',
  newDate: '',
  newSupplierId: '',
})
const bulkReplacePreview = ref<BulkReplacePreviewRow[] | null>(null)
const bulkReplaceMatchedCount = ref<number | null>(null)

function openBulkReplace() {
  bulkReplaceForm.matchDate = ''
  bulkReplaceForm.matchDateFrom = ''
  bulkReplaceForm.matchDateTo = ''
  bulkReplaceForm.matchSupplierId = ''
  bulkReplaceForm.matchItemName = ''
  bulkReplaceForm.newDate = ''
  bulkReplaceForm.newSupplierId = ''
  bulkReplacePreview.value = null
  bulkReplaceMatchedCount.value = null
  bulkReplaceDialogVisible.value = true
}

// Re-preview (never auto-apply) whenever any condition changes, so the
// match count on screen never silently goes stale relative to what
// "confirm" would actually act on.
watch(
  () => Object.values(bulkReplaceForm),
  () => {
    bulkReplacePreview.value = null
    bulkReplaceMatchedCount.value = null
  },
)

function bulkReplaceMatch(): BulkReplaceMatch {
  return {
    date: bulkReplaceForm.matchDate || undefined,
    dateFrom: bulkReplaceForm.matchDateFrom || undefined,
    dateTo: bulkReplaceForm.matchDateTo || undefined,
    supplierId: bulkReplaceForm.matchSupplierId || undefined,
    itemName: bulkReplaceForm.matchItemName || undefined,
  }
}

function bulkReplaceWith(): BulkReplaceWith {
  return { date: bulkReplaceForm.newDate || undefined, supplierId: bulkReplaceForm.newSupplierId || undefined }
}

const bulkReplaceHasMatch = computed(() => Object.values(bulkReplaceMatch()).some(Boolean))
const bulkReplaceHasReplacement = computed(() => Object.values(bulkReplaceWith()).some(Boolean))

async function handleBulkReplacePreview() {
  if (!bulkReplaceHasMatch.value) {
    ElMessage.warning(t('purchasing.bulkReplaceNeedMatch'))
    return
  }
  if (!bulkReplaceHasReplacement.value) {
    ElMessage.warning(t('purchasing.bulkReplaceNeedReplacement'))
    return
  }
  bulkReplaceSubmitting.value = true
  try {
    const result = await bulkReplacePurchases({ match: bulkReplaceMatch(), replace: bulkReplaceWith(), confirm: false })
    if ('preview' in result) {
      bulkReplacePreview.value = result.preview
      bulkReplaceMatchedCount.value = result.matchedCount
    }
  } finally {
    bulkReplaceSubmitting.value = false
  }
}

async function handleBulkReplaceConfirm() {
  bulkReplaceSubmitting.value = true
  try {
    const result = await bulkReplacePurchases({ match: bulkReplaceMatch(), replace: bulkReplaceWith(), confirm: true })
    if ('replacedCount' in result) {
      ElMessage.success(t('purchasing.bulkReplaceSuccess', { count: result.replacedCount }))
      bulkReplaceDialogVisible.value = false
      await refreshSilently()
    }
  } finally {
    bulkReplaceSubmitting.value = false
  }
}

// ---- Price history + cross-supplier comparison drawer --------------------

const historyDrawerVisible = ref(false)
const { loading: historyLoading, run: runHistoryLoad } = useDelayedLoading()
const historyTarget = ref<PurchaseRecord | null>(null)
const historyEntries = ref<PriceHistoryEntry[]>([])
const comparisonEntries = ref<SupplierPriceComparisonEntry[]>([])
// Opening the drawer defaults to just last+this month — enough to see the
// current month-over-month trend at a glance, which is what this is for.
// The full (up to 100-row) history fetched underneath is still right there
// client-side, so "show all" is a free toggle, not a second request.
const showFullHistory = ref(false)

const recentHistoryEntries = computed(() => {
  const [yearStr, monthStr] = todayJst().split('-')
  const year = Number(yearStr)
  const month = Number(monthStr)
  const prevYear = month === 1 ? year - 1 : year
  const prevMonth = month === 1 ? 12 : month - 1
  return historyEntries.value.filter((e) => {
    const [y, m] = e.date.split('-').map(Number)
    return (y === year && m === month) || (y === prevYear && m === prevMonth)
  })
})

const visibleHistoryEntries = computed(() => (
  showFullHistory.value ? historyEntries.value : recentHistoryEntries.value
))

async function openPriceHistory(record: PurchaseRecord) {
  historyTarget.value = record
  historyDrawerVisible.value = true
  showFullHistory.value = false
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
              @compositionend="handleCompositionEnd"
            >
              <template #default="{ item }">
                <div class="suggestion-item">
                  <span>{{ item.itemName }}</span>
                  <span class="suggestion-meta">{{ formatCurrency(item.lastUnitPrice) }}</span>
                </div>
              </template>
            </el-autocomplete>
            <span v-if="isNewItem" class="new-item-hint">
              <el-icon><MagicStick /></el-icon>{{ t('purchasing.newItemHint') }}
            </span>
          </div>
          <el-input
            v-model.number="row.quantity" type="number" class="c-qty"
            :placeholder="t('purchasing.quantity')" @keydown.enter="handleRowEnter"
          />
          <el-input
            v-model.number="row.unitPrice" type="number" class="c-price"
            :placeholder="t('purchasing.unitPrice')" @keydown.enter="handleRowEnter"
          >
            <template #prefix>¥</template>
          </el-input>
          <el-input :model-value="amountPreview" disabled class="c-amount">
            <template #prefix>¥</template>
          </el-input>
          <el-input
            v-model="row.note" class="c-note"
            :placeholder="t('purchasing.note')" @keydown.enter="handleRowEnter"
          />
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
        <el-button v-if="!isAdmin" :icon="Edit" @click="openBulkReplace">{{ t('purchasing.bulkReplace') }}</el-button>
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
            <div v-if="r.priorPurchaseDirection && r.priorPurchaseDeltaAmount !== null" class="price-change-detail" :class="r.priorPurchaseDirection">
              {{ t('purchasing.comparedWithLastPurchase') }}
              {{ r.priorPurchaseDeltaAmount >= 0 ? '+' : '−' }}{{ formatCurrency(Math.round(Math.abs(r.priorPurchaseDeltaAmount))) }}
              <span v-if="r.priorPurchaseDeltaPercent !== null">（{{ r.priorPurchaseDeltaPercent >= 0 ? '+' : '' }}{{ r.priorPurchaseDeltaPercent.toFixed(1) }}%）</span>
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

          <div class="drawer-section-title history-title-row">
            <h4>{{ t('purchasing.priceHistoryTitle') }}</h4>
            <span class="history-scope-toggle" @click="showFullHistory = !showFullHistory">
              {{ showFullHistory ? t('purchasing.priceHistoryShowRecentOnly') : t('purchasing.priceHistoryShowAll') }}
            </span>
          </div>
          <p v-if="!showFullHistory" class="drawer-subject history-scope-hint">{{ t('purchasing.priceHistoryRecentHint') }}</p>
          <el-table :data="visibleHistoryEntries" size="small" :empty-text="t('purchasing.noHistory')">
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

    <el-dialog v-model="bulkReplaceDialogVisible" :title="t('purchasing.bulkReplaceTitle')" width="520px">
      <p class="bulk-replace-hint">{{ t('purchasing.bulkReplaceScopeHint') }}</p>

      <div class="bulk-replace-section-title">{{ t('purchasing.bulkReplaceMatchSection') }}</div>
      <p class="bulk-replace-hint">{{ t('purchasing.bulkReplaceMatchHint') }}</p>
      <div class="bulk-replace-grid">
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceMatchDate') }}</span>
          <el-date-picker v-model="bulkReplaceForm.matchDate" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
        </div>
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceMatchSupplier') }}</span>
          <el-select v-model="bulkReplaceForm.matchSupplierId" :placeholder="t('purchasing.allSuppliers')" clearable style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
        </div>
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceMatchDateFrom') }}</span>
          <el-date-picker v-model="bulkReplaceForm.matchDateFrom" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
        </div>
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceMatchDateTo') }}</span>
          <el-date-picker v-model="bulkReplaceForm.matchDateTo" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
        </div>
        <div class="bulk-replace-field-row bulk-replace-span-2">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceMatchItemName') }}</span>
          <el-input v-model="bulkReplaceForm.matchItemName" :placeholder="t('purchasing.filterItemNamePlaceholder')" clearable />
        </div>
      </div>

      <div class="bulk-replace-section-title">{{ t('purchasing.bulkReplaceReplaceSection') }}</div>
      <div class="bulk-replace-grid">
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceNewDate') }}</span>
          <el-date-picker v-model="bulkReplaceForm.newDate" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
        </div>
        <div class="bulk-replace-field-row">
          <span class="bulk-replace-label">{{ t('purchasing.bulkReplaceNewSupplier') }}</span>
          <el-select v-model="bulkReplaceForm.newSupplierId" :placeholder="t('purchasing.allSuppliers')" clearable style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
        </div>
      </div>

      <el-button :loading="bulkReplaceSubmitting" @click="handleBulkReplacePreview">
        {{ t('purchasing.bulkReplacePreview') }}
      </el-button>

      <div v-if="bulkReplaceMatchedCount !== null" class="bulk-replace-preview">
        <p v-if="bulkReplaceMatchedCount === 0" class="bulk-replace-no-match">{{ t('purchasing.bulkReplaceNoMatch') }}</p>
        <template v-else>
          <p class="bulk-replace-matched-count">{{ t('purchasing.bulkReplaceMatchedCount', { count: bulkReplaceMatchedCount }) }}</p>
          <el-table :data="bulkReplacePreview ?? []" size="small" max-height="220">
            <el-table-column prop="date" :label="t('purchasing.date')" width="100" />
            <el-table-column :label="t('purchasing.supplier')" min-width="100">
              <template #default="{ row: p }">{{ p.supplierName }}</template>
            </el-table-column>
            <el-table-column prop="itemName" :label="t('purchasing.itemName')" min-width="100" />
          </el-table>
        </template>
      </div>

      <template #footer>
        <el-button @click="bulkReplaceDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="bulkReplaceSubmitting"
          :disabled="!bulkReplaceMatchedCount"
          @click="handleBulkReplaceConfirm"
        >
          {{ t('purchasing.bulkReplaceConfirm') }}
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

/* The entry row is a spreadsheet-style single line by design (fast
 * keyboard-driven data entry) — 7 columns of that on a phone-width screen
 * squeezes every field down to an unusable sliver. Below this width it
 * becomes a 2-up grid instead: item name and note (the two free-text,
 * variable-length fields) get their own full-width row, everything else
 * pairs up two per row in DOM order (date+supplier, qty+price, amount is
 * left to pair with note). The column labels above the row are dropped
 * here since they no longer line up with a wrapped grid — each field's
 * own placeholder/label carries that context instead. */
@media (max-width: 640px) {
  .entry-head {
    display: none;
  }

  .entry-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .c-item,
  .c-note {
    grid-column: 1 / -1;
  }
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

.new-item-hint {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--accent);
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

.history-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.history-title-row h4 {
  margin: 0;
  font-size: inherit;
  font-weight: inherit;
  color: inherit;
}

.history-scope-toggle {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--accent);
  cursor: pointer;
  white-space: nowrap;
}

.history-scope-hint {
  margin: -4px 0 10px;
  font-size: 11.5px;
}

.bulk-replace-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0 0 16px;
}

.bulk-replace-section-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 4px 0 4px;
}

.bulk-replace-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.bulk-replace-span-2 {
  grid-column: 1 / -1;
}

.bulk-replace-field-row {
  margin-bottom: 14px;
}

.bulk-replace-label {
  display: block;
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.bulk-replace-preview {
  margin-top: 14px;
}

.bulk-replace-matched-count {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.bulk-replace-no-match {
  font-size: 12.5px;
  color: var(--text-tertiary);
}
</style>
