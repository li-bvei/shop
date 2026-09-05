import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getGuestToken } from '@/api/guest'

/** Where an account belongs by default. A platform super admin lives
 * entirely in the /platform console — never the per-chain operational
 * screens. */
function homeRoute() {
  const auth = useAuthStore()
  if (auth.isSuperuser) return { name: 'platform-overview' }
  return auth.role === 'staff' ? { name: 'my-availability' } : { name: 'dashboard' }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      // Public loyalty-card pages — outside AppShell, no auth. Japanese-first.
      path: '/pc',
      component: () => import('@/layouts/GuestShell.vue'),
      children: [
        {
          path: 'register',
          name: 'guest-register',
          component: () => import('@/views/guest/GuestRegisterView.vue'),
          meta: { public: true },
          // A returning customer whose browser still holds the card skips
          // the form entirely — scanning the printed sticker again just
          // reopens their card.
          beforeEnter: (to) => (getGuestToken() && to.query.new === undefined ? { name: 'guest-card' } : true),
        },
        {
          path: 'card',
          name: 'guest-card',
          component: () => import('@/views/guest/GuestCardView.vue'),
          meta: { public: true },
        },
        {
          path: 'login',
          name: 'guest-login',
          component: () => import('@/views/guest/GuestLoginView.vue'),
          meta: { public: true },
        },
      ],
    },
    {
      // Counter-tablet kiosk pages — logged in (staff/branch/admin), but
      // full-screen with no admin chrome, so not AppShell children.
      path: '/kiosk/verify',
      name: 'promo-verify',
      component: () => import('@/views/staff/PromoVerifyView.vue'),
      meta: { roles: ['staff', 'branch', 'admin'], feature: 'promotions' },
    },
    {
      path: '/kiosk/redeem',
      name: 'promo-redeem',
      component: () => import('@/views/staff/PromoRedeemView.vue'),
      meta: { roles: ['staff', 'branch', 'admin'], feature: 'promotions' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      redirect: () => homeRoute(),
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'lottery',
          name: 'lottery',
          component: () => import('@/views/LotteryView.vue'),
          meta: { roles: ['admin', 'branch', 'staff'] },
        },
        {
          path: 'monthly-analysis',
          name: 'monthly-analysis',
          component: () => import('@/views/MonthlyAnalysisView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'daily-report',
          name: 'daily-report',
          component: () => import('@/views/DailyReportView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'purchasing',
          name: 'purchasing',
          component: () => import('@/views/PurchasingView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'purchasing' },
        },
        {
          path: 'suppliers',
          name: 'suppliers',
          component: () => import('@/views/SuppliersView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'suppliers' },
        },
        {
          path: 'products',
          name: 'products',
          component: () => import('@/views/ProductsView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'products' },
        },
        {
          path: 'inventory',
          name: 'inventory',
          component: () => import('@/views/InventoryView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'inventory' },
        },
        {
          path: 'staff',
          name: 'staff',
          component: () => import('@/views/StaffView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'scheduling',
          name: 'scheduling',
          component: () => import('@/views/SchedulingView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'scheduling' },
        },
        {
          path: 'wages',
          name: 'wages',
          component: () => import('@/views/WagesView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'wages' },
        },
        {
          path: 'promotions',
          name: 'promotions',
          component: () => import('@/views/PromotionsView.vue'),
          meta: { roles: ['admin', 'branch'], feature: 'promotions' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'my-availability',
          name: 'my-availability',
          component: () => import('@/views/staff/MyAvailabilityView.vue'),
          meta: { roles: ['staff'] },
        },
        {
          path: 'my-shifts',
          name: 'my-shifts',
          component: () => import('@/views/staff/MyShiftsView.vue'),
          meta: { roles: ['staff'], feature: 'scheduling' },
        },
        {
          path: 'my-wages',
          name: 'my-wages',
          component: () => import('@/views/staff/MyWagesView.vue'),
          meta: { roles: ['staff'], feature: 'wages' },
        },
        {
          path: 'my-password',
          name: 'my-password',
          component: () => import('@/views/staff/MyPasswordView.vue'),
          meta: { roles: ['staff'] },
        },
        {
          path: 'feature-unavailable',
          name: 'feature-unavailable',
          component: () => import('@/views/FeatureUnavailableView.vue'),
        },
        {
          path: 'platform/overview',
          name: 'platform-overview',
          component: () => import('@/views/platform/PlatformOverviewView.vue'),
          meta: { superuser: true },
        },
        {
          path: 'platform/manage',
          name: 'platform-manage',
          component: () => import('@/views/platform/PlatformFeaturesView.vue'),
          meta: { superuser: true },
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return homeRoute()
  }
  // Platform super admin lives only in the /platform console — the
  // per-chain operational screens (dashboards, daily reports, …) aren't
  // theirs to run.
  if (auth.isLoggedIn && auth.isSuperuser && !String(to.path).startsWith('/platform/')) {
    return homeRoute()
  }
  // Route-level role gate — mirrors the backend's own permission checks,
  // never a substitute for them (every one of these endpoints is also
  // independently enforced server-side).
  const allowedRoles = to.meta.roles as string[] | undefined
  if (allowedRoles && auth.isLoggedIn && !allowedRoles.includes(auth.role)) {
    return homeRoute()
  }
  // Platform super-admin screen.
  if (to.meta.superuser && auth.isLoggedIn && !auth.isSuperuser) {
    return homeRoute()
  }
  // Per-organization module gate — the backend returns 403 `feature-disabled`
  // for the same modules; this just gives a friendlier landing page than a
  // raw error when someone follows a bookmarked/forced link.
  const feature = to.meta.feature as string | undefined
  if (feature && auth.isLoggedIn && !auth.enabledFeatures.includes(feature)) {
    return { name: 'feature-unavailable', query: { m: feature } }
  }
  return true
})

export default router
