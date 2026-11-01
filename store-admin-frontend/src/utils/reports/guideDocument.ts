/**
 * The operating guide as a printable document.
 *
 * Shares everything structural with the business reports — the same
 * `buildPagesInHost` page construction, the same base styling, the same
 * continuation headers — so the guide PDF, the report PDFs and the printed
 * output of either are one family rather than three hand-built layouts.
 *
 * Like analysisReport.ts, this module takes its text pre-translated and
 * does no i18n of its own: the on-screen guide and this document render
 * from the same `guide.*` keys, which is what stops the two copies of the
 * guide saying different things.
 *
 * Japanese and Chinese text renders correctly because the pages are real
 * DOM rasterized by html2canvas with the project's report font stack
 * ("Hiragino Sans", "Microsoft YaHei") — the glyphs come from the system,
 * not from an embedded Latin font, so there is no tofu and no font
 * subsetting step to get wrong.
 */
import {
  REPORT_PDF_TEXT, buildReportContinuationHeader, buildReportHeader, createPageFlow, el,
} from '@/utils/pdfExport'

export const GUIDE_PAGE_WIDTH_PX = 794

export interface GuideDocumentSection {
  /** "3" — the chapter number shown in the contents and the heading. */
  number: string
  title: string
  /** One sentence on what the chapter is for. */
  summary: string
  /** Who it is for, already rendered ("本部管理者・店長"). */
  audience: string
  steps: string[]
  notes: string[]
}

export interface GuideDocument {
  title: string
  subtitle: string
  /** Shown under the title on page 1 and in every continuation header. */
  documentLabel: string
  generatedAtLabel: string
  contentsLabel: string
  stepsLabel: string
  notesLabel: string
  audienceLabel: string
  sections: GuideDocumentSection[]
}

function heading(text: string, number: string): HTMLDivElement {
  const wrapper = el('div', { marginTop: '16px', marginBottom: '6px' })
  const line = el('div', {
    display: 'flex', alignItems: 'baseline', gap: '8px',
    borderBottom: '1.5px solid #333', paddingBottom: '4px',
  })
  line.appendChild(el('span', { fontSize: '16px', fontWeight: '800', color: '#000' }, number))
  line.appendChild(el('span', { fontSize: '16px', fontWeight: '800' }, text))
  wrapper.appendChild(line)
  return wrapper
}

function paragraph(text: string, options: { muted?: boolean } = {}): HTMLDivElement {
  return el('div', {
    fontSize: REPORT_PDF_TEXT.body.fontSize,
    lineHeight: '1.7',
    margin: '4px 0',
    color: options.muted ? '#555' : '#000',
    // CJK text has no spaces to break at, so an un-hinted long run would
    // otherwise push past the page edge.
    wordBreak: 'break-word',
  }, text)
}

function labelled(label: string, text: string): HTMLDivElement {
  const row = el('div', { display: 'flex', gap: '8px', margin: '4px 0' })
  row.appendChild(el('div', {
    fontSize: '12px', fontWeight: '700', color: '#555', minWidth: '72px', flexShrink: '0',
  }, label))
  row.appendChild(el('div', {
    fontSize: '12px', color: '#555', lineHeight: '1.6', wordBreak: 'break-word',
  }, text))
  return row
}

function listItem(marker: string, text: string, markerColor = '#000'): HTMLDivElement {
  const row = el('div', { display: 'flex', gap: '8px', margin: '5px 0', alignItems: 'flex-start' })
  row.appendChild(el('div', {
    fontSize: '12px', fontWeight: '700', color: markerColor,
    minWidth: '20px', flexShrink: '0', lineHeight: '1.7',
  }, marker))
  row.appendChild(el('div', {
    fontSize: REPORT_PDF_TEXT.body.fontSize, lineHeight: '1.7', wordBreak: 'break-word',
  }, text))
  return row
}

function sectionLabel(text: string): HTMLDivElement {
  return el('div', {
    fontSize: '12px', fontWeight: '800', color: '#333',
    marginTop: '8px', marginBottom: '2px',
  }, text)
}

/**
 * Builds the guide: a title page carrying the table of contents, then one
 * chapter after another, each starting on its own page.
 *
 * Each chapter opens on a fresh page deliberately. A guide is read by
 * jumping to the part you need, and a chapter that starts halfway down the
 * previous chapter's last page is much harder to find — the small amount
 * of wasted paper buys back the document's only navigation.
 *
 * Headings are appended with `keepWithNext`, so a chapter title can never
 * be left alone at the foot of a page with its text overleaf.
 */
export function buildGuidePages(addPage: () => HTMLDivElement, doc: GuideDocument) {
  // Every continuation page's right-hand label is filled in at the very
  // end: it carries "n / total", and the total isn't known until the last
  // chapter has been laid out.
  const pageLabels: HTMLElement[] = []

  const flow = createPageFlow(addPage, {
    widthPx: GUIDE_PAGE_WIDTH_PX,
    continuationHeader: (page) => {
      const header = buildReportContinuationHeader(doc.title, '')
      pageLabels.push(header.children[1] as HTMLElement)
      page.appendChild(header)
    },
  })

  // --- Page 1: title + contents -------------------------------------
  // The right-hand slot carries the generation date rather than repeating
  // the document's own name, which the left-hand title already says.
  const first = flow.currentPage
  first.appendChild(buildReportHeader(doc.title, doc.generatedAtLabel))
  first.appendChild(paragraph(doc.subtitle))

  const contents = el('div', {
    marginTop: '18px', border: '1px solid #ddd', padding: '12px 14px',
  })
  contents.appendChild(el('div', {
    fontSize: REPORT_PDF_TEXT.sectionTitle.fontSize,
    fontWeight: REPORT_PDF_TEXT.sectionTitle.fontWeight,
    marginBottom: '8px',
  }, doc.contentsLabel))
  for (const section of doc.sections) {
    const row = el('div', {
      display: 'flex', gap: '10px', fontSize: '12.5px', lineHeight: '1.9', alignItems: 'baseline',
    })
    row.appendChild(el('span', { fontWeight: '700', minWidth: '22px' }, section.number))
    row.appendChild(el('span', { fontWeight: '700', flex: '1' }, section.title))
    row.appendChild(el('span', { color: '#777', fontSize: '11.5px' }, section.audience))
    contents.appendChild(row)
  }
  first.appendChild(contents)

  // --- One chapter per page ------------------------------------------
  for (const section of doc.sections) {
    flow.breakPage()
    flow.appendBlock(heading(section.title, section.number), true)
    flow.appendBlock(paragraph(section.summary))
    flow.appendBlock(labelled(doc.audienceLabel, section.audience))

    if (section.steps.length) {
      flow.appendBlock(sectionLabel(doc.stepsLabel), true)
      section.steps.forEach((step, index) => {
        flow.appendBlock(listItem(`${index + 1}.`, step))
      })
    }

    if (section.notes.length) {
      flow.appendBlock(sectionLabel(doc.notesLabel), true)
      for (const note of section.notes) {
        flow.appendBlock(listItem('•', note, '#888'))
      }
    }
  }

  // Without this, a document whose last block was held back by
  // keepWithNext would silently lose it.
  flow.flush()

  // Page 1 is the contents and carries no number; the rest are numbered
  // against the real total, so a loose sheet says where it belongs.
  pageLabels.forEach((label, index) => {
    // Just the number: the continuation header's left half already
    // carries the document's name, and repeating it reads as a stutter.
    label.textContent = `${index + 2} / ${flow.pageCount}`
  })
}
