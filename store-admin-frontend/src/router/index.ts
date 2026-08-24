import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore, type UserRole } from '@/stores/auth'

function defaultRouteForRole(role: UserRole) {
  return role === 'staff' ? { name: 'my-availability' } : { name: 'dashboard' }
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
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      redirect: () => defaultRouteForRole(useAuthStore().role),
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { roles: ['admin', 'branch'] },
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
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'suppliers',
          name: 'suppliers',
          component: () => import('@/views/SuppliersView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'products',
          name: 'products',
          component: () => import('@/views/ProductsView.vue'),
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'inventory',
          name: 'inventory',
          component: () => import('@/views/InventoryView.vue'),
          meta: { roles: ['admin', 'branch'] },
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
          meta: { roles: ['admin', 'branch'] },
        },
        {
          path: 'wages',
          name: 'wages',
          component: () => import('@/views/WagesView.vue'),
          meta: { roles: ['admin', 'branch'] },
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
          meta: { roles: ['staff'] },
        },
        {
          path: 'my-wages',
          name: 'my-wages',
          component: () => import('@/views/staff/MyWagesView.vue'),
          meta: { roles: ['staff'] },
        },
        {
          path: 'my-password',
          name: 'my-password',
          component: () => import('@/views/staff/MyPasswordView.vue'),
          meta: { roles: ['staff'] },
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
    return defaultRouteForRole(auth.role)
  }
  // Route-level role gate — mirrors the backend's own permission checks,
  // never a substitute for them (every one of these endpoints is also
  // independently enforced server-side).
  const allowedRoles = to.meta.roles as UserRole[] | undefined
  if (allowedRoles && auth.isLoggedIn && !allowedRoles.includes(auth.role)) {
    return defaultRouteForRole(auth.role)
  }
  return true
})

export default router
