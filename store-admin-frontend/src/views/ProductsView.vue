<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules, type InputInstance } from 'element-plus'
import { Plus, Edit, Delete, Search } from '@element-plus/icons-vue'
import {
  fetchProducts,
  createProduct,
  updateProduct,
  deleteProduct,
  type Product,
} from '@/api/products'
import { formatCurrency } from '@/utils/format'
import { useDelayedLoading } from '@/composables/useDelayedLoading'

const { t } = useI18n()

const products = ref<Product[]>([])
const keyword = ref('')
const { loading, run } = useDelayedLoading()
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()
// The JAN input auto-focuses on dialog open so a barcode scanner (which
// behaves as a keyboard typing digits + Enter) can fill it immediately —
// scanning an existing code while creating flags the duplicate up front
// instead of failing only on submit.
const janInputRef = ref<InputInstance>()

const form = reactive({
  janCode: '',
  name: '',
  category: '',
  unit: '个',
  sellingPrice: 0,
  costPrice: null as number | null,
  lowStockThreshold: null as number | null,
  status: 'active' as 'active' | 'inactive',
  note: '',
})

const rules: FormRules = {
  name: [{ required: true, message: t('products.validateName'), trigger: 'blur' }],
}

async function fetchData() {
  products.value = await fetchProducts(keyword.value)
}

async function load() {
  await run(fetchData)
}

async function refreshSilently() {
  await fetchData()
}

let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(load, 300)
})

onMounted(load)

function resetForm() {
  form.janCode = ''
  form.name = ''
  form.category = ''
  form.unit = '个'
  form.sellingPrice = 0
  form.costPrice = null
  form.lowStockThreshold = null
  form.status = 'active'
  form.note = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
  requestAnimationFrame(() => janInputRef.value?.focus())
}

function openEdit(row: Product) {
  editingId.value = row.id
  form.janCode = row.janCode
  form.name = row.name
  form.category = row.category
  form.unit = row.unit
  form.sellingPrice = row.sellingPrice
  form.costPrice = row.costPrice
  form.lowStockThreshold = row.lowStockThreshold
  form.status = row.status
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
        await updateProduct(editingId.value, { ...form })
      } else {
        await createProduct({ ...form })
      }
      ElMessage.success(t('common.savedSuccess'))
      dialogVisible.value = false
      await refreshSilently()
    } finally {
      submitting.value = false
    }
  })
}

async function handleDelete(row: Product) {
  try {
    await ElMessageBox.confirm(t('products.deleteConfirm'), t('common.confirm'), {
      type: 'warning',
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel'),
    })
    await deleteProduct(row.id)
    ElMessage.success(t('common.deletedSuccess'))
    await refreshSilently()
  } catch {
    // cancelled
  }
}
</script>

<template>
  <div class="products-view">
    <div class="card">
      <div class="page-header">
        <h3>{{ t('products.pageTitle') }}</h3>
        <div class="header-actions">
          <el-input
            v-model="keyword"
            :prefix-icon="Search"
            :placeholder="t('products.searchPlaceholder')"
            class="search-input"
            clearable
          />
          <el-button type="primary" :icon="Plus" @click="openCreate">{{ t('products.add') }}</el-button>
        </div>
      </div>

      <el-table :data="products" v-loading="loading" :empty-text="t('products.empty')">
        <el-table-column prop="janCode" :label="t('products.janCode')" width="150" />
        <el-table-column prop="name" :label="t('products.name')" min-width="160" />
        <el-table-column prop="category" :label="t('products.category')" width="110" />
        <el-table-column prop="unit" :label="t('products.unit')" width="80" />
        <el-table-column :label="t('products.sellingPrice')" width="110">
          <template #default="{ row }">{{ formatCurrency(row.sellingPrice) }}</template>
        </el-table-column>
        <el-table-column :label="t('products.lowStockThreshold')" width="110">
          <template #default="{ row }">{{ row.lowStockThreshold ?? '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('products.status')" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
              {{ row.status === 'active' ? t('products.statusActive') : t('products.statusInactive') }}
            </el-tag>
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
      :title="editingId ? t('products.edit') : t('products.add')"
      width="480px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item :label="t('products.janCode')">
          <el-input ref="janInputRef" v-model="form.janCode" :placeholder="t('products.janCodePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('products.name')" prop="name">
          <el-input v-model="form.name" :placeholder="t('products.namePlaceholder')" />
        </el-form-item>
        <div class="field-pair">
          <el-form-item :label="t('products.category')">
            <el-input v-model="form.category" :placeholder="t('products.categoryPlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('products.unit')">
            <el-input v-model="form.unit" />
          </el-form-item>
        </div>
        <div class="field-pair">
          <el-form-item :label="t('products.sellingPrice')">
            <el-input-number v-model="form.sellingPrice" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('products.costPrice')">
            <el-input-number v-model="form.costPrice" :min="0" style="width: 100%" />
          </el-form-item>
        </div>
        <div class="field-pair">
          <el-form-item :label="t('products.lowStockThreshold')">
            <el-input-number v-model="form.lowStockThreshold" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('products.status')">
            <el-select v-model="form.status" style="width: 100%">
              <el-option value="active" :label="t('products.statusActive')" />
              <el-option value="inactive" :label="t('products.statusInactive')" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item :label="t('common.note')">
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

.search-input {
  width: 220px;
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
</style>
