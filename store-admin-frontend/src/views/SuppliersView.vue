<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Edit, Delete, EditPen, Download, Refresh } from '@element-plus/icons-vue'
import {
  fetchSuppliers,
  createSupplier,
  updateSupplier,
  deleteSupplier,
  setSupplierPayableOverride,
  type Supplier,
} from '@/api/suppliers'
import { useBranchStore } from '@/stores/branches'
import { useAuthStore } from '@/stores/auth'
import { formatCurrency, currentMonthJst, todayJst } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { renderOffscreenToPdf } from '@/utils/pdfExport'

const { t } = useI18n()
const branchStore = useBranchStore()
const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')

const suppliers = ref<Supplier[]>([])
const { loading, run } = useDelayedLoading()
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()

// 口座種類 is a fixed, small set of standard Japanese bank account types —
// a free-text field just invited spelling drift ("普通"/"普通預金"/"ふつう").
const ACCOUNT_TYPE_OPTIONS = ['普通', '当座', '貯蓄'] as const

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
// Defaults to the current month; picking a different one re-fetches that
// month's purchases and switches the payable column to show its total.
const selectedMonth = ref(currentMonth)
const selectedBranchId = ref(auth.branchId ?? '')

function payableFor(supplier: Supplier) {
  return supplier.payableOverride ?? supplier.monthlyPayable
}

function isManual(supplier: Supplier) {
  return supplier.payableOverride !== null
}

function bankSummary(supplier: Supplier) {
  const parts = [supplier.bankName, supplier.branchName, supplier.accountType, supplier.accountNumber].filter(Boolean)
  return parts.length ? parts.join(' ') : '—'
}

async function fetchData() {
  const [supplierList] = await Promise.all([
    fetchSuppliers({ month: selectedMonth.value, branchId: selectedBranchId.value || undefined }),
    branchStore.ensureLoaded(),
  ])
  suppliers.value = supplierList
}

async function load() {
  await run(fetchData)
}

watch(selectedMonth, load)
watch(selectedBranchId, load)

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

function monthTitle(month: string) {
  const [year, monthNum] = month.split('-')
  return `${year}年${Number(monthNum)}月材料費`
}

async function handleDownload() {
  downloading.value = true
  try {
    // Suppliers with nothing owed this month just pad out the sheet.
    const rows = suppliers.value.filter((s) => payableFor(s) !== 0)

    await renderOffscreenToPdf(`供应商-${todayJst()}`, PDF_PAGE_WIDTH_PX, (root) => {
      root.style.padding = '28px 32px'
      root.style.fontFamily = '"Hiragino Sans", "Microsoft YaHei", sans-serif'
      root.style.color = '#1a1a1a'

      const header = el('div', { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '14px' })
      header.appendChild(el('div', { fontSize: '18px', fontWeight: '700' }, monthTitle(selectedMonth.value)))
      header.appendChild(el('div', { fontSize: '11px', color: '#666' }, todayJst()))
      root.appendChild(header)

      const table = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '10px', tableLayout: 'fixed' })
      const columns: [string, string][] = [
        [t('suppliers.name'), '22%'],
        [t('suppliers.contact'), '10%'],
        [t('suppliers.phone'), '13%'],
        [t('suppliers.bankAccount'), '42%'],
        [t('suppliers.monthlyPayable'), '13%'],
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
      rows.forEach((s, index) => {
        const row = document.createElement('tr')
        if (index % 2 === 1) row.style.backgroundColor = '#f7f7f7'
        const cellStyle: Partial<CSSStyleDeclaration> = {
          padding: '4px 6px', borderBottom: '0.5px solid #ddd', verticalAlign: 'top',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }
        row.appendChild(el('td', cellStyle, s.name))
        row.appendChild(el('td', cellStyle, s.contact))
        row.appendChild(el('td', cellStyle, s.phone))

        // The bank's own kana reading sits in its own small line directly
        // above the bank name, the way furigana annotates the kanji it
        // belongs to — not the account holder's reading, which instead
        // goes right after the bank name on the same line (that's whose
        // reading it is: the 口座名義, not the bank's). Overflow handling
        // is set on each line individually (not just the td) so a too-long
        // line truncates on its own instead of pushing the rest out of view.
        const lineStyle: Partial<CSSStyleDeclaration> = {
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }
        const bankCell = el('td', { ...cellStyle, whiteSpace: 'normal' })
        if (s.bankNameFurigana) {
          bankCell.appendChild(el('div', { ...lineStyle, fontSize: '7px', color: '#888', lineHeight: '1.3' }, s.bankNameFurigana))
        }
        const bankNameLine = [s.bankName, s.accountHolderFurigana].filter(Boolean).join(' ')
        const restLine = [s.branchName, s.accountType, s.accountNumber].filter(Boolean).join(' ')
        if (bankNameLine) bankCell.appendChild(el('div', lineStyle, bankNameLine))
        if (restLine) bankCell.appendChild(el('div', lineStyle, restLine))
        if (!bankNameLine && !restLine) bankCell.appendChild(el('div', lineStyle, '—'))
        row.appendChild(bankCell)

        row.appendChild(el('td', { ...cellStyle, textAlign: 'right' }, formatCurrency(payableFor(s))))
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
      inputValue: row.payableOverride !== null ? String(row.payableOverride) : String(row.monthlyPayable),
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
      inputValidator: (value: string) => !value.trim() || (!Number.isNaN(Number(value)) && Number(value) >= 0),
    })
    const trimmed = value.trim()
    await setSupplierPayableOverride(
      row.id, trimmed ? Number(trimmed) : null, selectedMonth.value, selectedBranchId.value || undefined,
    )
    await refreshSilently()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(t('common.saveFailed'))
  }
}

async function handleRestoreAutomatic(row: Supplier) {
  try {
    await setSupplierPayableOverride(row.id, null, selectedMonth.value, selectedBranchId.value || undefined)
    await refreshSilently()
  } catch {
    ElMessage.error(t('common.saveFailed'))
  }
}
</script>

<template>
  <div class="suppliers-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('suppliers.pageTitle') }}</h3>
        <div class="header-actions">
          <el-date-picker
            v-model="selectedMonth" type="month" value-format="YYYY-MM" :clearable="false"
            :placeholder="t('purchasing.filterMonth')"
          />
          <el-select
            v-if="isAdmin" v-model="selectedBranchId" clearable
            :placeholder="t('purchasing.allBranches')" style="width: 150px"
          >
            <el-option
              v-for="branch in branchStore.list" :key="branch.id" :value="branch.id"
              :label="branch.nameJa || branch.nameZh"
            />
          </el-select>
          <el-button :icon="Download" :loading="downloading" @click="handleDownload">{{ t('common.downloadPdf') }}</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreate">{{ t('suppliers.add') }}</el-button>
        </div>
      </div>

      <el-table v-loading="loading" class="desktop-table" :data="suppliers" :empty-text="t('suppliers.empty')">
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
              <el-button
                v-if="isManual(row)" circle text :icon="Refresh" size="small"
                :title="t('suppliers.restoreAutomatic')" @click="handleRestoreAutomatic(row)"
              />
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

      <!-- Narrow-viewport alternative to the table above (toggled purely by
           CSS media query, see .desktop-table/.mobile-cards below) — the
           table's 7 columns get clipped off-screen on a phone with no
           visible scroll affordance, so the numbers that matter (未払金額)
           end up invisible. A stacked card keeps every field readable. -->
      <div v-loading="loading" class="mobile-cards">
        <p v-if="!loading && !suppliers.length" class="empty-hint">{{ t('suppliers.empty') }}</p>
        <div v-for="row in suppliers" :key="row.id" class="supplier-card">
          <div class="supplier-card-head">
            <span class="supplier-card-name">{{ row.name }}</span>
            <span class="supplier-card-actions">
              <el-button circle text :icon="Edit" size="small" @click="openEdit(row)" />
              <el-button circle text :icon="Delete" size="small" @click="handleDelete(row)" />
            </span>
          </div>
          <div class="supplier-card-payable">
            <span class="payable-amount">{{ formatCurrency(payableFor(row)) }}</span>
            <el-tag size="small" :type="isManual(row) ? 'warning' : 'info'" round>
              {{ isManual(row) ? t('suppliers.monthlyPayableManual') : t('suppliers.monthlyPayableAuto') }}
            </el-tag>
            <el-button circle text :icon="EditPen" size="small" @click="handleEditPayable(row)" />
            <el-button
              v-if="isManual(row)" circle text :icon="Refresh" size="small"
              :title="t('suppliers.restoreAutomatic')" @click="handleRestoreAutomatic(row)"
            />
          </div>
          <div class="supplier-card-row">
            <span>{{ t('suppliers.category') }}</span><span>{{ row.category || '—' }}</span>
          </div>
          <div class="supplier-card-row">
            <span>{{ t('suppliers.contact') }}</span><span>{{ row.contact || '—' }}</span>
          </div>
          <div class="supplier-card-row">
            <span>{{ t('suppliers.phone') }}</span><span>{{ row.phone || '—' }}</span>
          </div>
          <div class="supplier-card-row">
            <span>{{ t('suppliers.bankAccount') }}</span><span>{{ bankSummary(row) }}</span>
          </div>
        </div>
      </div>
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
            <el-select v-model="form.accountType" clearable :placeholder="t('suppliers.accountTypePlaceholder')">
              <el-option v-for="opt in ACCOUNT_TYPE_OPTIONS" :key="opt" :value="opt" :label="opt" />
            </el-select>
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
  flex-wrap: wrap;
  gap: 10px;
}

.payable-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mobile-cards {
  display: none;
}

.supplier-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  margin-bottom: 10px;
}

.supplier-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.supplier-card-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.supplier-card-payable {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.supplier-card-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: var(--text-secondary);
  padding: 3px 0;
}

.supplier-card-row span:last-child {
  color: var(--text-primary);
  text-align: right;
  word-break: break-word;
}

.empty-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 20px 0;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .desktop-table {
    display: none;
  }

  .mobile-cards {
    display: block;
  }
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
