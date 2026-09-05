import { defineStore } from 'pinia'
import { http, setTokens, clearTokens, getAccessToken, ApiError } from '@/api/http'
import { usePreferenceStore } from './preference'

export type UserRole = 'admin' | 'branch' | 'staff'

interface MeResponse {
  account: string
  displayName: string
  role: UserRole
  branchId: string | null
  staffMemberId: string | null
  isSuperuser: boolean
  enabledFeatures: string[]
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    isLoggedIn: false,
    account: '',
    displayName: '',
    role: 'branch' as UserRole,
    branchId: null as string | null,
    staffMemberId: null as string | null,
    isSuperuser: false,
    // Module keys this account's Organization is entitled to. Empty until
    // loadMe() runs; the router gate and sidebar read it.
    enabledFeatures: [] as string[],
  }),
  getters: {
    hasFeature: (state) => (feature: string) => state.enabledFeatures.includes(feature),
  },
  actions: {
    async login(account: string, password: string) {
      try {
        const { access, refresh } = await http.post<{ access: string; refresh: string }>('/token/', {
          username: account,
          password,
        })
        setTokens(access, refresh)
      } catch {
        // Same error for "no such account" and "wrong password" — a failed
        // login can't be used to enumerate valid account names.
        throw new Error('invalid-credentials')
      }
      await this.loadMe()
      // The boot-time preference.init() in main.ts already ran with no
      // token and settled on defaults — re-run it now that one exists so
      // this account's actual saved locale/theme take effect immediately.
      await usePreferenceStore().init()
    },
    async loadMe() {
      const me = await http.get<MeResponse>('/auth/me/')
      this.isLoggedIn = true
      this.account = me.account
      this.displayName = me.displayName
      this.role = me.role
      this.branchId = me.branchId
      this.staffMemberId = me.staffMemberId
      this.isSuperuser = me.isSuperuser ?? false
      this.enabledFeatures = me.enabledFeatures ?? []
    },
    /** Called once at app boot — restores the session from a stored token
     * (survives a page reload) instead of forcing a fresh login every time. */
    async restoreSession() {
      if (!getAccessToken()) return
      try {
        await this.loadMe()
      } catch (err) {
        if (err instanceof ApiError) clearTokens()
      }
    },
    logout() {
      clearTokens()
      this.isLoggedIn = false
      this.account = ''
      this.displayName = ''
      this.role = 'branch'
      this.branchId = null
      this.staffMemberId = null
      this.isSuperuser = false
      this.enabledFeatures = []
    },
  },
})
