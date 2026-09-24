from api.nba_agent.db import connect, create_schema


def test_create_schema_creates_live_tables(tmp_path):
    db_path = tmp_path / "nba_agent_test.duckdb"
    con = connect(db_path, read_only=False)
    create_schema(con)
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        """
    ).fetchall()
    con.close()

    table_names = {row[0] for row in rows}
    assert {
        "games",
        "raw_responses",
        "box_scores_team",
        "box_scores_player",
        "box_scores_advanced_team",
        "play_by_play_events",
        "lineup_stints",
        "evidence_packets",
    }.issubset(table_names)
