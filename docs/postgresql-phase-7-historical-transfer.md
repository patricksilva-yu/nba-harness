# PostgreSQL Migration Phase 7: Historical DuckDB Transfer

## Result

Completed on 2026-09-22 from the legacy source
`/Users/patrick/Developer/nba/data/nba_agent.duckdb`.

An immutable private backup was created before transfer:

```text
/private/tmp/nba-harness-legacy-nba-agent-20260922.duckdb
SHA-256: 16999fdd436d8f93923aa504181fda8fc1acccaa7a7fedd7dddd82e841645911
```

The transfer used [`transfer_duckdb_to_postgres.py`](../scripts/transfer_duckdb_to_postgres.py), applied Alembic revision `20260922_03`, and loaded all canonical tables plus the previously out-of-scope `seed_player_game_logs` table.

| Table | Legacy rows | Supabase rows after transfer |
| --- | ---: | ---: |
| raw_responses | 62 | 67 |
| games | 8 | 9 |
| box_scores_team | 16 | 18 |
| box_scores_player | 226 | 226 |
| box_scores_advanced_team | 14 | 14 |
| play_by_play_events | 3,892 | 3,892 |
| lineup_stints | 86 | 86 |
| evidence_packets | 53 | 53 |
| analysis_runs | 44 | 44 |
| ingestion_jobs | 0 | 0 |
| seed_player_game_logs | 150,801 | 150,801 |

The higher raw-response, game, and team-box counts are the representative
Supabase game ingested before the historical transfer. Every legacy table's
target count is at least its source count. The Supabase database measured 68
MB after transfer, below the 500 MB Free-tier allowance.

## Safety notes

The transfer is idempotent for tables with established primary keys; records
with the same key are updated from the legacy source. The legacy seed-log table
has no primary key, so rerunning its transfer would append duplicate rows.
Treat this completed transfer as one-time unless a future migration adds a
stable identity for that table.
