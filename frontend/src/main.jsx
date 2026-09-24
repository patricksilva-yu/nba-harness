import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { AuthProvider, useAuth } from './app/auth'
import { authPage, AuthRoute } from './app/AuthPages'
import { navigate, useLocation } from './app/router'
import './styles/tailwind.css'

// Sign-in pages stand alone; with sign-in set up, the app needs a signed-in user.
function Root() {
  let { path } = useLocation()
  let { status, user } = useAuth()
  let page = authPage(path)
  let signedOut = !page && status === 'ready' && !user
  useEffect(() => {
    if (!signedOut) return
    let here = location.pathname + location.search
    navigate(here === '/' ? '/login' : `/login?next=${encodeURIComponent(here)}`, { replace: true })
  }, [signedOut])
  if (page) return <AuthRoute page={page} />
  return status === 'loading' || signedOut ? null : <App />
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <Root />
    </AuthProvider>
  </StrictMode>
)
