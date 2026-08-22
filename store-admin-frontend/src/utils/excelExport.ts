import ExcelJS from 'exceljs'

/** ExcelJS paper size code for A4. */
const A4_PAPER_SIZE = 9

function triggerDownload(buffer: ExcelJS.Buffer, filename: string) {
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * Sets up a worksheet's print area so opening it in Excel/LibreOffice and
 * printing lands on A4 without the user touching page setup — columns are
 * always scaled to fit one page wide (`fitToWidth: 1`); height is left
 * unbounded (`fitToHeight: 0`) so long tables paginate naturally down the
 * page instead of being squeezed illegibly small.
 */
export function applyA4PageSetup(worksheet: ExcelJS.Worksheet, orientation: 'portrait' | 'landscape' = 'portrait') {
  worksheet.pageSetup = {
    paperSize: A4_PAPER_SIZE,
    orientation,
    fitToPage: true,
    fitToWidth: 1,
    fitToHeight: 0,
    margins: { left: 0.4, right: 0.4, top: 0.5, bottom: 0.5, header: 0.2, footer: 0.2 },
  }
}

export interface ExcelColumn {
  header: string
  key: string
  width?: number
  /** e.g. '#,##0' for a plain integer/currency-style column. */
  numFmt?: string
}

/** Convenience export for a single flat table — the common case (supplier
 * list, wage table, attendance records, monthly detail rows). */
export async function downloadTableExcel(
  filename: string,
  sheetName: string,
  columns: ExcelColumn[],
  rows: Record<string, unknown>[],
  orientation: 'portrait' | 'landscape' = 'portrait',
) {
  const workbook = new ExcelJS.Workbook()
  const worksheet = workbook.addWorksheet(sheetName)
  worksheet.columns = columns.map((c) => ({
    header: c.header,
    key: c.key,
    width: c.width ?? 16,
    style: c.numFmt ? { numFmt: c.numFmt } : undefined,
  }))
  worksheet.addRows(rows)
  const headerRow = worksheet.getRow(1)
  headerRow.font = { bold: true }
  headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEFEF' } }
  worksheet.views = [{ state: 'frozen', ySplit: 1 }]
  applyA4PageSetup(worksheet, orientation)
  const buffer = await workbook.xlsx.writeBuffer()
  triggerDownload(buffer, filename)
}

/** Lower-level escape hatch for layouts that aren't one flat table (e.g. the
 * daily report's meta + stat grid + two side-by-side lists). The callback
 * builds the worksheet directly; A4 page setup is applied automatically
 * afterward unless the callback already set its own pageSetup. */
export async function downloadCustomExcel(
  filename: string,
  sheetName: string,
  build: (worksheet: ExcelJS.Worksheet, workbook: ExcelJS.Workbook) => void,
  orientation: 'portrait' | 'landscape' = 'portrait',
) {
  const workbook = new ExcelJS.Workbook()
  const worksheet = workbook.addWorksheet(sheetName)
  build(worksheet, workbook)
  if (!worksheet.pageSetup?.fitToPage) applyA4PageSetup(worksheet, orientation)
  const buffer = await workbook.xlsx.writeBuffer()
  triggerDownload(buffer, filename)
}
