import { useEffect, useState } from 'react'

// Minimal History API routing: the app has only a few top-level paths.
const EVENT = 'app:navigate'

export function navigate(to, { replace = false } = {}) {
  if (to === location.pathname + location.search) return
  history[replace ? 'replaceState' : 'pushState'](null, '', to)
  window.dispatchEvent(new Event(EVENT))
}

export function useLocation() {
  let read = () => ({ path: location.pathname, params: new URLSearchParams(location.search) })
  let [current, setCurrent] = useState(read)
  useEffect(() => {
    let update = () => setCurrent(read())
    window.addEventListener('popstate', update)
    window.addEventListener(EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(EVENT, update)
    }
  }, [])
  return current
}

// Plain left-clicks on in-app paths navigate without a reload; modified clicks keep browser behavior.
export function handleLinkClick(event, href, target) {
  if (
    !href?.startsWith('/') || href.startsWith('/api/') || (target && target !== '_self') ||
    event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
  ) return
  event.preventDefault()
  navigate(href)
}
