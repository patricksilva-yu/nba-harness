"""Live smoke test against an explicitly selected disposable PostgreSQL database.

No model calls. Imports an overtime game twice and checks the app's evidence and
home data paths. Do not run against the active application database.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.nba_agent.db import get_storage
from api.nba_agent.s3_ingest import import_s3_game_bundle, sync_s3_results
from api.nba_agent.service import NBAService
from api.nba_agent.storage.pipeline import GamePipelineRepository
from api.nba_agent.tools import ensure_game_cached, get_cached_games_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-id', required=True)
    args = parser.parse_args()
    # Only the documented disposable database is accepted; never load .env here.
    from urllib.parse import urlparse
    url = urlparse(os.environ.get('POSTGRES_CONNECTION_STRING', ''))
    if (os.environ.get('NBA_STORAGE_BACKEND') != 'postgres' or url.hostname not in ('127.0.0.1', 'localhost')
            or url.path != '/nba_test'):
        raise SystemExit('Supply the explicit local disposable PostgreSQL configuration.')
    storage = get_storage()
    storage.initialize()
    results = sync_s3_results()
    first = import_s3_game_bundle(args.game_id)
    second = import_s3_game_bundle(args.game_id)
    assert GamePipelineRepository(storage).missing_stats(args.game_id) is None
    assert ensure_game_cached(args.game_id)['ingested'] is False
    service = NBAService()
    context = service.get_analysis_context(args.game_id, persist=True)
    assert context['context']['advanced']['summary']['advanced_context_source'] == 'local_fallback'
    assert context['context']['snapshot']['evidence_packets']
    assert context['context']['runs']['evidence_packets']
    cached = get_cached_games_status(limit=10000)
    assert any(g['game_id'] == args.game_id and g['complete'] for g in cached['games'])
    con = storage.open()
    try:
        counts = {table: con.execute(f'SELECT COUNT(*) FROM {table} WHERE game_id = ?', [args.game_id]).fetchone()[0]
                  for table in ('box_scores_team', 'box_scores_player', 'play_by_play_events', 'box_scores_advanced_team')}
    finally:
        con.close()
    assert counts['box_scores_team'] == 2
    assert counts['box_scores_player'] == second['player_rows']
    assert counts['play_by_play_events'] == first['pbp_rows']
    assert counts['box_scores_advanced_team'] == 0
    print(json.dumps({'game_id': args.game_id, 'schedule_finals': len(results), 'counts': counts,
                      'evidence_packets': context['summary']['packet_count'], 'repeat_import': 'passed',
                      'analysis': 'not requested; no model cost'}))


if __name__ == '__main__':
    main()
