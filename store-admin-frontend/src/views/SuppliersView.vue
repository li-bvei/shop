<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Edit, Delete, EditPen, Download } from '@element-plus/icons-vue'
import {
  fetchSuppliers,
  createSupplier,
  updateSupplier,
  deleteSupplier,
  setSupplierPayableOverride,
  type Supplier,
} from '@/api/suppliers'
import { fetchAllPurchases, type PurchaseRecord } from '@/api/purchasing'
import { useBranchStore } from '@/stores/branches'
import { formatCurrency, currentMonthJst, todayJst } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { renderOffscreenToPdf } from '@/utils/pdfExport'

const { t } = useI18n()
const branchStore = useBranchStore()

const suppliers = ref<Supplier[]>([])
const purchases = ref<PurchaseRecord[]>([])
const { loading, run } = useDelayedLoading()
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  category: '',
  contact: '',
  phone: '',
  address: '',
  bankName: '',
  bankNameFurigana: '',
  branchName: '',
  branchNameFurigana: '',
  accountType: '',
  accountNumber: '',
  accountHolderFurigana: '',
  note: '',
})

const rules: FormRules = {
  name: [{ required: true, message: t('suppliers.validateName'), trigger: 'blur' }],
}

const currentMonth = currentMonthJst()

const autoPayableBySupplier = computed(() => {
  const totals = new Map<string, number>()
  for (const purchase of purchases.value) {
    if (!purchase.date.startsWith(currentMonth)) continue
    totals.set(purchase.supplierId, (totals.get(purchase.supplierId) ?? 0) + purchase.amount)
  }
  return totals
})

function payableFor(supplier: Supplier) {
  return supplier.payableOverride ?? autoPayableBySupplier.value.get(supplier.id) ?? 0
}

function isManual(supplier: Supplier) {
  return supplier.payableOverride !== null
}

function bankSummary(supplier: Supplier) {
  const parts = [supplier.bankName, supplier.branchName, supplier.accountType, supplier.accountNumber].filter(Boolean)
  return parts.length ? parts.join(' ') : '—'
}

async function fetchData() {
  const [supplierList, purchaseList] = await Promise.all([
    fetchSuppliers(),
    fetchAllPurchases({ month: currentMonth }),
    branchStore.ensureLoaded(),
  ])
  suppliers.value = supplierList
  purchases.value = purchaseList
}

async function load() {
  await run(fetchData)
}

// After a single row's create/update/delete/payable edit the user just
// closed a dialog or clicked one icon — a full-table loading mask on top of
// that reads as flicker, not feedback, so these refreshes stay silent.
async function refreshSilently() {
  await fetchData()
}

const downloading = ref(false)

// A4 at 96dpi is ~794px wide; rendering the offscreen node at that width
// (scaled up 2x by html2canvas itself for crispness) keeps 1px in this
// layout roughly equal to 1px on the printed page, so font/row sizing
// below can be reasoned about directly in page terms.
const PDF_PAGE_WIDTH_PX = 794

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  styles: Partial<CSSStyleDeclaration>,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  Object.assign(node.style, styles)
  if (text !== undefined) node.textContent = text
  return node
}

async function handleDownload() {
  downloading.value = true
  try {
    await renderOffscreenToPdf(`供应商-${todayJst()}`, PDF_PAGE_WIDTH_PX, (root) => {
      root.style.padding = '28px 32px'
      root.style.fontFamily = '"Hiragino Sans", "Microsoft YaHei", sans-serif'
      root.style.color = '#1a1a1a'

      const header = el('div', { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '14px' })
      header.appendChild(el('div', { fontSize: '18px', fontWeight: '700' }, t('suppliers.pageTitle')))
      header.appendChild(el('div', { fontSize: '11px', color: '#666' }, todayJst()))
      root.appendChild(header)

      const table = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '10px' })
      const columns: [string, string][] = [
        [t('suppliers.name'), '26%'],
        [t('suppliers.category'), '9%'],
        [t('suppliers.contact'), '9%'],
        [t('suppliers.phone'), '11%'],
        [t('suppliers.bankAccount'), '24%'],
        [t('suppliers.accountHolderFurigana'), '13%'],
        [t('suppliers.monthlyPayable'), '8%'],
      ]

      const thead = document.createElement('thead')
      const headRow = document.createElement('tr')
      for (const [label, width] of columns) {
        const isAmount = label === t('suppliers.monthlyPayable')
        headRow.appendChild(el('th', {
          width, textAlign: isAmount ? 'right' : 'left', padding: '5px 6px',
          borderBottom: '1.5px solid #333', fontWeight: '700', whiteSpace: 'nowrap',
        }, label))
      }
      thead.appendChild(headRow)
      table.appendChild(thead)

      const tbody = document.createElement('tbody')
      suppliers.value.forEach((s, index) => {
        const row = document.createElement('tr')
        if (index % 2 === 1) row.style.backgroundColor = '#f7f7f7'
        const cellStyle: Partial<CSSStyleDeclaration> = {
          padding: '4px 6px', borderBottom: '0.5px solid #ddd', verticalAlign: 'top', wordBreak: 'break-word',
        }
        row.appendChild(el('td', cellStyle, s.name))
        row.appendChild(el('td', cellStyle, s.category))
        row.appendChild(el('td', cellStyle, s.contact))
        row.appendChild(el('td', cellStyle, s.phone))
        row.appendChild(el('td', cellStyle, bankSummary(s)))
        row.appendChild(el('td', cellStyle, s.accountHolderFurigana))
        row.appendChild(el('td', { ...cellStyle, textAlign: 'right', whiteSpace: 'nowrap' }, formatCurrency(payableFor(s))))
        tbody.appendChild(row)
      })
      table.appendChild(tbody)
      root.appendChild(table)
    })
  } finally {
    downloading.value = false
  }
}

onMounted(load)

function resetForm() {
  form.name = ''
  form.category = ''
  form.contact = ''
  form.phone = ''
  form.address = ''
  form.bankName = ''
  form.bankNameFurigana = ''
  form.branchName = ''
  form.branchNameFurigana = ''
  form.accountType = ''
  form.accountNumber = ''
  form.accountHolderFurigana = ''
  form.note = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: Supplier) {
  editingId.value = row.id
  form.name = row.name
  form.category = row.category
  form.contact = row.contact
  form.phone = row.phone
  form.address = row.address
  form.bankName = row.bankName
  form.bankNameFurigana = row.bankNameFurigana
  form.branchName = row.branchName
  form.branchNameFurigana = row.branchNameFurigana
  form.accountType = row.accountType
  form.accountNumber = row.accountNumber
  form.accountHolderFurigana = row.accountHolderFurigana
  form.note = row.note
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      if (editingId.value) {
        const existing = suppliers.value.find((s) => s.id === editingId.value)
        await updateSupplier(editingId.value, { ...form, payableOverride: existing?.payableOverride ?? null })
      } else {
        await createSupplier({ ...form, payableOverride: null })
      }
      ElMessage.success(t('common.savedSuccess'))
      dialogVisible.value = false
      await refreshSilently()
    } finally {
      submitting.value = false
    }
  })
}

async function handleDelete(row: Supplier) {
  try {
    await ElMessageBox.confirm(t('suppliers.deleteConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deleteSupplier(row.id)
    ElMessage.success(t('common.deletedSuccess'))
    await refreshSilently()
  } catch {
    // cancelled
  }
}

async function handleEditPayable(row: Supplier) {
  try {
    const { value } = await ElMessageBox.prompt(t('suppliers.payableOverridePlaceholder'), t('suppliers.editPayable'), {
      inputValue: row.payableOverride !== null ? String(row.payableOverride) : '',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      inputValidator: (value: string) => !value.trim() || !Number.isNaN(Number(value)),
    })
    const trimmed = value.trim()
    await setSupplierPayableOverride(row.id, trimmed ? Number(trimmed) : null)
    await refreshSilently()
  } catch {
    // cancelled
  }
}
</script>

<template>
  <div class="suppliers-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('suppliers.pageTitle') }}</h3>
        <div class="header-actions">
          <el-button :icon="Download" :loading="downloading" @click="handleDownload">{{ t('common.downloadPdf') }}</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreate">{{ t('suppliers.add') }}</el-button>
        </div>
      </div>

      <el-table :data="suppliers" v-loading="loading" :empty-text="t('suppliers.empty')">
        <el-table-column prop="name" :label="t('suppliers.name')" min-width="150" />
        <el-table-column prop="category" :label="t('suppliers.category')" width="90" />
        <el-table-column prop="contact" :label="t('suppliers.contact')" width="110" />
        <el-table-column prop="phone" :label="t('suppliers.phone')" width="130" />
        <el-table-column :label="t('suppliers.bankAccount')" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ bankSummary(row) }}</template>
        </el-table-column>
        <el-table-column :label="t('suppliers.monthlyPayable')" width="180">
          <template #default="{ row }">
            <div class="payable-cell">
              <span class="payable-amount">{{ formatCurrency(payableFor(row)) }}</span>
              <el-tag size="small" :type="isManual(row) ? 'warning' : 'info'" round>
                {{ isManual(row) ? t('suppliers.monthlyPayableManual') : t('suppliers.monthlyPayableAuto') }}
              </el-tag>
              <el-button circle text :icon="EditPen" size="small" @click="handleEditPayable(row)" />
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="110">
          <template #default="{ row }">
            <el-button circle text :icon="Edit" size="small" @click="openEdit(row)" />
            <el-button circle text :icon="Delete" size="small" @click="handleDelete(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? t('suppliers.edit') : t('suppliers.add')"
      width="480px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item :label="t('suppliers.name')" prop="name">
          <el-input v-model="form.name" :placeholder="t('suppliers.namePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('suppliers.category')">
          <el-input v-model="form.category" :placeholder="t('suppliers.categoryPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('suppliers.contact')">
          <el-input v-model="form.contact" />
        </el-form-item>
        <el-form-item :label="t('suppliers.phone')" prop="phone">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item :label="t('suppliers.address')">
          <el-input v-model="form.address" />
        </el-form-item>
        <div class="field-pair">
          <el-form-item :label="t('suppliers.bankName')">
            <el-input v-model="form.bankName" :placeholder="t('suppliers.bankNamePlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('suppliers.bankNameFurigana')">
            <el-input v-model="form.bankNameFurigana" :placeholder="t('suppliers.bankNameFuriganaPlaceholder')" />
          </el-form-item>
        </div>
        <div class="field-pair">
          <el-form-item :label="t('suppliers.branchName')">
            <el-input v-model="form.branchName" :placeholder="t('suppliers.branchNamePlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('suppliers.branchNameFurigana')">
            <el-input v-model="form.branchNameFurigana" :placeholder="t('suppliers.branchNameFuriganaPlaceholder')" />
          </el-form-item>
        </div>
        <div class="field-pair">
          <el-form-item :label="t('suppliers.accountType')">
            <el-input v-model="form.accountType" :placeholder="t('suppliers.accountTypePlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('suppliers.accountNumber')">
            <el-input v-model="form.accountNumber" />
          </el-form-item>
        </div>
        <el-form-item :label="t('suppliers.accountHolderFurigana')">
          <el-input v-model="form.accountHolderFurigana" :placeholder="t('suppliers.accountHolderFuriganaPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('suppliers.note')">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
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

.payable-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.field-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 12px;
}

@media (max-width: 480px) {
  .field-pair {
    grid-template-columns: 1fr;
    gap: 0;
  }
}

.payable-amount {
  font-weight: 600;
  color: var(--text-primary);
}
</style>
