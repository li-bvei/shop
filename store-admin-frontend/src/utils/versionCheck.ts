// Detects a new deploy while the app is already open in a tab, so a page
// left open across a deploy doesn't keep running against APIs/response
// shapes that changed underneath it. `public/version.txt` is stamped with
// a fresh build id by the Docker build (see store-admin-frontend/Dockerfile)
// and served unhashed at the site root — comparing it against the value
// this tab loaded with is a simple, server-state-free way to notice a
// deploy even if something in front of nginx (the outer reverse proxy)
// caches index.html more aggressively than this app's own nginx.conf asks
// for.
const POLL_INTERVAL_MS = 5 * 60 * 1000

let knownVersion: string | null = null

async function fetchVersion(): Promise<string | null> {
  try {
    const res = await fetch(`/version.txt?_=${Date.now()}`, { cache: 'no-store' })
    if (!res.ok) return null
    const text = (await res.text()).trim()
    return text || null
  } catch {
    return null
  }
}

/** Starts watching for a new deploy; calls `onNewVersion` (at most once)
 * the first time the server's version differs from what this tab loaded
 * with. No-op outside production — dev mode has no version.txt and Vite's
 * own HMR already handles picking up code changes. */
export function startVersionWatch(onNewVersion: () => void) {
  if (!import.meta.env.PROD) return

  let notified = false
  const checkNow = async () => {
    if (notified) return
    const version = await fetchVersion()
    if (!version) return
    if (knownVersion === null) {
      knownVersion = version
      return
    }
    if (version !== knownVersion) {
      notified = true
      onNewVersion()
    }
  }

  checkNow()
  setInterval(checkNow, POLL_INTERVAL_MS)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkNow()
  })
}
