<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type InputInstance } from 'element-plus'
import { Plus, Minus, Warning } from '@element-plus/icons-vue'
import { fetchStock, adjustStock, fetchStockTransactions, type Stock, type StockTransaction, type StockTransactionType } from '@/api/inventory'
import { fetchProducts, lookupProductByJan, type Product } from '@/api/products'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { branchDisplayName } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'

const { t, locale } = useI18n()
const auth = useAuthStore()
const branchStore = useBranchStore()

const isAdmin = computed(() => auth.role === 'admin')
const activeTab = ref<'stock' | 'history'>('stock')

const stockList = ref<Stock[]>([])
const transactions = ref<StockTransaction[]>([])
const products = ref<Product[]>([])
const { loading, run } = useDelayedLoading()
const lowStockOnly = ref(false)
const selectedBranchId = ref(isAdmin.value ? '' : (auth.branchId ?? ''))

const adjustDialogVisible = ref(false)
const submitting = ref(false)
const janScanRef = ref<InputInstance>()
const janScanValue = ref('')
const scanFeedback = ref<'found' | 'not-found' | null>(null)

const adjustForm = reactive({
  branchId: '',
  productId: '',
  transactionType: 'adjustment_in' as StockTransactionType,
  quantity: 1,
  note: '',
})

function branchName(branchId: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === branchId), locale.value, branchId)
}

function productLabel(productId: string) {
  const p = products.value.find((x) => x.id === productId)
  return p ? `${p.name}${p.janCode ? ` (${p.janCode})` : ''}` : productId
}

async function fetchData() {
  const [stock, txns, productList] = await Promise.all([
    fetchStock({ branchId: selectedBranchId.value || undefined, lowStockOnly: lowStockOnly.value }),
    fetchStockTransactions(selectedBranchId.value || undefined),
    fetchProducts(),
    branchStore.ensureLoaded(),
  ])
  stockList.value = stock
  transactions.value = txns
  products.value = productList
}

async function load() {
  await run(fetchData)
}

async function refreshSilently() {
  await fetchData()
}

watch([selectedBranchId, lowStockOnly], load)
onMounted(load)

function openAdjustDialog(type: 'in' | 'out', row?: Stock) {
  // The dialog itself carries the branch: `selectedBranchId` is only the
  // page-level *filter* and is often blank ("全部分店") for admins, which
  // the backend rejects for a write — so this always needs an explicit
  // value, pre-filled from the row/filter/own-branch where available.
  adjustForm.branchId = row?.branchId || selectedBranchId.value || auth.branchId || ''
  adjustForm.productId = row?.productId ?? ''
  adjustForm.transactionType = type === 'in' ? 'adjustment_in' : 'adjustment_out'
  adjustForm.quantity = 1
  adjustForm.note = ''
  janScanValue.value = ''
  scanFeedback.value = null
  adjustDialogVisible.value = true
  nextTick(() => janScanRef.value?.focus())
}

// Barcode scanners behave as keyboard-wedge devices: they "type" the
// digits into whatever input is focused, then send Enter. This handler is
// the entire "scanning" implementation — no hardware API involved.
async function handleJanScan() {
  const jan = janScanValue.value.trim()
  if (!jan) return
  const product = await lookupProductByJan(jan)
  if (product) {
    adjustForm.productId = product.id
    scanFeedback.value = 'found'
  } else {
    scanFeedback.value = 'not-found'
  }
  janScanValue.value = ''
}

async function handleAdjustSubmit() {
  if (isAdmin.value && !adjustForm.branchId) {
    ElMessage.warning(t('inventory.selectBranchFirst'))
    return
  }
  if (!adjustForm.productId) {
    ElMessage.warning(t('inventory.selectProductFirst'))
    return
  }
  submitting.value = true
  try {
    await adjustStock({
      branchId: adjustForm.branchId || undefined,
      productId: adjustForm.productId,
      transactionType: adjustForm.transactionType,
      quantity: adjustForm.quantity,
      note: adjustForm.note,
    })
    ElMessage.success(t('common.savedSuccess'))
    adjustDialogVisible.value = false
    await refreshSilently()
  } catch (e) {
    const message = (e as { messages?: () => string[] })?.messages?.()?.join(', ')
    ElMessage.error(message || t('inventory.adjustFailed'))
  } finally {
    submitting.value = false
  }
}

function transactionLabel(type: StockTransactionType) {
  return t(`inventory.transactionType.${type}`)
}
</script>

<template>
  <div class="inventory-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('inventory.pageTitle') }}</h3>
        <div class="header-actions">
          <el-select
            v-if="isAdmin"
            v-model="selectedBranchId"
            clearable
            :placeholder="t('inventory.allBranches')"
            class="branch-select"
          >
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
          <el-button :icon="Plus" @click="openAdjustDialog('in')">{{ t('inventory.stockIn') }}</el-button>
          <el-button :icon="Minus" @click="openAdjustDialog('out')">{{ t('inventory.stockOut') }}</el-button>
        </div>
      </div>

      <el-tabs v-model="activeTab">
        <el-tab-pane :label="t('inventory.stockTab')" name="stock">
          <div class="filter-row">
            <el-checkbox v-model="lowStockOnly">{{ t('inventory.lowStockOnly') }}</el-checkbox>
          </div>
          <el-table :data="stockList" v-loading="loading" :empty-text="t('inventory.empty')">
            <el-table-column v-if="isAdmin && !selectedBranchId" :label="t('inventory.branch')" width="110">
              <template #default="{ row }">{{ branchName(row.branchId) }}</template>
            </el-table-column>
            <el-table-column prop="janCode" :label="t('products.janCode')" width="140" />
            <el-table-column prop="productName" :label="t('products.name')" min-width="150" />
            <el-table-column prop="category" :label="t('products.category')" width="100" />
            <el-table-column :label="t('inventory.quantity')" width="120">
              <template #default="{ row }">
                <span :class="{ 'low-stock': row.isLowStock }">
                  <el-icon v-if="row.isLowStock"><Warning /></el-icon>
                  {{ row.quantity }} {{ row.unit }}
                </span>
              </template>
            </el-table-column>
            <el-table-column :label="t('products.lowStockThreshold')" width="110">
              <template #default="{ row }">{{ row.lowStockThreshold ?? '—' }}</template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="130">
              <template #default="{ row }">
                <el-button circle text :icon="Plus" size="small" @click="openAdjustDialog('in', row)" />
                <el-button circle text :icon="Minus" size="small" @click="openAdjustDialog('out', row)" />
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="t('inventory.historyTab')" name="history">
          <el-table :data="transactions" v-loading="loading" :empty-text="t('inventory.empty')">
            <el-table-column prop="createdAt" :label="t('inventory.time')" width="170">
              <template #default="{ row }">{{ new Date(row.createdAt).toLocaleString('ja-JP') }}</template>
            </el-table-column>
            <el-table-column v-if="isAdmin && !selectedBranchId" :label="t('inventory.branch')" width="110">
              <template #default="{ row }">{{ branchName(row.branchId) }}</template>
            </el-table-column>
            <el-table-column prop="productName" :label="t('products.name')" min-width="150" />
            <el-table-column :label="t('inventory.transactionTypeLabel')" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.transactionType.endsWith('_in') ? 'success' : 'danger'">
                  {{ transactionLabel(row.transactionType) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="quantity" :label="t('inventory.quantity')" width="90" />
            <el-table-column prop="note" :label="t('inventory.note')" min-width="150" show-overflow-tooltip />
            <el-table-column prop="operatorName" :label="t('inventory.operator')" width="110" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog
      v-model="adjustDialogVisible"
      :title="adjustForm.transactionType.endsWith('_in') ? t('inventory.stockIn') : t('inventory.stockOut')"
      width="440px"
    >
      <el-form label-position="top">
        <el-form-item v-if="isAdmin" :label="t('inventory.branch')">
          <el-select v-model="adjustForm.branchId" style="width: 100%" :placeholder="t('inventory.selectBranchFirst')">
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('inventory.scanOrEnterJan')">
          <el-input
            ref="janScanRef"
            v-model="janScanValue"
            :placeholder="t('inventory.scanPlaceholder')"
            @keyup.enter="handleJanScan"
          />
          <div v-if="scanFeedback === 'found'" class="scan-feedback found">{{ t('inventory.scanFound') }}</div>
          <div v-if="scanFeedback === 'not-found'" class="scan-feedback not-found">{{ t('inventory.scanNotFound') }}</div>
        </el-form-item>
        <el-form-item :label="t('products.name')">
          <el-select v-model="adjustForm.productId" filterable style="width: 100%" :placeholder="t('inventory.selectProduct')">
            <el-option v-for="p in products" :key="p.id" :value="p.id" :label="productLabel(p.id)" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('inventory.direction')">
          <el-radio-group v-model="adjustForm.transactionType">
            <el-radio-button value="adjustment_in">{{ t('inventory.stockIn') }}</el-radio-button>
            <el-radio-button value="adjustment_out">{{ t('inventory.stockOut') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('inventory.quantity')">
          <el-input-number v-model="adjustForm.quantity" :min="0.01" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('inventory.note')">
          <el-input v-model="adjustForm.note" :placeholder="t('inventory.notePlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleAdjustSubmit">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.page-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.branch-select {
  width: 160px;
}

.filter-row {
  margin-bottom: 12px;
}

.low-stock {
  color: var(--danger);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.scan-feedback {
  font-size: 12px;
  margin-top: 4px;
}

.scan-feedback.found {
  color: var(--success);
}

.scan-feedback.not-found {
  color: var(--danger);
}
</style>
