import '@/assets/styles/variables.css'
import 'element-plus/dist/index.css'
import '@/assets/styles/element-overrides.css'
import '@/assets/styles/global.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import '@/echarts'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { usePreferenceStore } from './stores/preference'
import { useAuthStore } from './stores/auth'

const app = createApp(App)

app.use(createPinia())
app.use(i18n)
app.use(ElementPlus)
app.component('v-chart', VChart)

// A single bad row (a missing DTO field, a malformed number) should never be
// able to take down the whole app's navigation — without this, an uncaught
// render-time exception can leave Vue's internal patch state broken, and
// every subsequent route change silently does nothing (the sidebar highlight
// moves but the page never updates). This is a backstop, not a substitute
// for fixing the actual bug — it just keeps the app usable in the meantime.
let lastUnexpectedErrorAt = 0
function reportUnexpectedError(error: unknown) {
  console.error(error)
  const now = Date.now()
  if (now - lastUnexpectedErrorAt < 4000) return // avoid toast-spamming a repeating failure
  lastUnexpectedErrorAt = now
  ElMessage.error(i18n.global.t('common.unexpectedError'))
}

app.config.errorHandler = (err) => reportUnexpectedError(err)
// Vue's own scheduler routes most render/effect errors through errorHandler
// above, but a rejected promise outside any Vue-tracked async context (e.g.
// a plain fetch chain) surfaces only as an unhandledrejection event instead.
window.addEventListener('unhandledrejection', (event) => reportUnexpectedError(event.reason))

const auth = useAuthStore()
const preference = usePreferenceStore()

// Both must resolve before router is installed — app.use(router) is what
// fires the router's first navigation (and its beforeEach guard), not
// app.mount(). Installing it any earlier would let that guard run while
// isLoggedIn is still false, bouncing a still-valid session to /login
// before the stored token had a chance to be checked.
Promise.all([auth.restoreSession(), preference.init()]).finally(() => {
  app.use(router)
  app.mount('#app')
})
