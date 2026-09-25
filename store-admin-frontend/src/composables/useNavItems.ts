import { computed } from 'vue'
import {
  Odometer, Document, Box, OfficeBuilding, User, Setting, TrendCharts, Calendar, Money, Lock,
  Goods, Files, Present, Postcard, Switch as SwitchIcon,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

export interface NavItem {
  path: string
  icon: unknown
  labelKey: string
  // Opens in a new browser tab instead of navigating the admin shell —
  // the counter-reception kiosk is a separate workstation surface, so
  // clicking it must not replace whatever the manager was looking at.
  external?: boolean
  // Hidden unless the account's Organization is entitled to this module
  // (common.features on the backend).
  feature?: string
}

const adminBranchNavItems: NavItem[] = [
  { path: '/dashboard', icon: Odometer, labelKey: 'nav.dashboard' },
  { path: '/monthly-analysis', icon: TrendCharts, labelKey: 'nav.monthlyAnalysis' },
  { path: '/daily-report', icon: Document, labelKey: 'nav.dailyReport' },
  { path: '/purchasing', icon: Box, labelKey: 'nav.purchasing', feature: 'purchasing' },
  { path: '/suppliers', icon: OfficeBuilding, labelKey: 'nav.suppliers', feature: 'suppliers' },
  { path: '/products', icon: Goods, labelKey: 'nav.products', feature: 'products' },
  { path: '/inventory', icon: Files, labelKey: 'nav.inventory', feature: 'inventory' },
  { path: '/staff', icon: User, labelKey: 'nav.staff' },
  { path: '/scheduling', icon: Calendar, labelKey: 'nav.scheduling', feature: 'scheduling' },
  { path: '/wages', icon: Money, labelKey: 'nav.wages', feature: 'wages' },
  { path: '/promotions', icon: Present, labelKey: 'nav.promotions', feature: 'promotions' },
  { path: '/kiosk/verify', icon: Postcard, labelKey: 'nav.promoVerify', external: true, feature: 'promotions' },
]

const staffNavItems: NavItem[] = [
  { path: '/my-availability', icon: Calendar, labelKey: 'nav.myAvailability' },
  { path: '/my-shifts', icon: Document, labelKey: 'nav.myShifts', feature: 'scheduling' },
  { path: '/my-wages', icon: Money, labelKey: 'nav.myWages', feature: 'wages' },
  { path: '/kiosk/verify', icon: Postcard, labelKey: 'nav.promoVerify', external: true, feature: 'promotions' },
]

// A platform super admin never touches the per-chain operational screens —
// their whole world is the /platform console.
const platformNavItems: NavItem[] = [
  { path: '/platform/overview', icon: TrendCharts, labelKey: 'nav.platformOverview' },
  { path: '/platform/manage', icon: SwitchIcon, labelKey: 'nav.platformManage' },
]

/** The role- and feature-filtered navigation, shared by the desktop sidebar
 * and the phone bottom bar so both always show exactly the same set. */
export function useNavItems() {
  const auth = useAuthStore()

  function visible(items: NavItem[]) {
    return items.filter((i) => !i.feature || auth.enabledFeatures.includes(i.feature))
  }

  const navItems = computed(() => {
    if (auth.isSuperuser) return platformNavItems
    return visible(auth.role === 'staff' ? staffNavItems : adminBranchNavItems)
  })
  const systemItems = computed<NavItem[]>(() => {
    if (auth.isSuperuser) return []
    return auth.role === 'staff'
      ? [{ path: '/my-password', icon: Lock, labelKey: 'nav.myPassword' }]
      : [{ path: '/settings', icon: Setting, labelKey: 'nav.settings' }]
  })
  return { navItems, systemItems }
}
