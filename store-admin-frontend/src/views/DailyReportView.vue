<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Clock, Printer, Refresh, WarningFilled, Lock } from '@element-plus/icons-vue'
import { usePrintFit } from '@/composables/usePrintFit'
import { fetchPaymentMethods, type PaymentMethodDef } from '@/api/masterData'
import { fetchStaffByBranch, type StaffMember } from '@/api/staff'
import {
  fetchDailyReport,
  saveDailyReport,
  saveDailyReportHistorySnapshot,
  fetchDailyReportHistory,
  type DailyReportHistoryEntry,
} from '@/api/dailyReport'
import { useAuthStore } from '@/stores/auth'
import { useBranchStore } from '@/stores/branches'
import { fetchCashRegisterDefaults, type CashRegisterDefaults } from '@/api/cashRegisterDefaults'
import { fetchOrganization } from '@/api/accounts'
import { verifyReportUnlockPassword } from '@/api/reportLock'
import { ApiError } from '@/api/http'
import DailyReportForm, {
  CASH_REGISTER_DENOMINATIONS,
  CASH_REGISTER_EXPECTED_TOTAL,
  CASH_REGISTER_DEFAULTS_CUTOFF_DATE,
  cashRegisterDenominationBreakdown,
  computeCashRegisterTotal,
  computeDerived,
  normalizeDailyReportFormData,
  type DailyReportFormData,
} from '@/components/DailyReportForm.vue'
import { formatCurrency, formatNumber, branchDisplayName, todayJst, formatDateKanji } from '@/utils/format'
import { downloadCustomExcel } from '@/utils/excelExport'
import { renderOffscreenToPdf, el } from '@/utils/pdfExport'
import {
  saveDraft, getDraft, clearDraft, listDrafts, isNetworkFailure, type DailyReportDraft,
} from '@/utils/dailyReportDraft'

const { t, locale } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const branchStore = useBranchStore()
const isAdmin = computed(() => auth.role === 'admin')

const staffList = ref<StaffMember[]>([])
const paymentMethods = ref<PaymentMethodDef[]>([])
const cashRegisterExpectedTotal = ref(CASH_REGISTER_EXPECTED_TOTAL)
const cashRegisterDenominationDefaults = ref<Record<string, number>>({})
const branchId = ref(auth.branchId ?? 'shinsaibashi')
const reportDate = ref(todayJst())
const reportId = ref<number | null>(null)
const submitting = ref(false)

const reportForm = reactive<DailyReportFormData>(normalizeDailyReportFormData({}))
// The report's server-side updated_at as of the last successful load/save —
// compared against the live server value at sync time to tell whether
// someone else saved a newer version while this device was offline.
const reportUpdatedAt = ref<string | null>(null)
// Whether the form currently on screen came from an unsynced local draft
// rather than the server (see loadReport) — shown so the user knows this
// day still needs to reach the server.
const viewingUnsyncedDraft = ref(false)
const pendingDrafts = ref<DailyReportDraft[]>([])
const syncingDrafts = ref(false)

function refreshPendingDrafts() {
  pendingDrafts.value = listDrafts()
}

// Whether the org has opted into locking past reports at all (an admin sets
// a shared unlock password in Settings) — orgs that never configure one
// behave exactly as before this feature existed. A report is locked once
// its date is before today AND this is true.
const reportLockEnabled = ref(false)
function isDateLocked(date: string) {
  return reportLockEnabled.value && date < todayJst()
}
// In-memory only (never persisted) — a page reload or navigating to a
// different date re-locks, matching "unlocked for this editing session
// only". Separate tokens because the main form and the history-edit dialog
// can be looking at two different dates at once.
const mainUnlockToken = ref<string | null>(null)
const historyEditUnlockToken = ref<string | null>(null)
const mainFormLocked = computed(() => isDateLocked(reportDate.value) && !mainUnlockToken.value)
const historyEditFormLocked = computed(
  () => !!historyEditDate.value && isDateLocked(historyEditDate.value) && !historyEditUnlockToken.value,
)

/** Prompts for the shared unlock password and verifies it against the
 * server; returns the short-lived unlock token on success, null if the
 * user cancelled or got it wrong (an error is already shown for the
 * latter). */
async function promptForUnlockToken(): Promise<string | null> {
  let password: string
  try {
    const result = await ElMessageBox.prompt(
      t('dailyReport.reportLockPasswordPrompt'),
      t('dailyReport.reportLockTitle'),
      { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), inputType: 'password' },
    )
    password = result.value
  } catch {
    return null // cancelled
  }
  try {
    const { token } = await verifyReportUnlockPassword(password)
    return token
  } catch {
    ElMessage.error(t('dailyReport.reportLockWrongPassword'))
    return null
  }
}

async function handleUnlockMainForm() {
  const token = await promptForUnlockToken()
  if (token) mainUnlockToken.value = token
}

async function handleUnlockHistoryEdit() {
  const token = await promptForUnlockToken()
  if (token) historyEditUnlockToken.value = token
}

const printRoot = ref<HTMLElement>()
const { fitAndPrint } = usePrintFit(printRoot, { marginMm: 10 })

async function handlePrint() {
  const originalTitle = document.title
  document.title = exportFileName.value
  await fitAndPrint()
  document.title = originalTitle
}

const pdfDownloading = ref(false)

// e.g. "2026年9月18日_心斎橋店_日報" — a distinct naming convention from
// exportFileName above (underscore-separated, full branch name incl. 店,
// kanji date), asked for specifically for the PDF download.
const pdfFileName = computed(() => {
  const branch = branchStore.list.find((b) => b.id === branchId.value)
  const branchName = branchDisplayName(branch, locale.value, branchId.value)
  return `${formatDateKanji(reportDate.value)}_${branchName}_${t('dailyReport.pdfSuffix')}`
})

/** Formats the report's business date without letting the browser timezone
 * move it to the previous/next day. The weekday follows the active UI
 * language: e.g. 2026年9月22日（星期二） / 2026年9月22日（火曜日）. */
function reportDateWithWeekday(dateStr: string) {
  const [year = 1970, month = 1, day = 1] = dateStr.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  const weekday = new Intl.DateTimeFormat(locale.value === 'ja' ? 'ja-JP' : 'zh-CN', {
    weekday: 'long', timeZone: 'UTC',
  }).format(date)
  return `${formatDateKanji(dateStr)}（${weekday}）`
}

/** Calendar-day arithmetic for report dates. UTC is deliberate: these are
 * date-only business keys, not instants, so DST/browser timezone must not
 * change which date is considered "the previous day". */
function shiftReportDate(dateStr: string, days: number) {
  const [year = 1970, month = 1, day = 1] = dateStr.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + days))
  return date.toISOString().slice(0, 10)
}

function formatSignedCurrency(value: number) {
  if (value === 0) return '±¥0'
  return `${value > 0 ? '+' : '-'}${formatCurrency(Math.abs(value))}`
}

// A4 at 96dpi is ~794px wide — same convention as the supplier/monthly-
// analysis PDFs (renderOffscreenToPdf scales this down to fit one page,
// never up, so 1px here stays close to 1 printed px to reason about).
const PDF_PAGE_WIDTH_PX = 794

/** One 面额 row's <tr> for the PDF's cash-register table — quantity always
 * shows the actual total the subtotal was computed from (raw entered count
 * plus, where the cutoff date makes it eligible, the branch's float
 * default), with the breakdown in small text underneath whenever a default
 * contributed, so "数量" can never look inconsistent with "小计". */
function buildCashRegisterRow(
  denomination: number,
  counts: DailyReportFormData['cashRegisterCounts'],
  denominationDefaults: Record<string, number>,
) {
  const breakdown = cashRegisterDenominationBreakdown(denomination, counts, denominationDefaults, reportDate.value)
  const tr = document.createElement('tr')
  const cellStyle = { padding: '3px 5px', borderBottom: '1px solid #ccc' }
  tr.appendChild(el('td', { ...cellStyle, fontWeight: '700' }, formatCurrency(denomination)))
  const qtyCell = el('td', { ...cellStyle, textAlign: 'center' })
  qtyCell.appendChild(el('div', { fontWeight: '700' }, formatNumber(breakdown.totalQuantity)))
  if (breakdown.defaultQuantity) {
    qtyCell.appendChild(el('div', { fontSize: '9px', color: '#444', fontWeight: '400' }, `(${breakdown.rawQuantity}+${breakdown.defaultQuantity})`))
  }
  tr.appendChild(qtyCell)
  tr.appendChild(el('td', { ...cellStyle, textAlign: 'right', fontWeight: '700' }, formatCurrency(breakdown.subtotal)))
  return tr
}

function buildCashRegisterTable(
  denominations: readonly number[],
  counts: DailyReportFormData['cashRegisterCounts'],
  denominationDefaults: Record<string, number>,
) {
  const table = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '12px' })
  const headRow = document.createElement('tr')
  const headStyle = { padding: '3px 5px', borderBottom: '1.5px solid #333', fontWeight: '800' }
  headRow.appendChild(el('th', { ...headStyle, textAlign: 'left' }, t('dailyReport.cashRegisterDenomination')))
  headRow.appendChild(el('th', { ...headStyle, textAlign: 'center' }, t('dailyReport.cashRegisterQuantity')))
  headRow.appendChild(el('th', { ...headStyle, textAlign: 'right' }, t('dailyReport.cashRegisterSubtotal')))
  table.appendChild(headRow)
  for (const denomination of denominations) {
    table.appendChild(buildCashRegisterRow(denomination, counts, denominationDefaults))
  }
  return table
}

/**
 * Builds a compact, purpose-made one-page print document — not a
 * screenshot of the live editable form (that approach kept causing
 * problems: theme-dependent colors, disabled-input styling that read as
 * unreadable "black boxes" in dark mode, and forcing a tall interactive
 * layout to shrink-to-fit made every font tiny). Every color here is a
 * literal black/white/gray, independent of the app's light/dark theme or
 * any Element Plus component, so none of that can recur. Always reads
 * fresh payment-method and cash-register-default master data (passed in
 * by the caller) rather than this view's own page-load-time copies, since
 * DailyReportForm lets staff edit both without leaving this page.
 */
function buildDailyReportPdf(
  root: HTMLElement,
  branchName: string,
  freshMethods: PaymentMethodDef[],
  freshCashDefaults: CashRegisterDefaults,
  previousDay: { date: string; cashRegisterCounts: DailyReportFormData['cashRegisterCounts'] } | null,
) {
  const derived = computeDerived(reportForm, freshMethods)

  root.style.padding = '26px 30px'
  root.style.fontFamily = '"Hiragino Sans", "Microsoft YaHei", sans-serif'
  root.style.color = '#000000'
  root.style.background = '#ffffff'

  // 1. Header: date / branch / "日报" / person in charge -----------------
  const header = el('div', {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
    borderBottom: '2px solid #333', paddingBottom: '10px', marginBottom: '14px',
  })
  const headerLeft = el('div', {})
  headerLeft.appendChild(el('div', { fontSize: '22px', fontWeight: '800' }, `${branchName}　${reportDateWithWeekday(reportDate.value)}`))
  headerLeft.appendChild(el(
    'div', { fontSize: '13px', fontWeight: '700', marginTop: '4px' },
    `${t('dailyReport.personInCharge')}：${staffName(reportForm.personInCharge)}`,
  ))
  header.appendChild(headerLeft)
  header.appendChild(el('div', { fontSize: '18px', fontWeight: '800' }, t('dailyReport.pdfSuffix')))
  root.appendChild(header)

  // 2. Core numbers: 营业额（总）／客数（总）／组数, the reason anyone opens
  // this report — largest, boldest numbers on the page. -------------------
  const heroRow = el('div', { display: 'flex', gap: '10px', marginBottom: '14px' })
  const heroItems: [string, string][] = [
    [t('dailyReport.totalRevenue'), formatCurrency(reportForm.totalRevenue ?? 0)],
    [t('dailyReport.totalCustomers'), formatNumber(reportForm.totalCustomers ?? 0)],
    [t('dailyReport.groupCount'), formatNumber(reportForm.groupCount ?? 0)],
  ]
  for (const [label, value] of heroItems) {
    const box = el('div', { flex: '1', border: '1.5px solid #999', borderRadius: '4px', padding: '10px 12px' })
    box.appendChild(el('div', { fontSize: '11px', fontWeight: '700', marginBottom: '4px' }, label))
    box.appendChild(el('div', { fontSize: '24px', fontWeight: '800' }, value))
    heroRow.appendChild(box)
  }
  root.appendChild(heroRow)

  // 3. AM/PM split — afternoon values come from computeDerived, the same
  // function the on-screen form and Excel export both already use. ------
  const splitGrid = el('div', { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', marginBottom: '16px' })
  const splitItems: [string, string][] = [
    [t('dailyReport.morningRevenue'), formatCurrency(reportForm.morningRevenue ?? 0)],
    [t('dailyReport.morningCustomers'), formatNumber(reportForm.morningCustomers ?? 0)],
    [t('dailyReport.morningGroupCount'), formatNumber(reportForm.morningGroupCount ?? 0)],
    [t('dailyReport.afternoonRevenueAuto'), formatCurrency(derived.afternoonRevenue)],
    [t('dailyReport.afternoonCustomersAuto'), formatNumber(derived.afternoonCustomers)],
    [t('dailyReport.afternoonGroupCountAuto'), formatNumber(derived.afternoonGroupCount)],
  ]
  for (const [label, value] of splitItems) {
    const box = el('div', { border: '1px solid #bbb', borderRadius: '4px', padding: '6px 8px' })
    box.appendChild(el('div', { fontSize: '10px', fontWeight: '700', marginBottom: '2px' }, label))
    box.appendChild(el('div', { fontSize: '15px', fontWeight: '800' }, value))
    splitGrid.appendChild(box)
  }
  root.appendChild(splitGrid)

  // 4. Payment methods — cash always shown (derived.cashAmount, the same
  // auto-calculated value shown on screen); a non-cash method with ¥0 is
  // hidden, but one with a nonzero historical amount stays even if it was
  // since deactivated/deleted (freshMethods already includes those rows —
  // see paymentmethods app's soft-delete). Order follows sortOrder as
  // already returned by fetchPaymentMethods. -----------------------------
  const pmSection = el('div', { marginBottom: '16px' })
  pmSection.appendChild(el(
    'div', { fontSize: '14px', fontWeight: '800', marginBottom: '6px', borderBottom: '1px solid #999', paddingBottom: '3px' },
    t('dailyReport.paymentMethodsTitle'),
  ))
  const pmTable = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '13px' })
  for (const method of freshMethods) {
    const amount = paymentMethodAmount(method, derived)
    if (!method.protected && !amount) continue
    const row = document.createElement('tr')
    row.appendChild(el('td', { padding: '5px 4px', borderBottom: '1px solid #ccc', fontWeight: '700' }, paymentMethodLabel(method)))
    row.appendChild(el('td', { padding: '5px 4px', borderBottom: '1px solid #ccc', textAlign: 'right', fontWeight: '800' }, formatCurrency(amount)))
    pmTable.appendChild(row)
  }
  pmSection.appendChild(pmTable)
  root.appendChild(pmSection)

  // 5. Cash register — 9 denominations split into two side-by-side tables
  // to keep this section's height down; totals use the same
  // computeCashRegisterTotal the screen and Excel export use, and the
  // fixed/expected amount is the branch's current setting, never a
  // hardcoded default. ---------------------------------------------------
  const crSection = el('div', { marginBottom: '16px' })
  crSection.appendChild(el(
    'div', { fontSize: '14px', fontWeight: '800', marginBottom: '6px', borderBottom: '1px solid #999', paddingBottom: '3px' },
    t('dailyReport.cashRegisterTitle'),
  ))
  const crGrid = el('div', { display: 'flex', gap: '18px', marginBottom: '8px' })
  crGrid.appendChild(buildCashRegisterTable(
    CASH_REGISTER_DENOMINATIONS.slice(0, 5), reportForm.cashRegisterCounts, freshCashDefaults.denominationDefaults,
  ))
  crGrid.appendChild(buildCashRegisterTable(
    CASH_REGISTER_DENOMINATIONS.slice(5), reportForm.cashRegisterCounts, freshCashDefaults.denominationDefaults,
  ))
  crSection.appendChild(crGrid)

  const actualTotal = computeCashRegisterTotal(reportForm.cashRegisterCounts, freshCashDefaults.denominationDefaults, reportDate.value)
  const expectedTotal = freshCashDefaults.expectedTotal
  const diff = actualTotal - expectedTotal
  // Same wording/thresholds as the on-screen cashRegister.status, not a
  // separately invented phrasing — over/short/match all read unambiguously
  // without needing a raw +/- number.
  const diffText = diff === 0
    ? t('dailyReport.cashRegisterMatch')
    : diff > 0
      ? t('dailyReport.cashRegisterOver', { amount: formatCurrency(diff) })
      : t('dailyReport.cashRegisterShort', { amount: formatCurrency(Math.abs(diff)) })

  const crSummary = el('div', { display: 'flex', justifyContent: 'space-between', fontSize: '13px', fontWeight: '700' })
  crSummary.appendChild(el('div', {}, `${t('dailyReport.cashRegisterExpected')}：${formatCurrency(expectedTotal)}`))
  crSummary.appendChild(el('div', {}, `${t('dailyReport.cashRegisterActual')}：${formatCurrency(actualTotal)}`))
  crSummary.appendChild(el('div', {}, `${t('dailyReport.cashRegisterDifference')}：${diffText}`))
  crSection.appendChild(crSummary)

  // A shortage/surplus is cumulative: yesterday's mismatch remains in the
  // drawer and therefore appears again in today's actual total even when
  // nothing new went wrong today. Split the current difference into the
  // previous day's carried amount and today's change so the report doesn't
  // incorrectly attribute the whole cumulative shortage to today's shift.
  const carryoverBox = el('div', {
    marginTop: '8px', padding: '7px 10px', border: '1px solid #999', borderRadius: '4px',
    background: '#f7f7f7', fontSize: '12px', fontWeight: '700',
  })
  if (previousDay) {
    const previousActual = computeCashRegisterTotal(
      previousDay.cashRegisterCounts,
      freshCashDefaults.denominationDefaults,
      previousDay.date,
    )
    const previousDifference = previousActual - expectedTotal
    const todayDifference = diff - previousDifference
    const reconciliation = el('div', { display: 'flex', justifyContent: 'space-between', gap: '16px' })
    reconciliation.appendChild(el(
      'div', {},
      `${t('dailyReport.cashRegisterPreviousCarryover')}（${formatDateKanji(previousDay.date)}）：${formatSignedCurrency(previousDifference)}`,
    ))
    reconciliation.appendChild(el(
      'div', { fontWeight: '800' },
      `${t('dailyReport.cashRegisterTodayDifference')}：${formatSignedCurrency(todayDifference)}`,
    ))
    carryoverBox.appendChild(reconciliation)
    carryoverBox.appendChild(el(
      'div', { marginTop: '4px', color: '#444', fontSize: '10px', fontWeight: '400' },
      t('dailyReport.cashRegisterCarryoverHint'),
    ))
  } else {
    carryoverBox.appendChild(el('div', { color: '#444', fontWeight: '600' }, t('dailyReport.cashRegisterPreviousDayUnavailable')))
  }
  crSection.appendChild(carryoverBox)
  root.appendChild(crSection)

  // 6. Expenses — a row with nothing in it at all is a still-blank
  // placeholder, not a real entry, and doesn't print. Long item names or
  // purposes wrap within their own cell instead of forcing the table wider
  // than the page. ---------------------------------------------------------
  const expenseSection = el('div', { marginBottom: '16px' })
  const expenseHeader = el('div', {
    display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontWeight: '800',
    marginBottom: '6px', borderBottom: '1px solid #999', paddingBottom: '3px',
  })
  expenseHeader.appendChild(el('span', {}, t('dailyReport.expenseTitle')))
  expenseHeader.appendChild(el('span', {}, `${t('dailyReport.expenseTotal')}：${formatCurrency(derived.expenseTotal)}`))
  expenseSection.appendChild(expenseHeader)

  const nonEmptyExpenses = reportForm.expenses.filter((row) => row.itemName.trim() || row.amount || row.purpose.trim())
  if (nonEmptyExpenses.length) {
    const expTable = el('table', { width: '100%', borderCollapse: 'collapse', fontSize: '13px', tableLayout: 'fixed' })
    const colgroup = document.createElement('colgroup')
    colgroup.appendChild(el('col', { width: '32%' }))
    colgroup.appendChild(el('col', { width: '18%' }))
    colgroup.appendChild(el('col', { width: '50%' }))
    expTable.appendChild(colgroup)
    for (const expense of nonEmptyExpenses) {
      const row = document.createElement('tr')
      const wrapStyle = { padding: '5px 4px', borderBottom: '1px solid #ccc', wordBreak: 'break-word', overflowWrap: 'break-word' } as const
      row.appendChild(el('td', { ...wrapStyle, fontWeight: '700' }, expense.itemName))
      row.appendChild(el('td', { ...wrapStyle, textAlign: 'right', fontWeight: '700', whiteSpace: 'nowrap' }, formatCurrency(expense.amount ?? 0)))
      row.appendChild(el('td', { ...wrapStyle, fontWeight: '400' }, expense.purpose))
      expTable.appendChild(row)
    }
    expenseSection.appendChild(expTable)
  }
  root.appendChild(expenseSection)

  // 7. Cash remaining — bottom line, boxed and bold. ----------------------
  const remainingBox = el('div', {
    border: '2px solid #333', borderRadius: '4px', padding: '10px 14px',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  })
  remainingBox.appendChild(el('div', { fontSize: '15px', fontWeight: '800' }, t('dailyReport.cashRemaining')))
  remainingBox.appendChild(el('div', { fontSize: '24px', fontWeight: '800' }, formatCurrency(derived.cashRemaining)))
  root.appendChild(remainingBox)
}

async function handleDownloadPdf() {
  pdfDownloading.value = true
  try {
    // Fresh, not this view's page-load-time paymentMethods/cashRegister*
    // refs — DailyReportForm lets staff rename/add/delete payment methods
    // and edit the register defaults/expected total without leaving this
    // page, and a PDF requested right after such a change must reflect it.
    const previousDate = shiftReportDate(reportDate.value, -1)
    const [freshMethods, freshCashDefaults, previousReport] = await Promise.all([
      fetchPaymentMethods(branchId.value),
      fetchCashRegisterDefaults(branchId.value),
      fetchDailyReport(branchId.value, previousDate),
    ])
    // A locally saved previous-day draft is newer than the server copy and
    // should be the carryover source for this device, matching loadReport's
    // existing draft-wins rule. Without either a draft or a saved report we
    // explicitly say the daily split is unavailable instead of pretending
    // yesterday's difference was zero and blaming the whole amount on today.
    const previousDraft = getDraft(branchId.value, previousDate)
    const previousDay = previousDraft
      ? { date: previousDate, cashRegisterCounts: previousDraft.data.cashRegisterCounts }
      : previousReport.id
        ? { date: previousDate, cashRegisterCounts: previousReport.cashRegisterCounts }
        : null
    const branch = branchStore.list.find((b) => b.id === branchId.value)
    const branchName = branchDisplayName(branch, locale.value, branchId.value)
    await renderOffscreenToPdf(
      pdfFileName.value,
      PDF_PAGE_WIDTH_PX,
      (root) => buildDailyReportPdf(root, branchName, freshMethods, freshCashDefaults, previousDay),
    )
  } finally {
    pdfDownloading.value = false
  }
}

const historyDialogVisible = ref(false)
const historyLoading = ref(false)
const historyEntries = ref<DailyReportHistoryEntry[]>([])
// Browsing history by business date (independent of whatever date the main
// form happens to have loaded) — otherwise a day edited many times just
// shows as an undifferentiated pile of timestamps with no way to jump to
// a different date without leaving the dialog.
const historyFilterDate = ref('')
const historyEditDialogVisible = ref(false)
const historyEditSubmitting = ref(false)
const historyEditForm = ref<DailyReportFormData | null>(null)
const historyEditDate = ref('')

function staffName(id: string) {
  return staffList.value.find((s) => s.id === id)?.name ?? id
}

function branchLabel(id: string) {
  return branchDisplayName(branchStore.list.find((b) => b.id === id), locale.value, id)
}

function formatDateTime(iso: string) {
  const date = new Date(iso)
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function loadReport() {
  const [staff, methods, seed, cashRegisterDefaults] = await Promise.all([
    fetchStaffByBranch(branchId.value),
    fetchPaymentMethods(branchId.value),
    fetchDailyReport(branchId.value, reportDate.value),
    fetchCashRegisterDefaults(branchId.value),
  ])

  staffList.value = staff
  paymentMethods.value = methods
  // Only used for the Excel export — DailyReportForm.vue fetches and owns
  // its own copy for the on-screen comparison/editing.
  cashRegisterExpectedTotal.value = cashRegisterDefaults.expectedTotal
  cashRegisterDenominationDefaults.value = cashRegisterDefaults.denominationDefaults

  reportId.value = seed.id
  reportUpdatedAt.value = seed.updatedAt

  // An unsynced local draft for this exact branch+date wins over whatever
  // the server just returned — that server copy predates the offline edit
  // (or the report doesn't exist there yet), so showing it instead would
  // make the user think their earlier work was lost.
  const draft = getDraft(branchId.value, reportDate.value)
  viewingUnsyncedDraft.value = !!draft
  const source = draft ? draft.data : seed

  reportForm.personInCharge = source.personInCharge
  reportForm.totalRevenue = source.totalRevenue
  reportForm.totalCustomers = source.totalCustomers
  reportForm.groupCount = source.groupCount
  reportForm.morningRevenue = source.morningRevenue
  reportForm.morningCustomers = source.morningCustomers
  reportForm.morningGroupCount = source.morningGroupCount
  reportForm.paymentAmounts = { ...source.paymentAmounts }
  reportForm.expenses = source.expenses.map((e) => ({ ...e }))
  reportForm.cashRegisterCounts = { ...source.cashRegisterCounts }
}

onMounted(async () => {
  await branchStore.ensureLoaded()
  if (!isAdmin.value) {
    branchId.value = auth.branchId ?? branchId.value
  } else if (typeof route.query.branch === 'string' && route.query.branch) {
    branchId.value = route.query.branch
  }
  if (typeof route.query.date === 'string' && route.query.date) {
    reportDate.value = route.query.date
  }
  await loadReport()
  fetchOrganization().then((org) => { reportLockEnabled.value = org.reportUnlockPasswordSet }).catch(() => {})
  refreshPendingDrafts()
  // Best-effort: try once at page load (in case connectivity came back while
  // the tab was closed) and again whenever the browser reports the network
  // coming back up. Both are silent unless there's actually a conflict to
  // ask the user about — see syncAllDrafts.
  void syncAllDrafts()
  window.addEventListener('online', syncAllDrafts)
})

onBeforeUnmount(() => {
  window.removeEventListener('online', syncAllDrafts)
})

watch([branchId, reportDate], () => {
  mainUnlockToken.value = null
  loadReport()
})

async function handleSubmit() {
  submitting.value = true
  try {
    const derived = computeDerived(reportForm, paymentMethods.value)
    const snapshot = JSON.parse(JSON.stringify(reportForm))
    try {
      reportId.value = await saveDailyReport(
        reportId.value, branchId.value, reportDate.value, snapshot, mainUnlockToken.value ?? undefined,
      )
      await saveDailyReportHistorySnapshot({
        branchId: branchId.value,
        date: reportDate.value,
        cashRemaining: derived.cashRemaining,
        data: snapshot,
      })
      clearDraft(branchId.value, reportDate.value)
      refreshPendingDrafts()
      viewingUnsyncedDraft.value = false
      const fresh = await fetchDailyReport(branchId.value, reportDate.value)
      reportUpdatedAt.value = fresh.updatedAt
      ElMessage.success(t('dailyReport.savedSuccess'))
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        // The unlock token expired (or was never obtained) between opening
        // the report and hitting save — re-lock so the button reappears
        // instead of silently retrying as if it were a network blip.
        mainUnlockToken.value = null
        ElMessage.error(t('dailyReport.reportLockExpired'))
        return
      }
      if (!isNetworkFailure(err)) throw err
      // Offline (or the server is unreachable) — keep the entry instead of
      // losing it. `reportUpdatedAt` is the last version we know the server
      // actually has, so syncAllDrafts can tell later whether someone else
      // also saved this day while we were offline.
      saveDraft({
        branchId: branchId.value, date: reportDate.value, data: snapshot,
        baseUpdatedAt: reportUpdatedAt.value, savedLocallyAt: new Date().toISOString(),
      })
      refreshPendingDrafts()
      viewingUnsyncedDraft.value = true
      ElMessage({ type: 'warning', message: t('dailyReport.savedLocallyOffline'), duration: 5000 })
    }
  } finally {
    submitting.value = false
  }
}

/** Pushes one offline draft to the server. Returns whether it synced clean,
 * hit a conflict (the server has a newer save than the draft was based on),
 * or simply failed again (still offline) — the last two both leave the
 * draft in place for a later retry. A real validation error (not a network
 * failure) is left to propagate — silently discarding a draft over that
 * would lose real data instead of protecting it. */
async function syncOneDraft(draft: DailyReportDraft): Promise<'synced' | 'conflict' | 'still-offline'> {
  const current = await fetchDailyReport(draft.branchId, draft.date)
  if (draft.baseUpdatedAt && current.updatedAt && current.updatedAt !== draft.baseUpdatedAt) {
    return 'conflict'
  }
  const methods = await fetchPaymentMethods(draft.branchId)
  const derived = computeDerived(draft.data, methods)
  await saveDailyReport(current.id, draft.branchId, draft.date, draft.data)
  await saveDailyReportHistorySnapshot({
    branchId: draft.branchId, date: draft.date, cashRemaining: derived.cashRemaining, data: draft.data,
  })
  clearDraft(draft.branchId, draft.date)
  return 'synced'
}

async function syncAllDrafts() {
  if (syncingDrafts.value) return
  syncingDrafts.value = true
  try {
    const drafts = listDrafts()
    let syncedAny = false
    for (const draft of drafts) {
      let outcome: 'synced' | 'conflict' | 'still-offline'
      try {
        outcome = await syncOneDraft(draft)
      } catch (err) {
        if (!isNetworkFailure(err)) throw err
        outcome = 'still-offline'
      }
      if (outcome === 'synced') syncedAny = true
      else if (outcome === 'conflict') await resolveDraftConflict(draft)
    }
    refreshPendingDrafts()
    if (syncedAny) {
      ElMessage.success(t('dailyReport.draftSyncSuccess'))
      if (!getDraft(branchId.value, reportDate.value)) await loadReport()
    }
  } finally {
    syncingDrafts.value = false
  }
}

/** The server has a save newer than what this draft was based on — ask
 * which one should win rather than guessing. "Use local" force-pushes the
 * draft over it; "use server" just discards the draft. Leaving the dialog
 * without choosing (Escape/backdrop) keeps the draft pending — it'll be
 * asked about again on the next sync attempt, nothing is lost either way. */
async function resolveDraftConflict(draft: DailyReportDraft) {
  try {
    await ElMessageBox.confirm(
      t('dailyReport.draftConflictMessage', { date: draft.date }),
      t('dailyReport.draftConflictTitle'),
      {
        type: 'warning',
        confirmButtonText: t('dailyReport.draftConflictUseLocal'),
        cancelButtonText: t('dailyReport.draftConflictUseServer'),
        distinguishCancelAndClose: true,
      },
    )
    const current = await fetchDailyReport(draft.branchId, draft.date)
    const methods = await fetchPaymentMethods(draft.branchId)
    const derived = computeDerived(draft.data, methods)
    await saveDailyReport(current.id, draft.branchId, draft.date, draft.data)
    await saveDailyReportHistorySnapshot({
      branchId: draft.branchId, date: draft.date, cashRemaining: derived.cashRemaining, data: draft.data,
    })
    clearDraft(draft.branchId, draft.date)
  } catch (action) {
    if (action === 'cancel') clearDraft(draft.branchId, draft.date)
    // 'close' (Escape/backdrop): leave the draft pending, decide next time.
  }
}

async function refreshHistoryList() {
  historyLoading.value = true
  try {
    historyEntries.value = await fetchDailyReportHistory(branchId.value, historyFilterDate.value)
  } finally {
    historyLoading.value = false
  }
}

async function openHistory() {
  historyFilterDate.value = reportDate.value
  historyDialogVisible.value = true
  await refreshHistoryList()
}

watch(historyFilterDate, () => {
  if (historyDialogVisible.value) refreshHistoryList()
})

function openHistoryEdit(entry: DailyReportHistoryEntry) {
  historyEditForm.value = JSON.parse(JSON.stringify(entry.data)) as DailyReportFormData
  historyEditDate.value = entry.date
  historyEditUnlockToken.value = null
  historyEditDialogVisible.value = true
}

async function handleSaveHistoryEdit() {
  if (!historyEditForm.value) return
  historyEditSubmitting.value = true
  try {
    const derived = computeDerived(historyEditForm.value, paymentMethods.value)
    const snapshot = JSON.parse(JSON.stringify(historyEditForm.value))
    // Always the snapshot's own business date — historyFilterDate can
    // differ from the main form's reportDate, and saving under the wrong
    // one would silently file the edit under the wrong day. Re-fetch to
    // find whether a live report already exists for that date so we
    // update it instead of violating the branch+date unique constraint.
    const existing = await fetchDailyReport(branchId.value, historyEditDate.value)
    let savedId: number
    try {
      savedId = await saveDailyReport(
        existing.id, branchId.value, historyEditDate.value, snapshot, historyEditUnlockToken.value ?? undefined,
      )
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        historyEditUnlockToken.value = null
        ElMessage.error(t('dailyReport.reportLockExpired'))
        return
      }
      throw err
    }
    if (historyEditDate.value === reportDate.value) reportId.value = savedId
    await saveDailyReportHistorySnapshot({
      branchId: branchId.value,
      date: historyEditDate.value,
      cashRemaining: derived.cashRemaining,
      data: snapshot,
    })
    ElMessage.success(t('dailyReport.savedSuccess'))
    historyEditDialogVisible.value = false
    await refreshHistoryList()
    if (historyEditDate.value === reportDate.value) await loadReport()
  } finally {
    historyEditSubmitting.value = false
  }
}

// e.g. "心斋桥-20260816-日报表" — trailing 店/店 dropped per the naming
// convention asked for, so it reads as a short branch name, not "XX店店".
const exportFileName = computed(() => {
  const branch = branchStore.list.find((b) => b.id === branchId.value)
  const shortName = branchDisplayName(branch, locale.value, branchId.value).replace(/店$/, '')
  const compactDate = reportDate.value.replace(/-/g, '')
  return `${shortName}-${compactDate}-${t('dailyReport.exportFileSuffix')}`
})

function paymentMethodLabel(method: PaymentMethodDef) {
  return method.customName || (method.i18nKey ? t(method.i18nKey) : '')
}

function paymentMethodAmount(method: PaymentMethodDef, derived: ReturnType<typeof computeDerived>) {
  return method.protected ? derived.cashAmount : (reportForm.paymentAmounts[String(method.id)] ?? 0)
}

async function handleDownload() {
  const derived = computeDerived(reportForm, paymentMethods.value)
  await downloadCustomExcel(exportFileName.value, t('dailyReport.pageTitle'), (ws) => {
    ws.addRow([branchLabel(branchId.value), reportDate.value, t('dailyReport.personInCharge'), staffName(reportForm.personInCharge)])
    ws.getRow(1).font = { bold: true }
    ws.addRow([])

    ws.addRow([t('dailyReport.totalRevenue'), t('dailyReport.totalCustomers'), t('dailyReport.groupCount')]).font = { bold: true }
    ws.addRow([reportForm.totalRevenue, reportForm.totalCustomers, reportForm.groupCount])
    ws.addRow([t('dailyReport.morningRevenue'), t('dailyReport.morningCustomers'), t('dailyReport.morningGroupCount')]).font = { bold: true }
    ws.addRow([reportForm.morningRevenue, reportForm.morningCustomers, reportForm.morningGroupCount])
    ws.addRow([t('dailyReport.afternoonRevenueAuto'), t('dailyReport.afternoonCustomersAuto'), t('dailyReport.afternoonGroupCountAuto')]).font = { bold: true }
    ws.addRow([derived.afternoonRevenue, derived.afternoonCustomers, derived.afternoonGroupCount])
    ws.addRow([])

    ws.addRow([t('dailyReport.paymentMethodsTitle')]).font = { bold: true }
    for (const method of paymentMethods.value) {
      ws.addRow([paymentMethodLabel(method), paymentMethodAmount(method, derived)])
    }
    ws.addRow([])

    ws.addRow([t('dailyReport.expenseTitle'), null, null, `${t('dailyReport.expenseTotal')} ${derived.expenseTotal}`]).font = { bold: true }
    for (const expense of reportForm.expenses) {
      ws.addRow([expense.itemName, expense.amount, expense.purpose])
    }
    ws.addRow([])

    ws.addRow([t('dailyReport.cashRemaining'), derived.cashRemaining]).font = { bold: true }
    ws.addRow([])
    ws.addRow([t('dailyReport.cashRegisterTitle')]).font = { bold: true }
    ws.addRow([
      t('dailyReport.cashRegisterDenomination'),
      t('dailyReport.cashRegisterQuantity'),
      t('dailyReport.cashRegisterSubtotal'),
    ]).font = { bold: true }
    const defaultsEligible = reportDate.value >= CASH_REGISTER_DEFAULTS_CUTOFF_DATE
    for (const denomination of CASH_REGISTER_DENOMINATIONS) {
      const rawQuantity = reportForm.cashRegisterCounts[String(denomination)] ?? 0
      const defaultQuantity = defaultsEligible ? (cashRegisterDenominationDefaults.value[String(denomination)] ?? 0) : 0
      ws.addRow([denomination, rawQuantity, denomination * (rawQuantity + defaultQuantity)])
    }
    const cashRegisterTotal = computeCashRegisterTotal(reportForm.cashRegisterCounts, cashRegisterDenominationDefaults.value, reportDate.value)
    ws.addRow([t('dailyReport.cashRegisterExpected'), cashRegisterExpectedTotal.value])
    ws.addRow([t('dailyReport.cashRegisterActual'), cashRegisterTotal])
    ws.addRow([t('dailyReport.cashRegisterDifference'), cashRegisterTotal - cashRegisterExpectedTotal.value])
    ws.columns.forEach((col) => { col.width = 18 })
  })
}
</script>

<template>
  <div class="daily-report-view">
    <div class="card form-card">
      <div class="form-header">
        <div class="form-header-controls">
          <el-date-picker v-model="reportDate" type="date" size="default" :clearable="false" value-format="YYYY-MM-DD" />
          <el-select v-if="isAdmin" v-model="branchId" size="default" style="width: 140px">
            <el-option v-for="b in branchStore.list" :key="b.id" :value="b.id" :label="branchDisplayName(b, locale)" />
          </el-select>
          <span v-else class="branch-badge">{{ branchLabel(branchId) }}</span>
        </div>
        <div class="no-print form-header-actions">
          <el-button :icon="Printer" @click="handlePrint">{{ t('common.print') }}</el-button>
          <el-button :icon="Download" @click="handleDownload">{{ t('common.downloadExcel') }}</el-button>
          <el-button :icon="Download" :loading="pdfDownloading" @click="handleDownloadPdf">{{ t('common.downloadPdf') }}</el-button>
        </div>
      </div>

      <div v-if="pendingDrafts.length" class="no-print draft-banner">
        <el-icon><WarningFilled /></el-icon>
        <span>
          {{ viewingUnsyncedDraft ? t('dailyReport.viewingUnsyncedDraft') : '' }}
          {{ t('dailyReport.pendingDraftsCount', { count: pendingDrafts.length }) }}
        </span>
        <el-button size="small" :icon="Refresh" :loading="syncingDrafts" @click="syncAllDrafts">
          {{ t('dailyReport.syncNow') }}
        </el-button>
      </div>

      <div v-if="mainFormLocked" class="no-print report-lock-banner">
        <el-icon><Lock /></el-icon>
        <span>{{ t('dailyReport.reportLockedHint') }}</span>
        <el-button size="small" type="primary" @click="handleUnlockMainForm">
          {{ t('dailyReport.reportLockUnlock') }}
        </el-button>
      </div>

      <div ref="printRoot">
        <DailyReportForm
          v-model:data="reportForm" :branch-id="branchId" :report-date="reportDate"
          :readonly="mainFormLocked" allow-cash-register-default-edits
        />
      </div>

      <div class="submit-row no-print">
        <el-button :icon="Clock" @click="openHistory">{{ t('dailyReport.viewHistory') }}</el-button>
        <el-button type="primary" :loading="submitting" :disabled="mainFormLocked" @click="handleSubmit">
          {{ t('dailyReport.submit') }}
        </el-button>
      </div>
    </div>

    <el-dialog v-model="historyDialogVisible" :title="t('dailyReport.historyTitle')" width="640px">
      <div class="history-filter">
        <el-date-picker v-model="historyFilterDate" type="date" :clearable="false" value-format="YYYY-MM-DD" />
        <span class="history-count-hint" :class="{ 'is-empty': !historyEntries.length }">
          {{
            historyEntries.length
              ? t('dailyReport.historyCountHint', { date: historyFilterDate, count: historyEntries.length })
              : t('dailyReport.historyCountEmpty', { date: historyFilterDate })
          }}
        </span>
      </div>
      <el-table
        :data="historyEntries"
        v-loading="historyLoading"
        :empty-text="t('dailyReport.historyEmpty')"
        class="history-table"
        @row-click="openHistoryEdit"
      >
        <el-table-column :label="t('dailyReport.historySavedAt')" min-width="150">
          <template #default="{ row }">{{ formatDateTime(row.savedAt) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.historyEditedBy')" width="100">
          <template #default="{ row }">{{ row.editedBy }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.personInCharge')" width="100">
          <template #default="{ row }">{{ staffName(row.personInCharge) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.totalRevenue')" width="110">
          <template #default="{ row }">{{ formatCurrency(row.totalRevenue) }}</template>
        </el-table-column>
        <el-table-column :label="t('dailyReport.cashRemaining')" min-width="110">
          <template #default="{ row }">{{ formatCurrency(row.cashRemaining) }}</template>
        </el-table-column>
      </el-table>
      <p v-if="historyEntries.length" class="history-hint">{{ t('dailyReport.historyRowHint') }}</p>
    </el-dialog>

    <el-dialog
      v-model="historyEditDialogVisible"
      :title="t('dailyReport.editHistoryTitle')"
      width="960px"
      class="history-edit-dialog"
      append-to-body
    >
      <div v-if="historyEditFormLocked" class="no-print report-lock-banner">
        <el-icon><Lock /></el-icon>
        <span>{{ t('dailyReport.reportLockedHint') }}</span>
        <el-button size="small" type="primary" @click="handleUnlockHistoryEdit">
          {{ t('dailyReport.reportLockUnlock') }}
        </el-button>
      </div>
      <DailyReportForm
        v-if="historyEditForm" v-model:data="historyEditForm" :branch-id="branchId"
        :report-date="historyEditDate" :readonly="historyEditFormLocked"
      />
      <template #footer>
        <el-button @click="historyEditDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="historyEditSubmitting" :disabled="historyEditFormLocked" @click="handleSaveHistoryEdit">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<style scoped>
.daily-report-view {
  display: flex;
}

.form-card {
  width: 100%;
  max-width: 960px;
  background: var(--surface);
  border-radius: var(--radius-md);
  padding: 20px 22px;
  box-shadow: var(--shadow-soft);
}

.form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.form-header-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.form-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.draft-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--warning-light, #fdf3e2);
  border: 1px solid var(--warning, #b7791f);
  color: var(--warning, #b7791f);
  border-radius: var(--radius-sm);
  padding: 8px 14px;
  margin-bottom: 16px;
  font-size: 12.5px;
}

.draft-banner span {
  flex: 1;
}

.report-lock-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  padding: 8px 14px;
  margin-bottom: 16px;
  font-size: 12.5px;
}

.report-lock-banner span {
  flex: 1;
}

@media print {
  @page {
    size: A4 portrait;
    margin: 10mm;
  }
}

.branch-badge {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 14px;
  height: 32px;
  display: inline-flex;
  align-items: center;
}

.submit-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.history-table :deep(.el-table__row) {
  cursor: pointer;
}

.history-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 10px 2px 0;
}

.history-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.history-count-hint {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}

.history-count-hint.is-empty {
  font-weight: 400;
  color: var(--text-tertiary);
}

</style>
