import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

const A4_WIDTH_MM = 210
const A4_HEIGHT_MM = 297
const MARGIN_MM = 10
const USABLE_WIDTH_MM = A4_WIDTH_MM - MARGIN_MM * 2
const USABLE_HEIGHT_MM = A4_HEIGHT_MM - MARGIN_MM * 2

/**
 * The offscreen-node height (in the same CSS-px units as the `widthPx` a
 * report builder renders at), above which downloadElementAsPdf's own
 * "shrink to fit" would have to shrink the page below its natural font
 * sizes. A report that needs to guarantee readable text — never satisfying
 * "fits one page" by silently shrinking the whole document — measures its
 * built content against this before deciding whether to lay it out as one
 * page or split it across several (see MonthlyAnalysisView.vue's PDF
 * builder for the paginate-only-if-it-doesn't-fit logic this exists for).
 */
export function estimateUnshrunkHeightPx(widthPx: number): number {
  return USABLE_HEIGHT_MM * (widthPx / USABLE_WIDTH_MM)
}

function computeImagePlacement(canvas: HTMLCanvasElement) {
  const canvasAspectRatio = canvas.height / canvas.width
  let renderWidthMm = USABLE_WIDTH_MM
  let renderHeightMm = renderWidthMm * canvasAspectRatio
  if (renderHeightMm > USABLE_HEIGHT_MM) {
    renderHeightMm = USABLE_HEIGHT_MM
    renderWidthMm = renderHeightMm / canvasAspectRatio
  }
  const xOffset = MARGIN_MM + (USABLE_WIDTH_MM - renderWidthMm) / 2
  const yOffset = MARGIN_MM
  return { renderWidthMm, renderHeightMm, xOffset, yOffset }
}

// scale 1.5 is plenty for a text/lines table (this isn't a photo) — PNG at
// scale 2 was producing multi-megabyte files for a single page of text,
// since a screenshot-of-text compresses far worse than the same content
// would as native vector text. JPEG trades imperceptible edge softness on
// the (already-small) table text for a much smaller file.
async function rasterize(element: HTMLElement) {
  return html2canvas(element, { scale: 1.5, backgroundColor: '#ffffff' })
}

/**
 * Renders an offscreen DOM element to a single-page A4 PDF, scaling the
 * whole rendered image down (never up) to guarantee it fits on one page —
 * same "shrink to fit" principle as usePrintFit's zoom-to-fit printing,
 * just targeting a PDF blob instead of window.print(). Because the source
 * element is a purpose-built offscreen node (not the live app shell), the
 * old print bug — hidden siblings retaining their layout height and
 * leaving blank pages — can't happen here: there are no hidden siblings.
 */
export async function downloadElementAsPdf(element: HTMLElement, filename: string) {
  const canvas = await rasterize(element)
  const { renderWidthMm, renderHeightMm, xOffset, yOffset } = computeImagePlacement(canvas)
  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })
  pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', xOffset, yOffset, renderWidthMm, renderHeightMm)
  pdf.save(filename.endsWith('.pdf') ? filename : `${filename}.pdf`)
}

/**
 * Same as downloadElementAsPdf, but one element per PDF page (jsPDF's
 * addPage() between each) — for a report whose content is legitimately
 * longer than one page (see renderOffscreenPagesToPdf) rather than a
 * document being forced onto extra blank pages.
 */
export async function downloadElementsAsPdf(elements: HTMLElement[], filename: string) {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })
  for (const [index, element] of elements.entries()) {
    const canvas = await rasterize(element)
    const { renderWidthMm, renderHeightMm, xOffset, yOffset } = computeImagePlacement(canvas)
    if (index > 0) pdf.addPage()
    pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', xOffset, yOffset, renderWidthMm, renderHeightMm)
  }
  pdf.save(filename.endsWith('.pdf') ? filename : `${filename}.pdf`)
}

/**
 * Builds a node positioned off-screen (not display:none — html2canvas
 * can't measure/rasterize an element with no layout box), runs `build`
 * to fill it in, captures it, then always tears it down again.
 */
export async function renderOffscreenToPdf(filename: string, widthPx: number, build: (root: HTMLDivElement) => void) {
  const root = document.createElement('div')
  root.style.position = 'fixed'
  root.style.top = '0'
  root.style.left = '-99999px'
  root.style.width = `${widthPx}px`
  root.style.background = '#ffffff'
  document.body.appendChild(root)
  try {
    build(root)
    await downloadElementAsPdf(root, filename)
  } finally {
    document.body.removeChild(root)
  }
}

/** Class marking one logical report page inside a multi-page document (see
 * buildPagesInHost). Only the *print* path needs it — the page-break rules
 * keyed off it live in global.css — but every page carries it so the node
 * tree a PDF is rasterized from and the node tree the browser paginates are
 * byte-for-byte the same document. */
export const REPORT_PAGE_CLASS = 'report-page'

/**
 * Fills `host` with as many logical report pages as `build` asks for, and
 * returns them in order. Each page is a `widthPx`-wide node carrying the
 * shared report base styling (white background, black text, the report
 * font, the shared padding) — not just the first one. A continuation page
 * that skipped this would inherit whatever theme colors happen to be active
 * on <body> (dark mode text on a white page, for instance), since it's a
 * plain div with nothing else setting its color/background.
 *
 * Shared by both report destinations — `renderOffscreenPagesToPdf` (host
 * off-screen, pages rasterized into a PDF) and a page's print flow (host is
 * the `.print-only-document` node the browser paginates). That sharing is
 * the point: the printed document and the downloaded PDF are built by the
 * same builder into the same node structure, so their content, pagination,
 * headers and amount formatting cannot drift apart.
 */
export function buildPagesInHost(
  host: HTMLElement,
  widthPx: number,
  build: (addPage: () => HTMLDivElement) => void,
): HTMLDivElement[] {
  const pages: HTMLDivElement[] = []
  function addPage(): HTMLDivElement {
    const page = document.createElement('div')
    page.className = REPORT_PAGE_CLASS
    page.style.width = `${widthPx}px`
    styleReportRoot(page)
    host.appendChild(page)
    pages.push(page)
    return page
  }
  build(addPage)
  return pages
}

/**
 * Multi-page counterpart of renderOffscreenToPdf: `build` receives an
 * `addPage()` function it can call as many times as it needs logical pages,
 * each returning a fresh offscreen node (widthPx wide) to fill in; every
 * page is rasterized and written to the PDF independently via
 * downloadElementsAsPdf, so a table row is never split mid-row across two
 * pages — pagination happens at whichever `addPage()` calls the builder
 * chose, not by an image being cut in half.
 */
export async function renderOffscreenPagesToPdf(
  filename: string,
  widthPx: number,
  build: (addPage: () => HTMLDivElement) => void,
) {
  const host = document.createElement('div')
  host.style.position = 'fixed'
  host.style.top = '0'
  host.style.left = '-99999px'
  document.body.appendChild(host)
  try {
    await downloadElementsAsPdf(buildPagesInHost(host, widthPx, build), filename)
  } finally {
    document.body.removeChild(host)
  }
}

/**
 * Tiny DOM-builder shared by every "hand-built offscreen PDF" (as opposed
 * to screenshotting a live, on-screen element) — creates `tag`, applies
 * `styles` as literal inline CSS (never a theme variable or an Element
 * Plus component, so these documents render identically regardless of the
 * viewer's light/dark theme), and optionally sets its text content.
 */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  styles: Partial<CSSStyleDeclaration>,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  Object.assign(node.style, styles)
  if (text !== undefined) node.textContent = text
  return node
}

/**
 * One shared visual spec for every hand-built report PDF (daily/monthly/
 * yearly) so their font sizes can't drift apart from each other again —
 * daily's own spec (already tuned and shipped) is the baseline every other
 * report is meant to match, not a separate, smaller-print style.
 */
export const REPORT_PDF_FONT = '"Hiragino Sans", "Microsoft YaHei", sans-serif'

export const REPORT_PDF_TEXT = {
  title: { fontSize: '22px', fontWeight: '800' },
  reportType: { fontSize: '18px', fontWeight: '800' },
  sectionTitle: { fontSize: '14px', fontWeight: '800' },
  body: { fontSize: '13px', fontWeight: '400' },
  heroLabel: { fontSize: '11px', fontWeight: '700' },
  heroValue: { fontSize: '24px', fontWeight: '800' },
} as const

/** Sets the page-independent base styles every report root needs — never a
 * theme variable or Element Plus class, so the document looks the same
 * regardless of the viewer's light/dark theme (see downloadElementAsPdf's
 * own doc comment for why). */
export function styleReportRoot(root: HTMLElement) {
  root.style.fontFamily = REPORT_PDF_FONT
  root.style.color = '#000000'
  root.style.background = '#ffffff'
  root.style.padding = '26px 30px'
}

/** The title-left / report-type-right header every report's first page
 * opens with (daily's existing header, extracted so monthly/yearly use the
 * exact same sizes instead of re-declaring their own). */
export function buildReportHeader(
  titleContent: string | HTMLElement,
  reportTypeText: string,
): HTMLDivElement {
  const header = el('div', {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
    borderBottom: '2px solid #333', paddingBottom: '10px', marginBottom: '14px',
  })
  const left = typeof titleContent === 'string'
    ? el('div', { fontSize: REPORT_PDF_TEXT.title.fontSize, fontWeight: REPORT_PDF_TEXT.title.fontWeight }, titleContent)
    : titleContent
  header.appendChild(left)
  header.appendChild(el('div', { fontSize: REPORT_PDF_TEXT.reportType.fontSize, fontWeight: REPORT_PDF_TEXT.reportType.fontWeight }, reportTypeText))
  return header
}

/** A slimmer header repeated at the top of every continuation page (task:
 * "每页重复报告名称、期间和表格表头") — smaller than the first page's since
 * it isn't the page's main heading, but still well above the 10–11px floor. */
export function buildReportContinuationHeader(titleText: string, reportTypeText: string): HTMLDivElement {
  const header = el('div', {
    display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
    borderBottom: '1.5px solid #333', paddingBottom: '6px', marginBottom: '10px',
  })
  header.appendChild(el('div', { fontSize: '15px', fontWeight: '800' }, titleText))
  header.appendChild(el('div', { fontSize: '12px', fontWeight: '700', color: '#555' }, reportTypeText))
  return header
}

/** The bordered-bottom section label used before every table/group (payment
 * methods, supplier ranking, cash register, expenses, daily/monthly detail
 * — previously re-declared with the same literal styles in each report). */
export function reportSectionTitle(text: string): HTMLDivElement {
  return el('div', {
    fontSize: REPORT_PDF_TEXT.sectionTitle.fontSize, fontWeight: REPORT_PDF_TEXT.sectionTitle.fontWeight,
    marginBottom: '6px', borderBottom: '1px solid #999', paddingBottom: '3px',
  }, text)
}

// ---------------------------------------------------------------------------
// Table cells shared by every hand-built report document. The amount cell
// exists so "right-aligned, tabular-figure, accounting-formatted" is stated
// exactly once rather than re-declared at each of the ~10 call sites that
// render money into a report — which is how the daily and monthly reports
// drifted into showing the same amount two different ways.
// ---------------------------------------------------------------------------

const CELL_BASE: Partial<CSSStyleDeclaration> = {
  padding: '5px 7px',
  borderBottom: '1px solid #ccc',
  fontSize: REPORT_PDF_TEXT.body.fontSize,
}

/** A text cell (labels, dates, names) — left-aligned, and allowed to wrap
 * rather than being clipped, so a long supplier or branch name stays fully
 * readable in the document instead of ending in an ellipsis. */
export function reportTextCell(text: string, options: { bold?: boolean } = {}): HTMLTableCellElement {
  return el('td', {
    ...CELL_BASE,
    textAlign: 'left',
    fontWeight: options.bold ? '700' : '400',
    wordBreak: 'break-word',
  }, text)
}

/**
 * An amount or count cell. Right-aligned and set in tabular figures
 * (`fontVariantNumeric`), so digits occupy identical widths and the column
 * reads as a column of numbers — the thing that makes a negative in
 * brackets line up under the positives above it. `text` is expected to come
 * from formatAccountingCurrency/formatAccountingNumber; this function
 * deliberately does no formatting of its own, so there is exactly one place
 * that decides how an amount reads (see utils/format.ts).
 */
export function reportAmountCell(text: string, options: { bold?: boolean; muted?: boolean } = {}): HTMLTableCellElement {
  return el('td', {
    ...CELL_BASE,
    textAlign: 'right',
    whiteSpace: 'nowrap',
    fontVariantNumeric: 'tabular-nums',
    fontWeight: options.bold ? '800' : '400',
    ...(options.muted ? { color: '#666' } : {}),
  }, text)
}

/** A table header cell, aligned to match the column it heads — an amount
 * column's header is right-aligned over its own digits, which is what makes
 * a continuation page's repeated header line up with the rows under it. */
export function reportHeaderCell(text: string, align: 'left' | 'right' = 'left'): HTMLTableCellElement {
  return el('th', {
    padding: '6px 7px',
    borderBottom: '1.5px solid #333',
    textAlign: align,
    fontWeight: '800',
    fontSize: REPORT_PDF_TEXT.body.fontSize,
    whiteSpace: align === 'right' ? 'nowrap' : 'normal',
  }, text)
}

/**
 * Flows a sequence of small blocks across as many pages as they need.
 *
 * The table-shaped reports paginate by row (see
 * utils/reports/analysisReport.ts, which has its own fit-whole-section-or
 * -chunk-by-row logic). A prose document — the in-app guide — has no rows;
 * it has headings, paragraphs and list items, and wants the plainest
 * possible rule: keep filling the current page, and start a new one the
 * moment something no longer fits.
 *
 * Callers append at PARAGRAPH granularity, never whole sections. That is
 * what keeps this simple and correct: every block is comfortably smaller
 * than a page, so "put it on a fresh page instead" always succeeds. A
 * block genuinely taller than a printable page would still overflow its
 * page rather than being split mid-sentence — appendBlock reports that by
 * returning false so a caller can decide, instead of silently producing a
 * clipped page.
 *
 * `keepWithNext` is how a heading avoids being orphaned at the foot of a
 * page: the heading and the block after it are measured together, and if
 * they don't both fit, the heading moves to the next page with its text.
 */
export function createPageFlow(
  addPage: () => HTMLDivElement,
  options: {
    widthPx: number
    /** Drawn at the top of every page after the first. */
    continuationHeader?: (page: HTMLDivElement, pageNumber: number) => void
  },
) {
  const threshold = estimateUnshrunkHeightPx(options.widthPx)
  let page = addPage()
  let pageCount = 1
  let pendingKeep: HTMLElement[] = []

  function newPage() {
    page = addPage()
    pageCount += 1
    options.continuationHeader?.(page, pageCount)
  }

  function fits() {
    return page.scrollHeight <= threshold
  }

  function place(nodes: HTMLElement[]): boolean {
    for (const node of nodes) page.appendChild(node)
    if (fits()) return true
    for (const node of nodes) page.removeChild(node)
    newPage()
    for (const node of nodes) page.appendChild(node)
    // Still overflowing on a page of its own: the block is taller than a
    // printable page. Keep it (losing content is worse than one tight
    // page) and tell the caller.
    return fits()
  }

  return {
    /** Appends `node`. With `keepWithNext`, holds it back until the
     * following block arrives so the two are placed together. */
    appendBlock(node: HTMLElement, keepWithNext = false): boolean {
      if (keepWithNext) {
        pendingKeep.push(node)
        return true
      }
      const nodes = [...pendingKeep, node]
      pendingKeep = []
      return place(nodes)
    },
    /** Flushes any held-back block — call once at the end, so a document
     * ending on a heading still renders that heading. */
    flush() {
      if (pendingKeep.length) {
        const nodes = pendingKeep
        pendingKeep = []
        place(nodes)
      }
    },
    /** Starts the next block on a fresh page (a new top-level chapter). */
    breakPage() {
      this.flush()
      newPage()
    },
    get pageCount() {
      return pageCount
    },
    get currentPage() {
      return page
    },
  }
}
