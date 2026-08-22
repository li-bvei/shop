import { defineStore } from 'pinia'
import { fetchUserPreference, saveUserPreference, type AppTheme } from '@/api/userSettings'
import { getAccessToken } from '@/api/http'
import i18n, { type AppLocale } from '@/i18n'

function applyTheme(theme: AppTheme) {
  document.documentElement.setAttribute('data-theme', theme)
}

function applyLocale(locale: AppLocale) {
  i18n.global.locale.value = locale
}

export const usePreferenceStore = defineStore('preference', {
  state: () => ({
    locale: 'zh' as AppLocale,
    theme: 'light' as AppTheme,
    ready: false,
  }),
  actions: {
    /** Called at app boot (only meaningful with a stored token — an
     * anonymous visitor on the login page has no account to fetch a
     * preference for) and again right after a fresh login succeeds. */
    async init() {
      if (getAccessToken()) {
        try {
          const preference = await fetchUserPreference()
          this.locale = preference.locale
          this.theme = preference.theme
        } catch {
          // Stale/invalid token — auth.restoreSession() handles clearing it;
          // fall through to defaults so the UI still renders something.
        }
      }
      applyLocale(this.locale)
      applyTheme(this.theme)
      this.ready = true
    },
    async setLocale(locale: AppLocale) {
      this.locale = locale
      applyLocale(locale)
      await saveUserPreference({ locale: this.locale, theme: this.theme })
    },
    async setTheme(theme: AppTheme) {
      this.theme = theme
      applyTheme(theme)
      await saveUserPreference({ locale: this.locale, theme: this.theme })
    },
    async toggleTheme() {
      await this.setTheme(this.theme === 'light' ? 'dark' : 'light')
    },
  },
})
