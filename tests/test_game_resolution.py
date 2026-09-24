import pytest
import api.nba_agent.tools as tools
from api.nba_agent.tools import get_box_score, get_game_snapshot, get_lineup_stints, resolve_game_reference


def test_snapshot_claim_uses_actual_winner():
    snapshot = get_game_snapshot("0042500316", persist=False)

    assert snapshot["evidence_packets"][0]["claim_seed"] == "SAS defeated OKC 118-91."
    assert {row["team_abbr"] for row in snapshot["evidence_packets"][0]["metrics"]["team_box"]} == {"SAS", "OKC"}


def test_box_score_tool_returns_team_rows():
    box_score = get_box_score("0042500303", level="team")

    assert box_score["summary"]["row_count"] == 2
    assert {row["team_abbr"] for row in box_score["box_score"]} == {"NYK", "CLE"}


def test_lineup_stints_falls_back_to_substitution_events():
    lineups = get_lineup_stints("0042500303")

    assert lineups["summary"]["lineup_model"] in {"official_game_rotation", "pbp_substitution_inferred_v1"}
    assert lineups["summary"]["stint_count"] > 0
    assert lineups["evidence_packets"][0]["type"] == "lineup_stints"


def test_resolution_returns_ambiguous_for_repeated_matchup_without_date(monkeypatch):
    monkeypatch.setattr(
        tools,
        "find_recent_completed_games_for_resolution",
        lambda **_: {
            "summary": {"searched_season_types": ["Playoffs"], "count": 2},
            "games": [
                {
                    "game_id": "1",
                    "game_date": "2026-05-25",
                    "label": "NYK 130, CLE 93",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "NYK",
                    "home_score": 93,
                    "away_score": 130,
                },
                {
                    "game_id": "2",
                    "game_date": "2026-05-23",
                    "label": "NYK 121, CLE 108",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "NYK",
                    "home_score": 108,
                    "away_score": 121,
                },
            ],
            "source_status": [],
            "warnings": [],
        },
    )
    resolution = resolve_game_reference("Knicks Cavs", season_type="Auto")

    assert resolution["summary"]["resolution_status"] == "ambiguous"
    assert len(resolution["candidates"]) >= 2


def test_resolution_picks_newest_game_when_latest_is_requested(monkeypatch):
    monkeypatch.setattr(
        tools,
        "find_recent_completed_games_for_resolution",
        lambda **_: {
            "summary": {"searched_season_types": ["Playoffs"], "count": 2},
            "games": [
                {
                    "game_id": "1",
                    "game_date": "2026-05-25",
                    "label": "NYK 130, CLE 93",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "NYK",
                    "home_score": 93,
                    "away_score": 130,
                },
                {
                    "game_id": "2",
                    "game_date": "2026-05-23",
                    "label": "NYK 121, CLE 108",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "NYK",
                    "home_score": 108,
                    "away_score": 121,
                },
            ],
            "source_status": [],
            "warnings": [],
        },
    )
    for query in ("Why did the Knicks win their last game?", "Knicks latest game", "most recent Knicks Cavs game"):
        resolution = resolve_game_reference(query, season_type="Auto")
        assert resolution["summary"]["resolution_status"] == "resolved", query
        assert resolution["summary"]["game_id"] == "1", query
        assert resolution["summary"]["preference"] == "latest_game", query


def test_latest_game_phrases():
    assert tools.requests_latest_game("How did the Knicks do in their last game")
    assert tools.requests_latest_game("Knicks last playoff game")
    assert not tools.requests_latest_game("Who scored in the last quarter of Knicks Cavs")
    assert not tools.requests_latest_game("Knicks Cavs game 6")


def test_resolution_searches_deeper_than_display_limit(monkeypatch):
    requested_limits = []

    def fake_recent_games(**kwargs):
        requested_limits.append(kwargs["limit"])
        return {
            "summary": {"searched_season_types": ["Playoffs"], "count": 1},
            "games": [
                {
                    "game_id": "0042500207",
                    "game_date": "2026-04-30",
                    "season_type": "Playoffs",
                    "label": "TOR 96, CLE 101",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "TOR",
                    "home_score": 101,
                    "away_score": 96,
                },
            ],
            "source_status": [],
            "warnings": [],
        }

    monkeypatch.setattr(tools, "find_recent_completed_games_for_resolution", fake_recent_games)
    resolution = resolve_game_reference("Raptors Cavaliers Game 7 2026", season_type="Playoffs", limit=10)

    assert requested_limits == [120]
    assert resolution["summary"]["resolution_status"] == "resolved"
    assert resolution["summary"]["game_id"] == "0042500207"


@pytest.mark.parametrize("season", [None, "2016"])
def test_resolution_honors_calendar_year_for_numbered_playoff_game(monkeypatch, season):
    searched = []

    def fake_recent_games(**kwargs):
        searched.append(kwargs["season"])
        return {
            "summary": {"searched_season_types": ["Playoffs"]},
            "games": [
                {"game_id": game_id, "game_date": game_date, "season_type": "Playoffs",
                 "label": label, "home_team_abbr": "CLE", "away_team_abbr": "TOR",
                 "home_score": 113, "away_score": 87}
                for game_id, game_date, label in [
                    ("0042500136", "2026-05-01", "CLE 110, TOR 112"),
                    ("0041500306", "2016-05-27", "CLE 113, TOR 87"),
                ]],
            "source_status": [], "warnings": [],
        }

    monkeypatch.setattr(tools, "find_recent_completed_games_for_resolution", fake_recent_games)
    resolution = resolve_game_reference("Raptors vs Cavaliers Game 6 in 2016", season=season, season_type="Auto")

    assert searched == ["2015-16"]
    assert resolution["summary"]["game_id"] == "0041500306"


def test_resolution_requires_all_named_teams(monkeypatch):
    monkeypatch.setattr(
        tools,
        "find_recent_completed_games_for_resolution",
        lambda **_: {
            "summary": {"searched_season_types": ["Playoffs"], "count": 1},
            "games": [
                {
                    "game_id": "0042500304",
                    "game_date": "2026-05-25",
                    "season_type": "Playoffs",
                    "label": "NYK 130, CLE 93",
                    "home_team_abbr": "CLE",
                    "away_team_abbr": "NYK",
                    "home_score": 93,
                    "away_score": 130,
                },
            ],
            "source_status": [],
            "warnings": [],
        },
    )
    resolution = resolve_game_reference("Raptors Cavaliers Game 7 2026", season_type="Playoffs", limit=10)

    assert resolution["summary"]["resolution_status"] == "not_found"
    assert resolution["summary"]["matched_teams"] == ["CLE", "TOR"]


def test_resolution_uses_requested_playoff_game_number(monkeypatch):
    games = []
    for index in range(1, 8):
        games.append(
            {
                "game_id": f"004250020{index}",
                "game_date": f"2026-04-{20 + index:02d}",
                "season_type": "Playoffs",
                "label": f"TOR {90 + index}, CLE {95 + index}",
                "home_team_abbr": "CLE" if index % 2 else "TOR",
                "away_team_abbr": "TOR" if index % 2 else "CLE",
                "home_score": 95 + index,
                "away_score": 90 + index,
            }
        )
    monkeypatch.setattr(
        tools,
        "find_recent_completed_games_for_resolution",
        lambda **_: {
            "summary": {"searched_season_types": ["Playoffs"], "count": len(games)},
            "games": list(reversed(games)),
            "source_status": [],
            "warnings": [],
        },
    )

    resolution = resolve_game_reference("Why did the Raptors lose game 7 to the Cavs in 2026?", season_type="Playoffs")

    assert resolution["summary"]["resolution_status"] == "resolved"
    assert resolution["summary"]["preference"] == "playoff_series_game_match"
    assert resolution["summary"]["game_id"] == "0042500207"
    assert resolution["summary"]["series_game_number"] == 7


def spurs_playoff_run():
    """Spurs games across three rounds; ids encode round and game number."""
    series = [("0042500150", "POR", "2026-04-{:02d}", 20), ("0042500230", "DEN", "2026-05-{:02d}", 5), ("0042500400", "NYK", "2026-06-{:02d}", 3)]
    games = []
    for prefix, opponent, day, start in series:
        for number in range(1, 7):
            games.append({"game_id": f"{prefix[:-1]}{number}", "game_date": day.format(start + number), "season_type": "Playoffs",
                          "label": f"{opponent} 100, SAS 101", "home_team_abbr": "SAS", "away_team_abbr": opponent,
                          "home_score": 101, "away_score": 100})
    return {"summary": {"searched_season_types": ["Playoffs"], "count": len(games)},
            "games": sorted(games, key=lambda g: g["game_date"], reverse=True), "source_status": [], "warnings": []}


@pytest.mark.parametrize("query,expected", [
    ("why did the Spurs lose their lead in the 4th quarter of game 5? game 5 of finals", "0042500405"),
    ("Game 5 of the NBA Finals, Spurs lost their lead", "0042500405"),
    ("Spurs game 5 in the first round", "0042500155"),
    ("Spurs game 5 conference semifinals", "0042500235"),
    # No round named: game 5 of the most recent series, not the Spurs' fifth playoff game.
    ("Why did the Spurs win game 5?", "0042500405"),
])
def test_resolution_reads_series_game_and_round(monkeypatch, query, expected):
    monkeypatch.setattr(tools, "find_recent_completed_games_for_resolution", lambda **_: spurs_playoff_run())
    resolution = resolve_game_reference(query, season_type="Auto")
    assert resolution["summary"]["resolution_status"] == "resolved"
    assert resolution["summary"]["game_id"] == expected
    assert resolution["summary"]["series_game_number"] == 5


def test_playoff_round_words():
    from api.nba_agent.tools import requested_playoff_round
    assert requested_playoff_round("NBA Finals game 2") == 4
    assert requested_playoff_round("East finals") == 3
    assert requested_playoff_round("western conference finals") == 3
    assert requested_playoff_round("conference semifinals") == 2
    assert requested_playoff_round("semi-finals") == 2
    assert requested_playoff_round("first round") == 1
    assert requested_playoff_round("last night") is None
