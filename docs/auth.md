# Authentication

Accounts are managed by Supabase Auth. Supabase handles sign-up, sign-in,
password reset, email confirmation and OAuth; the API never sees a password.
The API only checks the access token the browser sends with each request.

```
Browser ── supabase-js ──> Supabase Auth      sign up, sign in, refresh
   └── /api/*  Authorization: Bearer <access token> ──> FastAPI
                  verifies ES256 signature against the project's JWKS,
                  audience "authenticated", issuer <SUPABASE_URL>/auth/v1, expiry
                  → user id = the token's `sub`
```

Verification is local: the API fetches the project's public signing keys from
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json` and caches them for ten minutes.
Symmetric (HS256) tokens, including legacy anon keys, are rejected. The project
must use asymmetric JWT signing keys (Supabase → Settings → JWT signing keys).

## Configuration

| Variable | Purpose |
|---|---|
| `NBA_AUTH_MODE` | `supabase` (default) or `disabled`. Disabled leaves every route open with no ownership filtering; use it only for local development and unit tests. |
| `SUPABASE_URL` | Project URL, e.g. `https://<ref>.supabase.co`. Required in `supabase` mode; without it, signed-in requests fail with 503 rather than falling open. |
| `NBA_ADMIN_USER_IDS` | Comma-separated Supabase user ids (Authentication → Users) allowed to use operator routes. User ids, not emails, so an unconfirmed sign-up cannot claim an admin address. |

The API does not need the Supabase secret or service-role key.

## Frontend

`frontend/.env` needs `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`
(Supabase → Settings → API keys; never the secret key). Without them the UI
runs without accounts, matching `NBA_AUTH_MODE=disabled`. supabase-js keeps the
session in the browser and refreshes it; `api.js` sends the access token on
every request and retries once with a fresh token after a 401.

Pages: `/login`, `/signup`, `/forgot-password` and `/reset-password`. Every
other page needs a signed-in user: signed-out visitors, including anyone who
signs out, are sent to `/login?next=<page>` and returned there after signing in.
Add `http://localhost:3000/**` and the production origin to Supabase's redirect
URLs so confirmation and reset links can return to the app.

## Access

| Route | Access |
|---|---|
| `/api/recent-games`, `/api/games/*`, `/api/health/storage` | Anyone |
| `POST /api/ask`, `/api/ask/stream` (`mcp_harness`) | Signed in. Each run records the asker's `user_id`. |
| Follow-up questions (`parent_run_id`) | Only as the user who asked the earlier run; anything else reads as not found. |
| `/api/me`, `/api/conversations*`, `/api/runs/{id}` | Signed in; conversations and runs are the viewer's own (admins may read any run). |
| `/api/traces*`, `/api/ingestion-jobs*`, `/api/db-status` | Admins |

Missing tokens return 401 on routes that need one; invalid or expired tokens
always return 401, so the client can refresh the session and retry.

Runs saved before revision `20260924_01` have no owner and appear in no
one's history.

## Supabase Data API

The browser holds the project's publishable key, which can reach tables in
exposed schemas through Supabase's Data API. Every application table has Row
Level Security enabled with no policies, so those roles are denied; the API
connects as the table owner and bypasses RLS. Any new table must enable RLS in
its migration. Disabling the Data API in the dashboard is an additional safeguard.
