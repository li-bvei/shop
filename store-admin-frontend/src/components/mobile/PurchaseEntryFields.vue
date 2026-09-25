<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchPurchaseItemSuggestions, type PurchaseItemSuggestion } from '@/api/purchasing'
import type { Supplier } from '@/api/suppliers'
import { purchaseAmountPreview, type PurchaseEntryRow } from '@/utils/purchaseEntry'
import { formatCurrency } from '@/utils/format'
import MobileNumberInput from '@/components/mobile/MobileNumberInput.vue'

/** The vertical purchase fields, used both for the always-open "new record"
 * form and inside the edit drawer. Every field has a real <label>; item-name
 * suggestions are an always-visible tappable list (not a floating dropdown
 * that a thumb or the keyboard would cover). */
const row = defineModel<PurchaseEntryRow>('row', { required: true })
defineProps<{ suppliers: Supplier[] }>()
const { t } = useI18n()
const uid = useId()

const amount = computed(() => purchaseAmountPreview(row.value))

// ---- item-name suggestions (same source + same "is this a new item" rule as desktop) ----
const suggestions = ref<PurchaseItemSuggestion[]>([])
const knownItemNames = ref<Set<string>>(new Set())
const itemInput = ref<HTMLInputElement>()
let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0

async function loadSuggestions(query: string) {
  const mine = ++seq
  if (!row.value.supplierId) { suggestions.value = []; return }
  const results = await fetchPurchaseItemSuggestions(row.value.supplierId, query, row.value.branchId)
  if (mine !== seq) return
  suggestions.value = results.slice(0, 6)
  if (!query) knownItemNames.value = new Set(results.map((r) => r.itemName))
}
watch(() => row.value.supplierId, () => {
  suggestions.value = []
  knownItemNames.value = new Set()
  void loadSuggestions('')
}, { immediate: true })
watch(() => row.value.itemName, (name) => {
  clearTimeout(timer)
  timer = setTimeout(() => { void loadSuggestions(name.trim()) }, 250)
})
onBeforeUnmount(() => clearTimeout(timer))

const isNewItem = computed(() => {
  const name = row.value.itemName.trim()
  return !!row.value.supplierId && !!name && !knownItemNames.value.has(name)
})
const visibleSuggestions = computed(() => suggestions.value.filter((s) => s.itemName !== row.value.itemName.trim()))

function pick(s: PurchaseItemSuggestion) {
  row.value.itemName = s.itemName
  row.value.unitPrice = s.lastUnitPrice
  suggestions.value = []
}
function noteAdded(name: string) {
  knownItemNames.value = new Set([...knownItemNames.value, name])
}
defineExpose({ focusItemName: () => itemInput.value?.focus(), noteAdded, isNewItem })
</script>

<template>
  <div class="pef">
    <div class="pef-field">
      <label class="pef-label" :for="`${uid}-date`">{{ t('purchasing.date') }}</label>
      <input :id="`${uid}-date`" v-model="row.date" class="pef-input" type="date">
    </div>
    <div class="pef-field">
      <label class="pef-label" :for="`${uid}-supplier`">{{ t('purchasing.supplier') }}</label>
      <select :id="`${uid}-supplier`" v-model="row.supplierId" class="pef-input">
        <option value="">{{ t('purchasing.supplierPlaceholder') }}</option>
        <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </div>
    <div class="pef-field">
      <label class="pef-label" :for="`${uid}-item`">{{ t('purchasing.itemName') }}</label>
      <input
        :id="`${uid}-item`" ref="itemInput" v-model="row.itemName" class="pef-input" type="text" autocomplete="off"
        autocapitalize="off" enterkeyhint="next"
      >
      <p v-if="isNewItem" class="pef-hint">{{ t('purchasing.newItemHint') }}</p>
      <div v-if="visibleSuggestions.length" class="pef-suggest" role="group" :aria-label="t('purchasing.mSuggestions')">
        <button v-for="s in visibleSuggestions" :key="s.itemName" type="button" class="pef-suggest-btn" @click="pick(s)">
          <span class="pef-suggest-name">{{ s.itemName }}</span>
          <span class="pef-suggest-price">{{ t('purchasing.mLastPrice', { price: formatCurrency(s.lastUnitPrice) }) }}</span>
        </button>
      </div>
    </div>
    <MobileNumberInput v-model="row.quantity" :label="t('purchasing.quantity')" decimal />
    <MobileNumberInput v-model="row.unitPrice" :label="t('purchasing.unitPrice')" prefix="¥" />
    <div class="pef-amount">
      <span>{{ t('purchasing.amountAuto') }}</span>
      <strong>{{ formatCurrency(amount) }}</strong>
    </div>
    <div class="pef-field">
      <label class="pef-label" :for="`${uid}-note`">{{ t('purchasing.note') }}</label>
      <input :id="`${uid}-note`" v-model="row.note" class="pef-input" type="text" autocomplete="off">
    </div>
  </div>
</template>

<style scoped>
.pef { display: flex; flex-direction: column; gap: 16px; font-size: 16px; color: var(--text-primary); }
.pef-field { display: flex; flex-direction: column; gap: 6px; }
.pef-label { font-size: 16px; font-weight: 700; }
.pef-input {
  width: 100%; box-sizing: border-box; min-height: 56px; padding: 0 14px; font: inherit; font-size: 18px; color: var(--text-primary);
  background: var(--surface); border: 2px solid var(--border-strong, #c9cdd1); border-radius: 12px; outline: 0;
}
.pef-input:focus { border-color: var(--accent); }
.pef-hint { margin: 0; font-size: 16px; font-weight: 700; color: var(--warning); }
.pef-suggest { display: flex; flex-direction: column; gap: 6px; }
.pef-suggest-btn {
  min-height: 52px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 14px; text-align: left;
  font: inherit; font-size: 16px; color: var(--text-primary); background: var(--accent-light); border: 2px solid var(--accent); border-radius: 12px; cursor: pointer;
}
.pef-suggest-name { font-weight: 700; overflow: hidden; text-overflow: ellipsis; }
.pef-suggest-price { font-size: 16px; color: var(--text-secondary); white-space: nowrap; }
.pef-amount { display: flex; align-items: baseline; justify-content: space-between; padding: 12px 14px; background: var(--surface-alt); border-radius: 12px; font-size: 17px; }
.pef-amount strong { font-size: 22px; }
</style>
