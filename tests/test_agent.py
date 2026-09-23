import pytest
from api.nba_agent.agent import classify_question, run_agent, season_type_for_ingest
from api.nba_agent.analysis import winning_team
import api.nba_agent.tools as tools
from api.nba_agent.tools import get_box_score, get_game_snapshot, get_lineup_stints, resolve_game_reference


def test_classify_question_routes():
    assert classify_question("advanced stats for Knicks Cavs") == "advanced"
    assert classify_question("what happened late in OKC Spurs") == "late_game"
    assert classify_question("who swung the Knicks Cavs game") == "players"
    assert classify_question("which lineup swung the game") == "lineups"
    assert classify_question("why did the Knicks win") == "full"


def test_run_agent_cached_game_shape():
    result = run_agent(
        "advanced stats for Knicks Cavs",
        game_id="0042500303",
        max_evidence=2,
        persist=False,
    )

    assert result["route"] == "advanced"
    assert result["persisted"] is False
    assert result["answer_markdown"].startswith("# NYK 121, CLE 108")
    assert result["analysis_run_id"] is None
    assert result["packet_ids"]
    assert len(result["evidence"]) == 2
    assert result["evidence"][0]["source"] == "in_memory"


def test_run_agent_player_route_uses_compact_player_rows():
    result = run_agent(
        "who swung the Knicks Cavs game",
        game_id="0042500303",
        max_evidence=2,
        persist=False,
    )

    assert result["route"] == "players"
    assert "## Player Read" in result["answer_markdown"]
    assert result["packet_ids"]


def test_run_agent_full_route_builds_memo():
    result = run_agent(
        "why did the Knicks win",
        game_id="0042500303",
        max_evidence=3,
        persist=False,
    )

    assert result["route"] == "full"
    assert "## One-Sentence Read" in result["answer_markdown"]
    assert "## Possession Context" in result["answer_markdown"]
    assert result["tool_responses"]["possessions"] is not None


def test_winning_team_uses_scores_not_first_label_team():
    snapshot = {
        "summary": {"label": "OKC 91, SAS 118"},
        "team_box": [
            {"team_abbr": "OKC", "pts": 91},
            {"team_abbr": "SAS", "pts": 118},
        ],
    }

    assert winning_team(snapshot) == "SAS"


def test_full_route_does_not_call_losing_team_the_winner():
    result = run_agent(
        "why did the Spurs beat the Thunder?",
        game_id="0042500316",
        max_evidence=1,
        persist=False,
    )

    assert "SAS won" in result["answer_markdown"]
    assert "SAS's official advanced profile" in result["answer_markdown"]
    assert "OKC won" not in result["answer_markdown"]


def test_snapshot_claim_uses_actual_winner():
    snapshot = get_game_snapshot("0042500316", persist=False)

    assert snapshot["evidence_packets"][0]["claim_seed"] == "SAS defeated OKC 118-91."


def test_box_score_tool_returns_team_rows():
    box_score = get_box_score("0042500303", level="team")

    assert box_score["summary"]["row_count"] == 2
    assert {row["team_abbr"] for row in box_score["box_score"]} == {"NYK", "CLE"}


def test_lineup_stints_falls_back_to_substitution_events():
    lineups = get_lineup_stints("0042500303")

    assert lineups["summary"]["lineup_model"] in {"official_game_rotation", "pbp_substitution_inferred_v1"}
    assert lineups["summary"]["stint_count"] > 0
    assert lineups["evidence_packets"][0]["type"] == "lineup_stints"


def test_run_agent_lineup_route():
    result = run_agent(
        "which lineup or rotation stint swung the Knicks Cavs game",
        game_id="0042500303",
        max_evidence=2,
        persist=False,
    )

    assert result["route"] == "lineups"
    assert "## Rotation / Stint Read" in result["answer_markdown"]
    assert result["tool_responses"]["lineups"] is not None


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


def test_season_type_for_ingest_uses_resolved_season_type():
    resolution = {"summary": {"game_id": "0042500316", "season_type": "Playoffs"}}

    assert season_type_for_ingest(resolution, "Auto") == "Playoffs"
    assert season_type_for_ingest(resolution, "Regular Season") == "Playoffs"


def test_season_type_for_ingest_falls_back_to_game_id_prefix_for_provided_ids():
    assert season_type_for_ingest({"summary": {"game_id": "0042500316"}}, "Auto") == "Playoffs"
    assert season_type_for_ingest({"summary": {"game_id": "0022501196"}}, "Auto") == "Regular Season"


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
