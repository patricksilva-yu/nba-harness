# Migration Provenance

- Source directory: `/Users/patrick/Developer/nba`
- Target directory: `/Users/patrick/Developer/nba-harness`
- Migration date: 2026-09-21
- Source commit: `432560bc2dad01aba172f4fdba1d7a8301ebcdfa`

The source working tree, rather than only its committed state, was migrated.
At capture time, it contained modifications to `.env.example`, `.github/workflows/docker-images.yml`,
`README.md`, selected `api/nba_agent` files, `api/models.py`, `api/routes.py`, selected frontend
and test files; and untracked application files in `api/nba_agent`, `docs`, `evals`, and `tests`.

The migration copied only the allowlist defined in `docs/MIGRATION.md`. It intentionally excludes
secrets, installed dependencies, caches, generated output, local DuckDB data, and legacy experiments.
