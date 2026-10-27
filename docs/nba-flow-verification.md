# NBA schedule and real Q&A verification — October 26, 2026

## Schedule

The collector is configured on `main` for **10:30 pm and 1 am Eastern** using
`America/Toronto` timezone-aware GitHub schedules. Checked the committed YAML,
UTC offsets before/after daylight saving changes, and the unchanged zero-AI
collection default. A manual stats-only GitHub run passed against the app database:
https://github.com/patricksilva-yu/nba-harness/actions/runs/40439610430

GitHub timezone-aware scheduling documentation:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule

## Real model and browser test

Used the configured `gpt-6-luna` model, real MCP tools, saved NBA S3 data and the
application PostgreSQL database. Browser interaction used a dedicated local test
identity on a loopback-only test API. The normal API's Supabase configuration
was preserved and its unauthenticated conversation request still returned 401.
The non-admin test identity received 403 for admin traces.

Game: Toronto at Minnesota, October 25, 2026 (`0022600115`).

1. **Question:** Why did Minnesota beat Toronto 117–94 on October 25, 2026?
   Explain the shooting and rebounding differences using the saved game data.
   **Result:** supported, three claims, one verification pass, about 21.9 seconds.
   Independently checked against saved box scores: FG 35/91 vs 43/77; threes
   10/38 vs 15/31; rebounds 34–49, including offensive 14–9 and defensive 20–40.
2. **Follow-up:** Who led Toronto in scoring, and how many points, rebounds and
   assists did he have?
   **Result:** supported, one claim, two verification passes, about 28.4 seconds.
   Correct answer: Ja'Kobe Walter, 22 points, 4 rebounds and 2 assists. The
   verifier rejected an initially incomplete top-scorer justification; targeted
   lookup supplied the missing support before the final answer was released.

Both runs are completed and remain on the same game and conversation. The child
references its parent; all cited packet IDs exist in each run's evidence ledger.
Conversation replay after a full browser reload was tested; no extra model calls
were made for replay or citation inspection.

Conversation: `harness_7b0b8d88459f43e8b728c05f4681abae`.
Follow-up run: `harness_ee1a3ef364964446b632ba34786155c0`.

Actual provider usage: 56,951 input and 2,378 output tokens across both answers.
No dollar estimate is reported because model token prices were not configured.
Scheduled collection still makes zero model calls.

## Issues found and fixed

- Snapshot citations showed only the final score even when the answer cited
  shooting and rebounds. They now show the supporting team box-score table;
  score-only legacy packets and missing/zero stats have regression tests.
- Reopened conversations lost the game date when the game was no longer in the
  recent-finals list. Game-flow metadata now includes date and season type,
  which the header uses as a fallback. The date is checked in the flow test.

## Limits of this test

This was an agent-operated real-browser user-flow test, not human usability
research. **Human acceptance testing and a real Supabase login in that browser
remain pending**. Authentication is covered separately by automated tests; no
login success is claimed here.
No third paid answer was generated during these checks. Football work is excluded.

## Regression and UI checks

- Working checkout: `pytest -q` with explicit disposable PostgreSQL URL: 226 passed.
- Isolated NBA-only checkout: PostgreSQL-enabled suite: 179 passed (legacy
  cache-dependent tests used an ignored local fixture copy).
- `npm run test:evidence`: 3 passed, covering the real citation's numbers,
  score-only legacy packets and zero versus missing statistics.
- Frontend production builds passed in both checkouts.
- Desktop and 390px mobile conversation replay, box-score citation drawer,
  final game date and follow-up composer checked using the saved real answers.
