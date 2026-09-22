#!/usr/bin/env python3
"""One-time validated transfer from the immutable legacy DuckDB backup."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
import duckdb
import psycopg2
from psycopg2.extras import Json, execute_values
from dotenv import load_dotenv

TABLES = ["raw_responses", "games", "box_scores_team", "box_scores_player", "box_scores_advanced_team", "play_by_play_events", "lineup_stints", "evidence_packets", "analysis_runs", "ingestion_jobs", "seed_player_game_logs"]
PKS = {"raw_responses":["response_id"], "games":["game_id"], "box_scores_team":["game_id","team_side"], "box_scores_player":["game_id","player_id"], "box_scores_advanced_team":["game_id","team_id"], "play_by_play_events":["game_id","eventnum"], "lineup_stints":["stint_id"], "evidence_packets":["packet_id"], "analysis_runs":["run_id"], "ingestion_jobs":["job_id"]}
JSON_COLUMNS = {"raw_responses":{"request_json","response_json"}, "evidence_packets":{"payload_json"}, "analysis_runs":{"packet_ids_json"}, "ingestion_jobs":{"result_json"}}

def normalize(value):
    if isinstance(value, datetime) and value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
    return value

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--source", required=True); parser.add_argument("--batch-size", type=int, default=1000); args=parser.parse_args()
    load_dotenv(".env"); url=os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_CONNECTION_STRING")
    if not url: raise RuntimeError("DATABASE_URL or POSTGRES_CONNECTION_STRING is required")
    source=duckdb.connect(args.source, read_only=True); target=psycopg2.connect(url); target.autocommit=False
    report={}
    try:
        for table in TABLES:
            columns=[r[0].lower() for r in source.execute(f"DESCRIBE {table}").fetchall()]
            rows=source.execute(f"SELECT * FROM {table}").fetchall()
            converted=[]
            for row in rows:
                values=[]
                for col,value in zip(columns,row):
                    if col in JSON_COLUMNS.get(table,set()) and value is not None: value=Json(json.loads(value) if isinstance(value,str) else value)
                    values.append(normalize(value))
                converted.append(values)
            with target.cursor() as cursor:
                quoted=", ".join(columns); template="(" + ", ".join(["%s"]*len(columns)) + ")"
                if table in PKS:
                    keys=PKS[table]; updates=", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in keys)
                    conflict=f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}"
                else: conflict=""
                for start in range(0,len(converted),args.batch_size): execute_values(cursor, f"INSERT INTO {table} ({quoted}) VALUES %s{conflict}", converted[start:start+args.batch_size], template=template)
                cursor.execute(f"SELECT COUNT(*) FROM {table}"); count=cursor.fetchone()[0]
            report[table]={"source_rows":len(rows),"target_rows":count}
            if count < len(rows): raise RuntimeError(f"row-count validation failed for {table}")
        target.commit(); print(json.dumps(report, sort_keys=True))
    except Exception:
        target.rollback(); raise
    finally: source.close(); target.close()
if __name__ == "__main__": main()
