<script setup lang="ts">
/**
 * The guided product tour — the page a salesperson opens in front of a
 * prospect, and the page a new customer opens on their first day.
 *
 * It is a *script*, not a dashboard: each step says what to show, why a
 * restaurant owner cares, and opens the real screen. Deliberately no
 * screenshots and no mock widgets — the whole point is that the prospect
 * is clicking the actual product with real-shaped data behind it.
 *
 * Nothing on this page exposes how any of it is built: no seed commands,
 * no server names, no credentials, no model or endpoint names. Everything
 * here is written for someone who runs restaurants, not for someone who
 * runs the deployment. The operator-facing side of the demo tenant (how to
 * build it, how to remove it) lives in docs/ai-handoff, not on screen.
 *
 * Steps are filtered by the tenant's enabled modules, so a tour never
 * promises a screen this account cannot open.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  Box, Calendar, Clock, Document, Money, Odometer, Present, TrendCharts,
} from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const isMobile = useIsMobile()

interface TourStep {
  key: string
  icon: unknown
  route: string
  /** Hidden when the tenant isn't entitled to this module, so the tour
   * never offers a screen the account would be bounced out of. */
  feature?: string
  /** Hidden for a branch-level account when the step is a chain-wide one. */
  adminOnly?: boolean
}

const ALL_STEPS: TourStep[] = [
  { key: 'dashboard', icon: Odometer, route: '/dashboard' },
  { key: 'dailyReport', icon: Document, route: '/daily-report' },
  { key: 'monthlyAnalysis', icon: TrendCharts, route: '/monthly-analysis' },
  { key: 'purchasing', icon: Box, route: '/purchasing', feature: 'purchasing' },
  { key: 'scheduling', icon: Calendar, route: '/scheduling', feature: 'scheduling' },
  { key: 'attendance', icon: Clock, route: '/attendance', feature: 'scheduling' },
  { key: 'wages', icon: Money, route: '/wages', feature: 'wages' },
  { key: 'promotions', icon: Present, route: '/promotions', feature: 'promotions' },
]

const steps = computed(() => ALL_STEPS.filter((step) => {
  if (step.feature && !auth.enabledFeatures.includes(step.feature)) return false
  if (step.adminOnly && auth.role !== 'admin') return false
  return true
}))

function open(step: TourStep) {
  router.push(step.route)
}
</script>

<template>
  <div class="demo-view">
    <div class="card intro-card">
      <h2>{{ t('demo.title') }}</h2>
      <p class="intro-lead">{{ t('demo.lead') }}</p>
      <p v-if="auth.isDemo" class="intro-demo-note">{{ t('demo.sampleDataNote') }}</p>
      <p v-else class="intro-live-note">{{ t('demo.liveDataNote') }}</p>
    </div>

    <ol class="steps" :class="{ 'is-mobile': isMobile }">
      <li v-for="(step, index) in steps" :key="step.key" class="step-card">
        <div class="step-head">
          <span class="step-number">{{ index + 1 }}</span>
          <el-icon class="step-icon"><component :is="step.icon" /></el-icon>
          <h3>{{ t(`demo.steps.${step.key}.title`) }}</h3>
        </div>
        <p class="step-what">{{ t(`demo.steps.${step.key}.what`) }}</p>
        <p class="step-why">{{ t(`demo.steps.${step.key}.why`) }}</p>
        <el-button type="primary" plain class="step-open" @click="open(step)">
          {{ t('demo.openScreen') }}
        </el-button>
      </li>
    </ol>

    <div class="card closing-card">
      <h3>{{ t('demo.closingTitle') }}</h3>
      <ul class="closing-list">
        <li>{{ t('demo.closing.multiBranch') }}</li>
        <li>{{ t('demo.closing.bilingual') }}</li>
        <li>{{ t('demo.closing.exports') }}</li>
        <li>{{ t('demo.closing.roles') }}</li>
        <li>{{ t('demo.closing.mobile') }}</li>
      </ul>
      <p v-if="auth.isDemo" class="closing-reset">{{ t('demo.resetNote') }}</p>
    </div>
  </div>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 14px;
}

.intro-card h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--text-primary);
}

.intro-lead {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin: 0 0 10px;
}

.intro-demo-note,
.intro-live-note {
  font-size: 13px;
  line-height: 1.7;
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-alt);
  color: var(--text-secondary);
}

.intro-demo-note {
  border-left: 3px solid #f0a020;
}

.intro-live-note {
  border-left: 3px solid var(--accent);
}

.steps {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.step-card {
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 18px 20px;
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.step-number {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-icon {
  color: var(--accent);
  font-size: 17px;
  flex-shrink: 0;
}

.step-head h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  /* Wraps rather than truncating — a step title the reader can't finish
     reading defeats the purpose of a script. */
  overflow-wrap: anywhere;
}

.step-what {
  font-size: 13.5px;
  color: var(--text-primary);
  line-height: 1.65;
  margin: 0 0 8px;
}

.step-why {
  font-size: 12.5px;
  color: var(--text-tertiary);
  line-height: 1.6;
  margin: 0 0 14px;
  /* Pushes the button to the bottom so every card's button lines up
     regardless of how long its text is. */
  flex: 1;
}

.step-open {
  align-self: flex-start;
}

.closing-card h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 10px;
  color: var(--text-primary);
}

.closing-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.closing-reset {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 12px 0 0;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .card,
  .step-card {
    padding: 16px 14px;
  }

  .steps {
    grid-template-columns: 1fr;
  }

  .step-open {
    align-self: stretch;
    height: 44px;
  }
}
</style>
