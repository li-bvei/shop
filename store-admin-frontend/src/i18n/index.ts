import { createI18n } from 'vue-i18n'
import zh from './locales/zh'
import ja from './locales/ja'

export type AppLocale = 'zh' | 'ja'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'zh',
  messages: { zh, ja },
})

export default i18n
