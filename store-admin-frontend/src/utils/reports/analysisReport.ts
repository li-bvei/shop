/**
 * The monthly / yearly business report document.
 *
 * This module owns the document itself — its structure, its pagination and
 * how its amounts read — and nothing else: no i18n, no stores, no API, no
 * Vue. Every label arrives pre-translated in an `AnalysisReportDocument`,
 * which is the whole reason it can be shared.
 *
 * It is shared by the report's two destinations:
 *
 *   • the PDF download — `renderOffscreenPagesToPdf` rasterizes the pages
 *   • the print button  — the same pages are built into a
 *     `.print-only-document.is-paged` node and handed to the browser
 *
 * Both go through `pdfExport.buildPagesInHost`, so they are not "two
 * implementations that agree"; they are one document rendered to two
 * destinations. Content, page breaks, repeated continuation headers, column
 * alignment and amount formatting therefore cannot drift apart between
 * printing and downloading, which is exactly what they used to do.
 *
 * Amounts are never formatted here. Callers pass raw numbers and this module
 * renders them through `formatAccountingCurrency`/`formatAccountingNumber`
 * (utils/format.ts) into right-aligned, tabular-figure cells — one rule for
 * thousands separators, bracketed negatives, zero and missing values, used
 * by the screen, the PDF, the print output and the Excel workbook alike.
 */
import { formatAccountingCurrency, formatAccountingNumber } from '@/utils/format'
import {
  REPORT_PDF_TEXT, buildReportContinuationHeader, buildReportHeader, el,
  estimateUnshrunkHeightPx, reportAmountCell, reportHeaderCell, reportSectionTitle, reportTextCell,
} from '@/utils/pdfExport'

/** A4 at 96dpi is ~794px wide — the same convention as the daily report and
 * supplier PDFs. Both destinations scale this down to the real printable
 * width and never up, so 1px here stays close to 1 printed px. */
export const ANALYSIS_REPORT_PAGE_WIDTH_PX = 794

/** One cell of a report table. `kind` decides the column's alignment and
 * numeric treatment, so a row's shape alone determines its formatting —
 * a call site can't accidentally left-align one month's revenue. */
export type AnalysisReportCell =
  | { kind: 'text'; text: string; bold?: boolean }
  | { kind: 'currency'; value: number | null | undefined; bold?: boolean }
  | { kind: 'count'; value: number | null | undefined; bold?: boolean }
  /** A ratio/percentage — right-aligned like a number but rendered by the
   * caller, since a share isn't an accounting amount. */
  | { kind: 'ratio'; text: string }

export type AnalysisReportSection =
  /** A label + amount list with no column headers (payment-method
   * breakdown, supplier ranking) — matching how these have always read. */
  | { kind: 'list'; title: string; rows: AnalysisReportCell[][] }
  /** A table with a repeated, alignment-matched header row (the daily /
   * monthly detail table). */
  | { kind: 'table'; title: string; columns: { label: string; align: 'left' | 'right' }[]; rows: AnalysisReportCell[][] }

export interface AnalysisReportDocument {
  /** Left-hand first-page heading, e.g. "心斎橋店　2026年9月". */
  titleText: string
  /** Right-hand report-type label, e.g. "月报" — also repeated, with a
   * page number, at the top of every continuation page. */
  reportTypeText: string
  /** The one headline amount the report exists to show (revenue). */
  hero: { label: string; value: number }
  /** The fixed stat grid under the hero. Amounts are raw; `kind` decides
   * how each reads. */
  summary: { label: string; cell: AnalysisReportCell }[]
  sections: AnalysisReportSection[]
  /** Shown in place of a section's rows when it has none. */
  emptyText: string
}

function renderCell(cell: AnalysisReportCell): HTMLTableCellElement {
  switch (cell.kind) {
    case 'text':
      return reportTextCell(cell.text, { bold: cell.bold })
    case 'currency':
      return reportAmountCell(formatAccountingCurrency(cell.value), { bold: cell.bold })
    case 'count':
      return reportAmountCell(formatAccountingNumber(cell.value), { bold: cell.bold })
    case 'ratio':
      return reportAmountCell(cell.text, { muted: true })
  }
}

/** The plain-text form of a cell, for the hero/summary grid, which is not a
 * table. Same formatters as renderCell, so a figure in the summary grid and
 * the same figure in the detail table below it can never disagree. */
function cellText(cell: AnalysisReportCell): string {
  switch (cell.kind) {
    case 'text':
      return cell.text
    case 'currency':
      return formatAccountingCurrency(cell.value)
    case 'count':
      return formatAccountingNumber(cell.value)
    case 'ratio':
      return cell.text
  }
}

function buildHeroAndSummary(page: HTMLElement, doc: AnalysisReportDocument) {
  const hero = el('div', {
    border: '1.5px solid #999', borderRadius: '4px', padding: '10px 14px', marginBottom: '10px',
  })
  hero.appendChild(el('div', {
    fontSize: REPORT_PDF_TEXT.heroLabel.fontSize, fontWeight: REPORT_PDF_TEXT.heroLabel.fontWeight,
    marginBottom: '4px',
  }, doc.hero.label))
  hero.appendChild(el('div', {
    fontSize: REPORT_PDF_TEXT.heroValue.fontSize, fontWeight: REPORT_PDF_TEXT.heroValue.fontWeight,
    fontVariantNumeric: 'tabular-nums',
  }, formatAccountingCurrency(doc.hero.value)))
  page.appendChild(hero)

  const grid = el('div', {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '16px',
    border: '1px solid #ddd', padding: '10px 12px',
  })
  for (const item of doc.summary) {
    const cell = el('div', {})
    cell.appendChild(el('div', {
      fontSize: REPORT_PDF_TEXT.heroLabel.fontSize, marginBottom: '3px',
    }, item.label))
    // Left-aligned under its own label (this is a stat grid, not a column
    // of amounts to compare down), but still set in tabular figures so the
    // seven cells read as one row of figures rather than as prose.
    cell.appendChild(el('div', {
      fontSize: '15px', fontWeight: '800', fontVariantNumeric: 'tabular-nums',
    }, cellText(item.cell)))
    grid.appendChild(cell)
  }
  page.appendChild(grid)
}

/** A titled section's table shell. `columns` is given only for a real table;
 * a `list` section has no header row, matching how the payment-method and
 * supplier lists have always read. */
function buildSectionShell(section: AnalysisReportSection) {
  const wrapper = el('div', {})
  wrapper.appendChild(reportSectionTitle(section.title))
  const table = el('table', {
    width: '100%', borderCollapse: 'collapse', marginBottom: '10px',
    ...(section.kind === 'table' ? { tableLayout: 'fixed' } : {}),
  })
  if (section.kind === 'table') {
    const thead = document.createElement('thead')
    const headRow = document.createElement('tr')
    for (const column of section.columns) {
      headRow.appendChild(reportHeaderCell(column.label, column.align))
    }
    thead.appendChild(headRow)
    table.appendChild(thead)
  }
  const tbody = document.createElement('tbody')
  table.appendChild(tbody)
  wrapper.appendChild(table)
  return { wrapper, tbody }
}

function buildRow(cells: AnalysisReportCell[], zebra: boolean): HTMLTableRowElement {
  const tr = document.createElement('tr')
  if (zebra) tr.style.backgroundColor = '#f7f7f7'
  for (const cell of cells) tr.appendChild(renderCell(cell))
  return tr
}

/**
 * Builds the report page by page, flowing content onto whatever page is
 * currently open and only starting a fresh one when something genuinely
 * doesn't fit — never by shrinking a page below its designed font size
 * (`estimateUnshrunkHeightPx` is the fits-without-shrinking budget every
 * measurement below is checked against).
 *
 * Title/hero/summary grid is small and fixed-size and always opens page 1.
 * Each row-based section is then flowed in order, trying three things in
 * turn: (1) append the whole section to the page already open — the common
 * case for a short report, where everything shares one page; (2) if that
 * overflows, undo it and give the section a fresh page of its own, avoiding
 * a lone orphaned row at the bottom of a busy page; (3) if even a fresh
 * page can't hold it all (a long payment-method list, a 31-day month),
 * chunk its rows across as many further pages as it needs, always on a
 * whole-row boundary. This is what makes "the summary alone is taller than
 * one page" resolve correctly instead of forcing a page per section.
 *
 * Every continuation page repeats the report name, the period and — for a
 * `table` section — its column header, so a loose sheet from the middle of
 * the document is still self-describing.
 */
export function buildAnalysisReportPages(
  addPage: () => HTMLDivElement,
  doc: AnalysisReportDocument,
) {
  const threshold = estimateUnshrunkHeightPx(ANALYSIS_REPORT_PAGE_WIDTH_PX)

  let page = addPage()
  page.appendChild(buildReportHeader(doc.titleText, doc.reportTypeText))
  buildHeroAndSummary(page, doc)

  // Filled in as continuation pages are created; a page's "月报 2/3" label
  // can't be written until the total is known, so each one's right-hand
  // header element is patched at the very end.
  const continuationLabels: HTMLElement[] = []
  let pageCount = 1

  function startContinuationPage() {
    page = addPage()
    pageCount += 1
    const header = buildReportContinuationHeader(doc.titleText, doc.reportTypeText)
    continuationLabels.push(header.children[1] as HTMLElement)
    page.appendChild(header)
  }

  function fits(): boolean {
    return page.scrollHeight <= threshold
  }

  function appendSection(section: AnalysisReportSection) {
    if (section.rows.length === 0) {
      const empty = el('div', {})
      empty.appendChild(reportSectionTitle(section.title))
      empty.appendChild(el('div', {
        fontSize: REPORT_PDF_TEXT.body.fontSize, color: '#888', marginBottom: '10px',
      }, doc.emptyText))
      page.appendChild(empty)
      return
    }

    // Attempt 1: the whole section fits onto whatever's already here.
    let { wrapper, tbody } = buildSectionShell(section)
    section.rows.forEach((cells, i) => tbody.appendChild(buildRow(cells, i % 2 === 1)))
    page.appendChild(wrapper)
    if (fits()) return
    page.removeChild(wrapper)

    // Attempt 2: it fits fine on a fresh page of its own.
    startContinuationPage()
    ;({ wrapper, tbody } = buildSectionShell(section))
    section.rows.forEach((cells, i) => tbody.appendChild(buildRow(cells, i % 2 === 1)))
    page.appendChild(wrapper)
    if (fits()) return
    page.removeChild(wrapper)

    // Attempt 3: even a fresh page can't hold it all — chunk by row, moving
    // a row wholesale onto the next page rather than splitting it.
    ;({ wrapper, tbody } = buildSectionShell(section))
    page.appendChild(wrapper)
    section.rows.forEach((cells, i) => {
      const tr = buildRow(cells, i % 2 === 1)
      tbody.appendChild(tr)
      if (!fits()) {
        tbody.removeChild(tr)
        startContinuationPage()
        ;({ wrapper, tbody } = buildSectionShell(section))
        page.appendChild(wrapper)
        tbody.appendChild(tr)
      }
    })
  }

  for (const section of doc.sections) appendSection(section)

  continuationLabels.forEach((label, i) => {
    label.textContent = `${doc.reportTypeText}　${i + 2}/${pageCount}`
  })
}
