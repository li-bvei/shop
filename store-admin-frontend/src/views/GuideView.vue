<script setup lang="ts">
/**
 * The in-app operating guide / help centre.
 *
 * One source of words: every chapter here and every chapter in the
 * downloadable PDF is rendered from the same `guide.*` locale keys through
 * the same `GUIDE_SECTIONS` structure (utils/guide/guideContent.ts). There
 * is no second copy of the text to fall out of date, and switching the UI
 * language switches the PDF too.
 *
 * Chapters are filtered by the reader's role and the tenant's enabled
 * modules, and the PDF contains exactly what is on screen — a guide that
 * explains screens you cannot open is worse than a shorter guide.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Download, Printer, Search } from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'
import { usePagedDocumentPrint } from '@/composables/usePagedDocumentPrint'
import { renderOffscreenPagesToPdf } from '@/utils/pdfExport'
import { GUIDE_SECTIONS, sectionsFor, type GuideSection } from '@/utils/guide/guideContent'
import {
  GUIDE_PAGE_WIDTH_PX, buildGuidePages,
  type GuideDocument, type GuideDocumentSection,
} from '@/utils/reports/guideDocument'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const isMobile = useIsMobile()

const search = ref('')
const pdfDownloading = ref(false)
const { printing, printPagedDocument } = usePagedDocumentPrint(GUIDE_PAGE_WIDTH_PX)

/** Chapters this reader can act on. Computed, not fixed at load, so it
 * follows a role or entitlement change without a reload. */
const visibleSections = computed(() => sectionsFor(auth.role, auth.enabledFeatures))

function stepsOf(section: GuideSection): string[] {
  return Array.from({ length: section.stepCount }, (_, i) => t(`guide.sections.${section.id}.steps.${i + 1}`))
}

function notesOf(section: GuideSection): string[] {
  return Array.from({ length: section.noteCount }, (_, i) => t(`guide.sections.${section.id}.notes.${i + 1}`))
}

function audienceOf(section: GuideSection): string {
  return section.audiences.map((a) => t(`guide.audiences.${a}`)).join(' / ')
}

/** A chapter matches when the query appears anywhere in it — title,
 * summary, any step or any note. Searching only titles would miss "why
 * does it say no permission", which is exactly what someone types. */
function matches(section: GuideSection, query: string): boolean {
  if (!query) return true
  const haystack = [
    t(`guide.sections.${section.id}.title`),
    t(`guide.sections.${section.id}.summary`),
    ...stepsOf(section),
    ...notesOf(section),
  ].join('\n').toLowerCase()
  return haystack.includes(query.toLowerCase())
}

const filteredSections = computed(() => {
  const query = search.value.trim()
  return visibleSections.value.filter((section) => matches(section, query))
})

/** Numbering follows the reader's own filtered chapter list, so the
 * number beside a heading always matches the contents page above it —
 * including in the PDF, which is built from the same list. */
function numberOf(section: GuideSection): string {
  return String(visibleSections.value.indexOf(section) + 1)
}

function openScreen(section: GuideSection) {
  if (section.route) router.push(section.route)
}

function scrollTo(section: GuideSection) {
  document.getElementById(`guide-${section.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// --- The printable / downloadable document --------------------------------

function buildDocument(): GuideDocument {
  const generatedAt = new Date().toLocaleString(locale.value === 'ja' ? 'ja-JP' : 'zh-CN')
  return {
    title: t('guide.pageTitle'),
    documentLabel: t('guide.documentLabel'),
    subtitle: t('guide.subtitle'),
    generatedAtLabel: t('guide.generatedAt', { at: generatedAt }),
    contentsLabel: t('guide.contents'),
    stepsLabel: t('guide.steps'),
    notesLabel: t('guide.notes'),
    audienceLabel: t('guide.audience'),
    // The whole guide for this reader — never the search-filtered subset.
    // A downloaded file is kept and re-read later, when whatever was typed
    // into the search box is long forgotten.
    sections: visibleSections.value.map((section): GuideDocumentSection => ({
      number: numberOf(section),
      title: t(`guide.sections.${section.id}.title`),
      summary: t(`guide.sections.${section.id}.summary`),
      audience: audienceOf(section),
      steps: stepsOf(section),
      notes: notesOf(section),
    })),
  }
}

const fileName = computed(() => `${t('guide.pageTitle')}_${new Date().toISOString().slice(0, 10)}`)

async function handleDownloadPdf() {
  pdfDownloading.value = true
  try {
    const doc = buildDocument()
    await renderOffscreenPagesToPdf(
      fileName.value, GUIDE_PAGE_WIDTH_PX, (addPage) => buildGuidePages(addPage, doc),
    )
  } finally {
    pdfDownloading.value = false
  }
}

async function handlePrint() {
  const doc = buildDocument()
  await printPagedDocument(fileName.value, (addPage) => buildGuidePages(addPage, doc))
}

const totalSections = computed(() => GUIDE_SECTIONS.length)
</script>

<template>
  <div class="guide-view">
    <div class="card intro-card">
      <div class="intro-head">
        <div class="intro-text">
          <h2>{{ t('guide.pageTitle') }}</h2>
          <p class="intro-lead">{{ t('guide.subtitle') }}</p>
          <p class="intro-hint">{{ t('guide.filterHint') }}（{{ visibleSections.length }}/{{ totalSections }}）</p>
        </div>
        <div class="intro-actions no-print" :class="{ 'is-mobile': isMobile }">
          <el-button :icon="Printer" :loading="printing" @click="handlePrint">
            {{ isMobile ? t('common.printShort') : t('guide.print') }}
          </el-button>
          <el-button :icon="Download" type="primary" plain :loading="pdfDownloading" @click="handleDownloadPdf">
            {{ isMobile ? t('common.downloadPdfShort') : t('guide.downloadPdf') }}
          </el-button>
        </div>
      </div>
      <el-input
        v-model="search" class="guide-search no-print" :prefix-icon="Search"
        :placeholder="t('guide.searchPlaceholder')" clearable
      />
    </div>

    <!-- Contents: the page's own navigation, matching the PDF's. -->
    <div v-if="!search" class="card contents-card no-print">
      <h3>{{ t('guide.contents') }}</h3>
      <ol class="contents-list">
        <li v-for="section in visibleSections" :key="section.id">
          <button type="button" class="contents-link" @click="scrollTo(section)">
            <span class="contents-number">{{ numberOf(section) }}</span>
            <span class="contents-title">{{ t(`guide.sections.${section.id}.title`) }}</span>
            <span class="contents-audience">{{ audienceOf(section) }}</span>
          </button>
        </li>
      </ol>
    </div>

    <div v-for="section in filteredSections" :id="`guide-${section.id}`" :key="section.id" class="card section-card">
      <div class="section-head">
        <span class="section-number">{{ numberOf(section) }}</span>
        <h3>{{ t(`guide.sections.${section.id}.title`) }}</h3>
        <span class="section-audience">{{ audienceOf(section) }}</span>
      </div>
      <p class="section-summary">{{ t(`guide.sections.${section.id}.summary`) }}</p>

      <template v-if="section.stepCount">
        <h4>{{ t('guide.steps') }}</h4>
        <ol class="step-list">
          <li v-for="(step, i) in stepsOf(section)" :key="i">{{ step }}</li>
        </ol>
      </template>

      <template v-if="section.noteCount">
        <h4>{{ t('guide.notes') }}</h4>
        <ul class="note-list">
          <li v-for="(note, i) in notesOf(section)" :key="i">{{ note }}</li>
        </ul>
      </template>

      <el-button v-if="section.route" class="no-print" link type="primary" @click="openScreen(section)">
        {{ t('guide.openScreen') }} →
      </el-button>
    </div>

    <p v-if="!filteredSections.length" class="empty-hint">{{ t('guide.noMatch') }}</p>
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

.intro-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.intro-text {
  flex: 1;
  min-width: 0;
}

.intro-card h2 {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--text-primary);
}

.intro-lead {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin: 0 0 6px;
}

.intro-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0;
}

.intro-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.guide-search {
  margin-top: 14px;
}

.contents-card h3,
.section-card h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.contents-card h3 {
  margin-bottom: 10px;
}

.contents-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.contents-link {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  background: none;
  border: none;
  padding: 7px 0;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  border-bottom: 1px solid var(--border);
}

.contents-list li:last-child .contents-link {
  border-bottom: none;
}

.contents-number {
  font-weight: 700;
  color: var(--accent);
  min-width: 20px;
  flex-shrink: 0;
}

.contents-title {
  flex: 1;
  font-size: 13.5px;
  color: var(--text-primary);
  /* Wraps rather than truncating — a contents entry you can't finish
     reading is not a contents entry. */
  overflow-wrap: anywhere;
}

.contents-audience,
.section-audience {
  font-size: 11.5px;
  color: var(--text-tertiary);
  background: var(--surface-alt);
  border-radius: 999px;
  padding: 2px 9px;
  white-space: nowrap;
  flex-shrink: 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.section-number {
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

.section-summary {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.75;
  margin: 0 0 12px;
}

.section-card h4 {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-tertiary);
  margin: 14px 0 6px;
  letter-spacing: 0.02em;
}

.step-list,
.note-list {
  margin: 0;
  padding-left: 22px;
  font-size: 13.5px;
  color: var(--text-primary);
  line-height: 1.85;
}

.note-list {
  color: var(--text-secondary);
  font-size: 13px;
}

.step-list li,
.note-list li {
  margin-bottom: 4px;
  overflow-wrap: anywhere;
}

.empty-hint {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 24px 0;
}

@media (max-width: 768px) {
  .card {
    padding: 16px 14px;
  }

  .intro-actions.is-mobile {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
  }

  .intro-actions.is-mobile :deep(.el-button) {
    width: 100%;
    min-width: 0;
    height: 44px;
    margin-left: 0;
  }

  .contents-audience {
    display: none;
  }

  .step-list,
  .note-list {
    padding-left: 18px;
  }
}
</style>
