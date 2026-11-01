import { ref } from 'vue'

import { usePrintFit } from '@/composables/usePrintFit'
import { buildPagesInHost } from '@/utils/pdfExport'

/**
 * Prints a hand-built, already-paginated report document — the print-side
 * counterpart of `renderOffscreenPagesToPdf`.
 *
 * Both take the same `build(addPage)` builder and run it through the same
 * `buildPagesInHost`, so a page prints as the identical node tree the PDF is
 * rasterized from. That's the point: a report's print output and its PDF
 * download are one document with two destinations, not two implementations
 * to keep in sync by hand.
 *
 * What this adds over the PDF path is the browser-print plumbing, all of
 * which the daily report already established and none of which is worth a
 * second copy per report:
 *
 *   • the document is built into a throwaway `.print-only-document` node
 *     rather than the live page, so the on-screen form, the filter bar, the
 *     navigation and Element Plus' body-teleported overlays are all
 *     structurally absent from the print rather than merely hidden (hidden
 *     elements keep their layout height, which is what used to produce
 *     blank pages);
 *   • `is-paged` + one `.report-page` per logical page let the sheet breaks
 *     land exactly where the builder put them (see global.css);
 *   • `fit: 'width'` scales the builder's CSS-px page width onto the real
 *     printable width without measuring the document's full height — which
 *     would otherwise shrink every page into one unreadable sheet;
 *   • `document.title` becomes the filename Chrome's "Save as PDF" offers;
 *   • and every one of those mutations is undone in `finally`, so a throw
 *     anywhere in `build` can't leave the app stuck in its printing state
 *     with #app hidden.
 */
export function usePagedDocumentPrint(widthPx: number) {
  const printRoot = ref<HTMLElement>()
  const { fitAndPrint } = usePrintFit(printRoot, { marginMm: 10, minScale: 0, fit: 'width' })
  const printing = ref(false)

  /** `documentTitle` is what Chrome's print dialog pre-fills as the
   * "Save as PDF" filename — pass the same name the PDF download uses, so
   * the two routes produce identically named files. */
  async function printPagedDocument(
    documentTitle: string,
    build: (addPage: () => HTMLDivElement) => void,
  ) {
    printing.value = true
    const originalTitle = document.title
    const host = document.createElement('div')
    host.className = 'print-only-document is-paged'
    document.body.appendChild(host)
    // Must go on <body>, not scoped CSS: #app has to disappear entirely for
    // the print pass, and a component's `scoped` styles reach neither <body>
    // nor #app (see the .is-printing-report rules in global.css).
    document.body.classList.add('is-printing-report')
    try {
      buildPagesInHost(host, widthPx, build)
      printRoot.value = host
      document.title = documentTitle
      // Waits for the browser's `afterprint`, not merely for window.print()
      // to return, so the print node isn't torn down below while the
      // browser is still paginating from it (see usePrintFit's own comment).
      await fitAndPrint()
    } finally {
      document.title = originalTitle
      printRoot.value = undefined
      document.body.classList.remove('is-printing-report')
      if (host.isConnected) host.remove()
      printing.value = false
    }
  }

  return { printing, printPagedDocument }
}
