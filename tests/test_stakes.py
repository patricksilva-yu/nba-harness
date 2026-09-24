from api.nba_agent.db import create_schema, get_storage
from api.nba_agent.official_ingest import upsert_game_results
from api.nba_agent.service import NBAService
from api.nba_agent.tools import get_cached_games_status, get_stakes_context


def result(game_id, date, home, away, home_score, away_score, season_type="Playoffs"):
    return {"game_id": game_id, "season_id": "42025" if season_type == "Playoffs" else "22025", "game_date": date,
            "season_type": season_type, "home_team_id": home, "home_team_abbr": home, "home_team_name": home,
            "away_team_id": away, "away_team_abbr": away, "away_team_name": away,
            "home_score": home_score, "away_score": away_score}


def store(tmp_path, games):
    path = tmp_path / "stakes.duckdb"
    con = get_storage(path).open(read_only=False)
    create_schema(con)
    upsert_game_results(con, games)
    con.close()
    return path


# Finals ids: 004 25 00 4 0 G. NYK won 4-1, as in the 2026 Finals the app shows.
FINALS = [
    result("0042500401", "2026-06-03", "SAS", "NYK", 95, 105),
    result("0042500402", "2026-06-05", "SAS", "NYK", 104, 105),
    result("0042500403", "2026-06-08", "NYK", "SAS", 111, 115),
    result("0042500404", "2026-06-10", "NYK", "SAS", 107, 106),
    result("0042500405", "2026-06-13", "SAS", "NYK", 90, 94),
]


def stakes(path, game_id):
    packet = get_stakes_context(game_id, path)["evidence_packets"][0]
    return packet, packet["metrics"]


def test_clinching_finals_game_is_a_championship(tmp_path):
    packet, metrics = stakes(store(tmp_path, FINALS), "0042500405")
    assert packet["type"] == "series_context" and packet["confidence"] == "high"
    assert metrics["round_name"] == "NBA Finals" and metrics["game_in_series"] == 5
    assert metrics["series_before"] == {"NYK": 3, "SAS": 1} and metrics["series_after"] == {"NYK": 4, "SAS": 1}
    assert metrics["outcome"] == "clinched_series" and metrics["series_winner"] == "NYK"
    assert metrics["elimination_game"] is True
    assert packet["claim_seed"] == "NYK won Game 5 of the NBA Finals to clinch the NBA championship, 4-1 over SAS."


def test_series_state_counts_only_games_through_this_one(tmp_path):
    _, metrics = stakes(store(tmp_path, FINALS), "0042500403")
    assert metrics["series_after"] == {"NYK": 2, "SAS": 1}
    assert metrics["outcome"] == "cut_series_deficit"
    assert [g["game_in_series"] for g in metrics["games"]] == [1, 2, 3]


def test_game_six_win_forces_game_seven(tmp_path):
    games = [result(f"004250020{n}", f"2026-05-0{n}", "BOS", "MIA", *(score)) for n, score in
             zip(range(1, 7), [(100, 90), (100, 90), (100, 90), (90, 100), (90, 100), (90, 100)])]
    packet, metrics = stakes(store(tmp_path, games), "0042500206")
    assert metrics["outcome"] == "forced_game_7" and metrics["round_name"] == "Conference Semifinals"
    assert "force Game 7" in packet["claim_seed"]


def test_missing_earlier_games_are_flagged_not_miscounted(tmp_path):
    packet, metrics = stakes(store(tmp_path, [FINALS[0], FINALS[4]]), "0042500405")
    assert packet["confidence"] == "medium" and packet["caveats"]
    assert metrics["series_winner"] is None


def test_regular_season_reports_record_last_ten_and_streak(tmp_path):
    games = [result(f"00225000{n:02d}", f"2026-01-{n:02d}", "NYK", "BOS", 100, 90 if n > 2 else 110, "Regular Season")
             for n in range(1, 6)]
    packet, metrics = stakes(store(tmp_path, games), "0022500005")
    assert packet["type"] == "team_form"
    assert metrics["teams"]["NYK"] == {"record": "3-2", "games_counted": 5, "last_10": "3-2", "streak": "W3"}
    assert metrics["teams"]["BOS"]["streak"] == "L3"


def test_results_sync_never_overwrites_an_imported_game_and_is_not_a_cached_game(tmp_path):
    path = store(tmp_path, FINALS)
    con = get_storage(path).open(read_only=False)
    upsert_game_results(con, [{**FINALS[0], "home_score": 0}])
    score = con.execute("SELECT home_score FROM games WHERE game_id = ?", ["0042500401"]).fetchone()[0]
    con.close()
    assert score == 95
    assert get_cached_games_status(path)["games"] == []


def test_stakes_is_an_analysis_section(tmp_path):
    context = NBAService(store(tmp_path, FINALS)).get_analysis_context("0042500405", sections=["stakes"])
    assert [p["type"] for p in context["evidence_packets"]] == ["series_context"]


def test_neutral_site_games_are_not_dropped_from_results():
    import pandas as pd
    from api.nba_agent.official_ingest import league_log_games

    class Response:
        def get_data_frames(self):
            return [pd.DataFrame([
                {"GAME_ID": "0022501230", "GAME_DATE": "2025-12-13", "SEASON_ID": "22025", "TEAM_ID": 1,
                 "TEAM_ABBREVIATION": "SAS", "TEAM_NAME": "Spurs", "MATCHUP": "SAS @ OKC", "PTS": 111},
                {"GAME_ID": "0022501230", "GAME_DATE": "2025-12-13", "SEASON_ID": "22025", "TEAM_ID": 2,
                 "TEAM_ABBREVIATION": "OKC", "TEAM_NAME": "Thunder", "MATCHUP": "OKC @ SAS", "PTS": 109},
            ])]

    [game] = league_log_games(Response(), "2025-26", "Regular Season")
    assert (game["away_team_abbr"], game["home_team_abbr"]) == ("SAS", "OKC")


def test_game_id_decides_which_league_log_a_past_game_is_imported_from():
    from api.nba_agent.official_ingest import season_for_game

    assert season_for_game("0042300405", None, "Playoffs") == ("2023-24", "Playoffs")
    assert season_for_game("0022400100", None, "Playoffs") == ("2024-25", "Regular Season")
    assert season_for_game("fixture-game", "2022-23", "Playoffs") == ("2022-23", "Playoffs")
