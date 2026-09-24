import { createClient } from '@supabase/supabase-js'

// Null when sign-in isn't configured: the app then runs open, matching an API
// started with NBA_AUTH_MODE=disabled. Only the publishable key belongs here.
const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

export const supabase = url && key ? createClient(url, key) : null
