import { computed } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import ja from 'element-plus/es/locale/lang/ja'
import { usePreferenceStore } from '@/stores/preference'

const NUMERIC_MONTHS: [string, string, string, string, string, string, string, string, string, string, string, string] = [
  '1',
  '2',
  '3',
  '4',
  '5',
  '6',
  '7',
  '8',
  '9',
  '10',
  '11',
  '12',
]

function withNumericMonths<T extends { el: { datepicker: Record<string, unknown> } }>(locale: T): T {
  const datepicker = locale.el.datepicker as Record<string, unknown>
  const monthKeys = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'] as const
  const months: Record<string, string> = {}
  monthKeys.forEach((key, i) => {
    months[key] = NUMERIC_MONTHS[i]!
  })

  return {
    ...locale,
    el: {
      ...locale.el,
      datepicker: {
        ...datepicker,
        months,
        month1: NUMERIC_MONTHS[0],
        month2: NUMERIC_MONTHS[1],
        month3: NUMERIC_MONTHS[2],
        month4: NUMERIC_MONTHS[3],
        month5: NUMERIC_MONTHS[4],
        month6: NUMERIC_MONTHS[5],
        month7: NUMERIC_MONTHS[6],
        month8: NUMERIC_MONTHS[7],
        month9: NUMERIC_MONTHS[8],
        month10: NUMERIC_MONTHS[9],
        month11: NUMERIC_MONTHS[10],
        month12: NUMERIC_MONTHS[11],
      },
    },
  }
}

const zhCnNumeric = withNumericMonths(zhCn)
const jaNumeric = withNumericMonths(ja)

export function useElLocale() {
  const preference = usePreferenceStore()
  return computed(() => (preference.locale === 'ja' ? jaNumeric : zhCnNumeric))
}
