/**
 * Structure of the in-app operating guide.
 *
 * This file holds the guide's SHAPE — which chapters exist, in what order,
 * who each one is for, and which route it describes. The WORDS all live in
 * the locale files under `guide.*`, so the on-screen page and the
 * downloadable PDF render the same text from the same keys and cannot
 * drift apart (and so the guide is bilingual by construction rather than
 * by a second translation of a second copy).
 *
 * What belongs here: how to use a screen that exists today, who is allowed
 * to use it, and what to do when it refuses.
 *
 * What must never appear here, in any locale: deployment or server
 * commands, hostnames or IP addresses, credentials of any kind, database
 * or migration details, environment variables, internal model/endpoint
 * names, or anything else aimed at whoever operates the deployment rather
 * than at whoever runs the restaurant. The operator-facing material has
 * its own home in docs/ai-handoff and deliberately stays out of the
 * product.
 *
 * Content is derived from the current interface, not from the historical
 * development log — that log is a changelog of refactors and test runs,
 * and most of it describes neither a screen nor a task a user performs.
 */

/** Who a chapter is written for. A chapter is shown when the reader's own
 * role appears here; `all` means everyone. */
export type GuideAudience = 'all' | 'admin' | 'branch' | 'staff'

export interface GuideSection {
  /** i18n key suffix under `guide.sections.<id>`. */
  id: string
  audiences: GuideAudience[]
  /** Hidden when the tenant is not entitled to this module, so the guide
   * never explains a screen this customer cannot open. */
  feature?: string
  /** The in-app screen this chapter is about; the page turns it into a
   * "open this screen" link. Omitted for chapters that aren't one screen
   * (getting started, FAQ). */
  route?: string
  /** `steps.<n>` keys under the section — the numbered walkthrough. */
  stepCount: number
  /** `notes.<n>` keys — permissions, limits, and what to do when
   * something is refused. Optional per section. */
  noteCount: number
}

export const GUIDE_SECTIONS: GuideSection[] = [
  { id: 'gettingStarted', audiences: ['all'], stepCount: 4, noteCount: 3 },
  { id: 'dashboard', audiences: ['admin', 'branch'], route: '/dashboard', stepCount: 3, noteCount: 1 },
  { id: 'dailyReport', audiences: ['admin', 'branch'], route: '/daily-report', stepCount: 6, noteCount: 4 },
  { id: 'monthlyAnalysis', audiences: ['admin', 'branch'], route: '/monthly-analysis', stepCount: 5, noteCount: 3 },
  {
    id: 'purchasing', audiences: ['admin', 'branch'], route: '/purchasing',
    feature: 'purchasing', stepCount: 4, noteCount: 2,
  },
  {
    id: 'suppliers', audiences: ['admin', 'branch'], route: '/suppliers',
    feature: 'suppliers', stepCount: 3, noteCount: 2,
  },
  { id: 'staff', audiences: ['admin', 'branch'], route: '/staff', stepCount: 3, noteCount: 2 },
  {
    id: 'scheduling', audiences: ['admin', 'branch'], route: '/scheduling',
    feature: 'scheduling', stepCount: 5, noteCount: 3,
  },
  {
    id: 'attendance', audiences: ['admin', 'branch'], route: '/attendance',
    feature: 'scheduling', stepCount: 5, noteCount: 4,
  },
  {
    id: 'myAttendance', audiences: ['staff'], route: '/my-attendance',
    feature: 'scheduling', stepCount: 4, noteCount: 3,
  },
  { id: 'wages', audiences: ['admin', 'branch'], route: '/wages', feature: 'wages', stepCount: 4, noteCount: 3 },
  { id: 'demo', audiences: ['admin', 'branch'], route: '/demo', stepCount: 2, noteCount: 1 },
  { id: 'faq', audiences: ['all'], stepCount: 0, noteCount: 7 },
]

/** The chapters this reader should see: their role, and their tenant's
 * modules. Filtering here rather than in the view means the PDF download
 * contains exactly the chapters the reader can act on — a guide that
 * explains screens you cannot open is worse than a shorter guide. */
export function sectionsFor(role: string, enabledFeatures: string[]): GuideSection[] {
  return GUIDE_SECTIONS.filter((section) => {
    if (section.feature && !enabledFeatures.includes(section.feature)) return false
    return section.audiences.includes('all') || section.audiences.includes(role as GuideAudience)
  })
}
