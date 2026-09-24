import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'
import { navigate } from './router'
import { supabase } from './supabase'

const AuthContext = createContext(null)

// status: 'loading' until Supabase reports the stored session, then 'ready';
// 'disabled' when sign-in isn't configured and the app runs open.
export function AuthProvider({ children }) {
  let [session, setSession] = useState({ status: supabase ? 'loading' : 'disabled', user: null })
  // null while unknown; the API holds the admin allowlist.
  let [isAdmin, setIsAdmin] = useState(supabase ? null : true)
  let userId = session.user?.id

  useEffect(() => {
    if (!supabase) return
    // Fires INITIAL_SESSION on subscribe, then on every sign-in, sign-out and refresh.
    let { data } = supabase.auth.onAuthStateChange((event, next) => {
      setSession({ status: 'ready', user: next?.user ?? null })
      if (event === 'PASSWORD_RECOVERY') navigate('/reset-password')
    })
    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!supabase || !userId) return
    let current = true
    setIsAdmin(null)
    api.me().then(
      (me) => current && setIsAdmin(me.is_admin),
      () => current && setIsAdmin(false)
    )
    return () => {
      current = false
    }
  }, [userId])

  let value = { ...session, isAdmin, signOut: () => supabase.auth.signOut() }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
