from datetime import date

import pytest

from api.nba_agent.tools import matching_team_abbrs, requested_game_date, season_for_date

TODAY = date(2026, 9, 23)


def test_teams_match_whole_words_only():
    # "show" once matched Houston and turned a real question into a refusal.
    assert matching_team_abbrs("Thunder vs Suns - quick hits for a show segment") == {"OKC", "PHX"}
    assert matching_team_abbrs("It was a sudden, memorable finish; find the details in the world feed, 36 min") == set()


def test_word_like_abbreviations_count_only_in_capitals():
    assert matching_team_abbrs("WAS at DEN") == {"WAS", "DEN"}
    assert matching_team_abbrs("the game was close") == set()
    assert matching_team_abbrs("Wizards vs Nuggets") == {"WAS", "DEN"}


def test_multi_word_team_names_still_match():
    assert matching_team_abbrs("golden state at portland trail blazers") == {"GSW", "POR"}


@pytest.mark.parametrize("text, expected", [
    ("Thunder vs Suns on April 12, 2026", "2026-04-12"),
    ("Apr 12 2026 game", "2026-04-12"),
    ("the April 12th game", "2026-04-12"),
    ("12 April 2026", "2026-04-12"),
    ("the 12th of April", "2026-04-12"),
    ("4/12/2026", "2026-04-12"),
    ("4/12/26", "2026-04-12"),
    ("the game on 4/12", "2026-04-12"),
    ("2026-04-12", "2026-04-12"),
    ("Sept. 30", "2025-09-30"),  # without a year: the latest such date not in the future
    ("Dec 13, 2024", "2024-12-13"),
    ("last night", "2026-09-22"),
])
def test_written_dates(text, expected):
    assert requested_game_date(text, TODAY) == expected


def test_scores_and_non_dates_are_not_dates():
    assert requested_game_date("Boston won 106-88 in Game 5", TODAY) is None
    assert requested_game_date("may the best team win", TODAY) is None
    assert requested_game_date("13/45 from three", TODAY) is None
    assert requested_game_date("Brunson went 5/12 from three", TODAY) is None


def test_dates_map_to_the_season_that_contains_them():
    assert season_for_date("2024-12-13") == "2024-25"
    assert season_for_date("2025-06-17") == "2024-25"


def test_game_number_beyond_the_series_reports_how_it_ended(monkeypatch):
    from api.nba_agent import tools

    scores = [(95, 105), (104, 105), (111, 115), (107, 106), (90, 94)]
    homes = ["SAS", "SAS", "NYK", "NYK", "SAS"]
    games = [{"game_id": f"004250040{n}", "game_date": f"2026-06-0{n}", "season_type": "Playoffs",
              "home_team_abbr": home, "away_team_abbr": "NYK" if home == "SAS" else "SAS",
              "home_score": h, "away_score": a, "label": "x"}
             for n, home, (h, a) in zip(range(1, 6), homes, scores)]
    monkeypatch.setattr(tools, "find_recent_completed_games_for_resolution",
                        lambda **_: {"games": games, "summary": {}, "source_status": [], "warnings": []})
    result = tools.resolve_game_reference("Knicks Game 7 vs the Spurs")
    summary = result["summary"]
    assert summary["resolution_status"] == "game_not_played" and "game_id" not in summary
    assert summary["series"]["winner"] == "NYK" and summary["series"]["wins"] == {"NYK": 4, "SAS": 1}
    assert summary["series"]["games_played"] == 5 and summary["series"]["last_game"]["game_id"] == "0042500405"
    assert [c["series_game_number"] for c in result["candidates"]] == [5, 4, 3, 2, 1]
    # A game number that was played still resolves normally.
    assert tools.resolve_game_reference("Knicks Game 4 vs the Spurs")["summary"]["game_id"] == "0042500404"


def test_not_found_for_a_dated_question_stays_small(monkeypatch):
    from api.nba_agent import tools

    season = [{"game_id": f"00225{n:05d}", "game_date": "2026-01-01", "season_type": "Regular Season",
               "home_team_abbr": "BOS", "away_team_abbr": "MIA", "home_score": 100, "away_score": 90, "label": "x"}
              for n in range(1300)]
    monkeypatch.setattr(tools, "find_recent_completed_games_for_resolution",
                        lambda **_: {"games": season, "summary": {}, "source_status": [], "warnings": []})
    result = tools.resolve_game_reference("Raptors vs Lakers on April 1, 2026")
    assert result["summary"]["resolution_status"] == "not_found"
    assert len(result["recent_games"]) == 20
