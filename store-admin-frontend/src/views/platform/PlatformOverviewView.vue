<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { fetchPlatformOverview, type PlatformOverview } from '@/api/platform'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { formatCurrency, formatNumber } from '@/utils/format'

const { t, locale } = useI18n()
const router = useRouter()
const { loading, run } = useDelayedLoading()
const data = ref<PlatformOverview | null>(null)

function orgName(o: { name_zh: string; name_ja: string }) {
  return locale.value === 'ja' ? o.name_ja : o.name_zh
}

const totalCards = computed(() => {
  const tt = data.value?.totals
  if (!tt) return []
  return [
    { label: t('platformOverview.orgs'), value: formatNumber(tt.organizations) },
    { label: t('platformOverview.branches'), value: formatNumber(tt.branches) },
    { label: t('platformOverview.accounts'), value: `${formatNumber(tt.active_accounts)} / ${formatNumber(tt.accounts)}` },
    { label: t('platformOverview.monthRevenue'), value: formatCurrency(Number(tt.month_revenue)), delta: tt.month_revenue_delta_pct },
    { label: t('platformOverview.monthCustomers'), value: formatNumber(tt.month_customers) },
    { label: t('platformOverview.loyaltyCustomers'), value: formatNumber(tt.loyalty_customers) },
  ]
})

async function load() {
  await run(async () => {
    data.value = await fetchPlatformOverview()
  })
}

onMounted(load)
</script>

<template>
  <div class="platform-overview" v-loading="loading">
    <div class="head">
      <div>
        <h2>{{ t('platformOverview.title') }}</h2>
        <p class="sub">{{ t('platformOverview.subtitle', { month: data?.month ?? '' }) }}</p>
      </div>
      <el-button type="primary" plain @click="router.push({ name: 'platform-manage' })">
        {{ t('platformOverview.toManage') }}
      </el-button>
    </div>

    <div class="totals">
      <div v-for="c in totalCards" :key="c.label" class="total-card">
        <div class="label">{{ c.label }}</div>
        <div class="value">{{ c.value }}</div>
        <div
          v-if="c.delta !== undefined && c.delta !== null"
          class="delta"
          :class="c.delta >= 0 ? 'up' : 'down'"
        >
          {{ c.delta >= 0 ? '↑' : '↓' }} {{ Math.abs(c.delta) }}% {{ t('platformOverview.vsLastMonth') }}
        </div>
      </div>
    </div>

    <div class="card">
      <h3>{{ t('platformOverview.byOrg') }}</h3>
      <div class="table-scroll">
        <el-table :data="data?.organizations ?? []" class="org-table">
          <el-table-column :label="t('platformOverview.org')" min-width="160">
            <template #default="{ row }">
              <span class="org-cell">{{ orgName(row) }}</span>
              <span class="org-code">{{ row.code }}</span>
              <el-tag v-if="!row.active" size="small" type="info" round>{{ t('platformOverview.inactive') }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.branches')" width="80" align="center" prop="branch_count" />
          <el-table-column :label="t('platformOverview.accountsCol')" width="100" align="center">
            <template #default="{ row }">{{ row.accounts.active }} / {{ row.accounts.total }}</template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.modules')" width="150">
            <template #default="{ row }">
              {{ row.features_enabled }} / {{ row.features_total }}
              <span v-if="row.disabled_features.length" class="disabled-hint">
                （{{ row.disabled_features.map((f: string) => t('featureUnavailable.modules.' + f)).join('、') }} {{ t('platformOverview.off') }}）
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.monthRevenue')" min-width="130" align="right">
            <template #default="{ row }">
              {{ formatCurrency(Number(row.month_revenue)) }}
              <span
                v-if="row.month_revenue_delta_pct !== null"
                class="delta-inline"
                :class="row.month_revenue_delta_pct >= 0 ? 'up' : 'down'"
              >{{ row.month_revenue_delta_pct >= 0 ? '↑' : '↓' }}{{ Math.abs(row.month_revenue_delta_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.monthCustomers')" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.month_customers) }}</template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.monthPurchasing')" min-width="110" align="right">
            <template #default="{ row }">{{ formatCurrency(Number(row.month_purchasing)) }}</template>
          </el-table-column>
          <el-table-column :label="t('platformOverview.loyalty')" width="120" align="right">
            <template #default="{ row }">
              {{ formatNumber(row.loyalty_customers) }}
              <span class="disabled-hint">· {{ t('platformOverview.campaigns', { n: row.active_campaigns }) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

.head h2 {
  font-size: 17px;
  margin: 0 0 4px;
  color: var(--text-primary);
}

.sub {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin: 0;
}

.totals {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.total-card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  box-shadow: var(--shadow-soft);
}

.total-card .label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.total-card .value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.total-card .delta,
.delta-inline {
  font-size: 11.5px;
  font-weight: 600;
}

.total-card .delta {
  margin-top: 4px;
}

.delta-inline {
  margin-left: 4px;
}

.up {
  color: var(--success);
}

.down {
  color: var(--danger);
}

.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 18px 20px;
  box-shadow: var(--shadow-soft);
}

.card h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 14px;
  color: var(--text-primary);
}

.table-scroll {
  overflow-x: auto;
}

.org-cell {
  font-weight: 600;
  color: var(--text-primary);
}

.org-code {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: 6px;
}

.disabled-hint {
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
