import { useEffect, useState } from 'react'
import { AuthLayout } from '../components/auth-layout'
import { Button } from '../components/button'
import { Field, Label } from '../components/fieldset'
import { Heading } from '../components/heading'
import { Input } from '../components/input'
import { Link } from '../components/link'
import { Strong, Text, TextLink } from '../components/text'
import { useAuth } from './auth'
import { BrandMark } from './AppSidebar'
import { navigate, useLocation } from './router'
import { supabase } from './supabase'

const MIN_PASSWORD = 8

// Only same-app paths, so a crafted ?next= can't send someone off-site.
function nextPath(params) {
  let next = params.get('next')
  return next?.startsWith('/') && !next.startsWith('//') ? next : '/'
}

// Carries ?next= between the sign-in and sign-up forms.
function withNext(path, params) {
  return params.has('next') ? `${path}?next=${encodeURIComponent(nextPath(params))}` : path
}

function Page({ title, children, onSubmit }) {
  return (
    <AuthLayout>
      <form onSubmit={onSubmit} className="grid w-full max-w-sm grid-cols-1 gap-8">
        <Link href="/" className="flex items-center gap-3">
          <BrandMark />
          <span className="text-sm/5 font-semibold text-zinc-950 dark:text-white">Postgame Desk</span>
        </Link>
        <Heading>{title}</Heading>
        {children}
      </form>
    </AuthLayout>
  )
}

// One request at a time and one error line per form. Supabase calls resolve
// with { error } rather than rejecting, so `action` rethrows it.
function useSubmit(action) {
  let [state, setState] = useState({ busy: false, error: null })
  async function onSubmit(event) {
    event.preventDefault()
    setState({ busy: true, error: null })
    try {
      await action(Object.fromEntries(new FormData(event.currentTarget)))
      setState({ busy: false, error: null })
    } catch (error) {
      let offline = error.name === 'AuthRetryableFetchError' || error instanceof TypeError
      setState({ busy: false, error: offline ? "Can't reach the sign-in service. Try again." : error.message || 'Something went wrong. Try again.' })
    }
  }
  return { ...state, onSubmit }
}

function check({ data, error }) {
  if (error) throw error
  return data
}

// Catalyst's ErrorMessage belongs to one Field; this one speaks for the whole form.
function FormError({ children }) {
  return (
    <p role="alert" className="text-base/6 text-red-600 sm:text-sm/6 dark:text-red-500">
      {children}
    </p>
  )
}

function Submit({ busy, children, busyLabel }) {
  return (
    <Button type="submit" className="w-full" disabled={busy}>
      {busy ? busyLabel : children}
    </Button>
  )
}

function EmailField() {
  return (
    <Field>
      <Label>Email</Label>
      <Input type="email" name="email" autoComplete="email" required autoFocus />
    </Field>
  )
}

function NewPasswordField({ label }) {
  return (
    <Field>
      <Label>{label}</Label>
      <Input type="password" name="password" autoComplete="new-password" minLength={MIN_PASSWORD} required />
    </Field>
  )
}

function Notice({ title, children }) {
  return (
    <Page title={title}>
      <Text>{children}</Text>
      <Text>
        <TextLink href="/">
          <Strong>Back to Postgame Desk</Strong>
        </TextLink>
      </Text>
    </Page>
  )
}

// A successful sign-in updates the session, and AuthRoute moves on to ?next=.
function LoginPage() {
  let { params } = useLocation()
  let { busy, error, onSubmit } = useSubmit(({ email, password }) =>
    supabase.auth.signInWithPassword({ email, password }).then(check)
  )
  return (
    <Page title="Sign in to your account" onSubmit={onSubmit}>
      <EmailField />
      <Field>
        <div className="flex items-baseline justify-between">
          <Label>Password</Label>
          <Text>
            <TextLink href="/forgot-password">Forgot password?</TextLink>
          </Text>
        </div>
        <Input type="password" name="password" autoComplete="current-password" required />
      </Field>
      {error && <FormError>{error}</FormError>}
      <Submit busy={busy} busyLabel="Signing in…">
        Sign in
      </Submit>
      <Text>
        New here?{' '}
        <TextLink href={withNext('/signup', params)}>
          <Strong>Create an account</Strong>
        </TextLink>
      </Text>
    </Page>
  )
}

function SignupPage() {
  let { params } = useLocation()
  let [sentTo, setSentTo] = useState(null)
  let { busy, error, onSubmit } = useSubmit(async ({ email, password }) => {
    let data = check(
      await supabase.auth.signUp({ email, password, options: { emailRedirectTo: location.origin + nextPath(params) } })
    )
    // With email confirmation on, there is no session until the link is followed.
    if (!data.session) setSentTo(email)
  })
  if (sentTo) {
    return (
      <Notice title="Check your inbox">
        We sent a confirmation link to <Strong>{sentTo}</Strong>. Open it to finish creating your account.
      </Notice>
    )
  }
  return (
    <Page title="Create your account" onSubmit={onSubmit}>
      <Text>Ask about any recent game and pick your conversations up on any device.</Text>
      <EmailField />
      <NewPasswordField label="Password" />
      {error && <FormError>{error}</FormError>}
      <Submit busy={busy} busyLabel="Creating account…">
        Create account
      </Submit>
      <Text>
        Already have an account?{' '}
        <TextLink href={withNext('/login', params)}>
          <Strong>Sign in</Strong>
        </TextLink>
      </Text>
    </Page>
  )
}

function ForgotPasswordPage() {
  let [sentTo, setSentTo] = useState(null)
  let { busy, error, onSubmit } = useSubmit(async ({ email }) => {
    check(await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${location.origin}/reset-password` }))
    setSentTo(email)
  })
  if (sentTo) {
    return (
      <Notice title="Check your inbox">
        If <Strong>{sentTo}</Strong> has an account, we sent it a link to choose a new password.
      </Notice>
    )
  }
  return (
    <Page title="Reset your password" onSubmit={onSubmit}>
      <Text>Enter your email and we'll send you a link to choose a new one.</Text>
      <EmailField />
      {error && <FormError>{error}</FormError>}
      <Submit busy={busy} busyLabel="Sending…">
        Send reset link
      </Submit>
      <Text>
        <TextLink href="/login">
          <Strong>Back to sign in</Strong>
        </TextLink>
      </Text>
    </Page>
  )
}

// The emailed link signs the user in with a recovery session, then lands here.
function ResetPasswordPage() {
  let { user } = useAuth()
  let { busy, error, onSubmit } = useSubmit(async ({ password }) => {
    check(await supabase.auth.updateUser({ password }))
    navigate('/', { replace: true })
  })
  if (!user) {
    return (
      <Notice title="This link has expired">
        Reset links work once and expire after a while. <TextLink href="/forgot-password">Send a new one</TextLink>.
      </Notice>
    )
  }
  return (
    <Page title="Choose a new password" onSubmit={onSubmit}>
      <NewPasswordField label="New password" />
      {error && <FormError>{error}</FormError>}
      <Submit busy={busy} busyLabel="Saving…">
        Save password
      </Submit>
    </Page>
  )
}

const PAGES = {
  '/login': LoginPage,
  '/signup': SignupPage,
  '/forgot-password': ForgotPasswordPage,
  '/reset-password': ResetPasswordPage,
}

// Signed-in visitors skip these and go on to ?next=.
const SIGNED_OUT_ONLY = [LoginPage, SignupPage]

export function authPage(path) {
  return PAGES[path.replace(/\/$/, '')] ?? null
}

export function AuthRoute({ page: Page }) {
  let { status, user } = useAuth()
  let { params } = useLocation()
  let redirect = Boolean(user) && SIGNED_OUT_ONLY.includes(Page)
  useEffect(() => {
    if (redirect) navigate(nextPath(params), { replace: true })
  }, [redirect, params])
  if (status === 'disabled') {
    return <Notice title="Sign-in isn't set up">This copy of Postgame Desk runs without accounts.</Notice>
  }
  return status === 'loading' || redirect ? null : <Page />
}
