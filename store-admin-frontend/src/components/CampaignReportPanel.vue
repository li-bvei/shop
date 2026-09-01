<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDelayedLoading } from '@/composables/useDelayedLoading'
import { currentMonthJst } from '@/utils/format'
import { fetchCampaignReport, type CampaignReport } from '@/api/promotions'

const props = defineProps<{ campaignId: string }>()
const { t } = useI18n()

const month = ref(currentMonthJst())
const report = ref<CampaignReport | null>(null)
const { loading, run } = useDelayedLoading()

async function load() {
  if (!props.campaignId) {
    report.value = null
    return
  }
  await run(async () => {
    report.value = await fetchCampaignReport(props.campaignId, month.value)
  })
}

watch([() => props.campaignId, month], load, { immediate: true })

const yen = (n: number) => `¥${n.toLocaleString('ja-JP')}`
</script>

<template>
  <div>
    <div class="toolbar">
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" />
    </div>

    <div v-if="report" v-loading="loading" class="report">
      <section class="block">
        <h4>{{ t('report.spend') }}</h4>
        <div class="stats">
          <div><strong>{{ report.spend.verifications }}</strong><span>{{ t('report.verifications') }}</span></div>
          <div><strong>{{ yen(report.spend.totalAmount) }}</strong><span>{{ t('report.totalAmount') }}</span></div>
          <div><strong>{{ report.spend.voided }}</strong><span>{{ t('report.voided') }}</span></div>
        </div>
      </section>

      <section class="block">
        <h4>{{ t('report.points') }}</h4>
        <div class="stats wide">
          <div><strong>+{{ report.points.earned }}</strong><span>{{ t('report.earned') }}</span></div>
          <div><strong>−{{ report.points.spentOnDraws }}</strong><span>{{ t('report.spentOnDraws') }}</span></div>
          <div><strong>−{{ report.points.spentOnVouchers }}</strong><span>{{ t('report.spentOnVouchers') }}</span></div>
          <div><strong>+{{ report.points.refunded }}</strong><span>{{ t('report.refunded') }}</span></div>
          <div><strong>−{{ report.points.expired }}</strong><span>{{ t('report.expired') }}</span></div>
        </div>
      </section>

      <section class="block">
        <h4>{{ t('report.staffStats') }}</h4>
        <el-table :data="report.staffStats" size="small" :empty-text="t('promotions.noRecords')">
          <el-table-column prop="staff" :label="t('promotions.operator')" min-width="110" />
          <el-table-column prop="count" :label="t('report.count')" width="80" />
          <el-table-column :label="t('report.totalAmount')" width="120">
            <template #default="{ row }">{{ yen(row.totalAmount) }}</template>
          </el-table-column>
          <el-table-column :label="t('report.avgAmount')" width="110">
            <template #default="{ row }">{{ yen(row.avgAmount) }}</template>
          </el-table-column>
          <el-table-column prop="voids" :label="t('promotions.voided')" width="80" />
        </el-table>
      </section>

      <section class="block">
        <h4>{{ t('report.draws') }}</h4>
        <div class="stats">
          <div><strong>{{ report.draws.total }}</strong><span>{{ t('report.drawTotal') }}</span></div>
          <div><strong>{{ report.draws.won }}</strong><span>{{ t('promotions.drawWon') }}</span></div>
          <div><strong>{{ report.draws.refund }}</strong><span>{{ t('promotions.drawRefund') }}</span></div>
        </div>
        <el-table :data="report.draws.byPrize" size="small" class="mt">
          <el-table-column prop="prize" :label="t('promotions.prizeResult')" min-width="150" />
          <el-table-column prop="count" :label="t('report.count')" width="80" />
        </el-table>
      </section>

      <section class="block">
        <h4>{{ t('report.vouchers') }}</h4>
        <div class="stats">
          <div><strong>{{ report.vouchers.issued }}</strong><span>{{ t('report.issued') }}</span></div>
          <div><strong>{{ report.vouchers.redeemed }}</strong><span>{{ t('promotions.voucherRedeemed') }}</span></div>
          <div><strong>{{ yen(report.vouchers.cashFaceRedeemedYen) }}</strong><span>{{ t('report.cashRedeemed') }}</span></div>
        </div>
      </section>

      <section class="block">
        <h4>{{ t('report.risk') }}</h4>
        <div class="stats">
          <div><strong>{{ report.risk.total }}</strong><span>{{ t('report.riskTotal') }}</span></div>
          <div><strong>{{ report.risk.open }}</strong><span>{{ t('risk.statusOpen') }}</span></div>
        </div>
        <ul v-if="report.risk.byType.length" class="risk-list">
          <li v-for="r in report.risk.byType" :key="r.eventType">
            {{ t(`risk.type_${r.eventType}`, r.eventType) }} — {{ r.count }}
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 16px;
}

.report {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.block h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.stats.wide {
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
}

.stats > div {
  background: var(--surface-alt);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
}

.stats strong {
  display: block;
  font-size: 20px;
  color: var(--text-primary);
}

.stats span {
  font-size: 11px;
  color: var(--text-secondary);
}

.mt {
  margin-top: 10px;
}

.risk-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--text-secondary);
}
</style>
