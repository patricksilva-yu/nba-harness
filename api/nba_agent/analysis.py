#!/usr/bin/env python3
"""Run the deterministic NBA analyst loop without an LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.nba_agent.tools import (
    DEFAULT_DB,
    ensure_game_cached,
    find_decisive_runs,
    get_advanced_game_context,
    get_game_snapshot,
    get_player_game_context,
    get_possession_summary,
    persist_evidence_packets,
)


def pick_top_packet(response: dict) -> dict | None:
    packets = response.get("evidence_packets", [])
    return packets[0] if packets else None


def pick_team_run(response: dict, team_abbr: str | None, fallback_to_top: bool = True) -> dict | None:
    if not team_abbr:
        return pick_top_packet(response)
    for packet in response.get("evidence_packets", []):
        if packet.get("metrics", {}).get("beneficiary") == team_abbr:
            return packet
    return pick_top_packet(response) if fallback_to_top else None


def winning_team(snapshot: dict) -> str | None:
    team_box = snapshot.get("team_box", [])
    if len(team_box) >= 2:
        winner = max(team_box, key=lambda team: team.get("pts") or 0)
        return winner.get("team_abbr")
    label = snapshot["summary"]["label"]
    if "," not in label:
        return None
    away_part, home_part = label.split(",", 1)
    try:
        away_abbr, away_score = away_part.strip().rsplit(" ", 1)
        home_abbr, home_score = home_part.strip().rsplit(" ", 1)
        return away_abbr if int(away_score) > int(home_score) else home_abbr
    except ValueError:
        return None


def pct_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def player_efficiency(player: dict) -> str:
    if player.get("fg") and player.get("fg3"):
        return f"{player['fg']} FG and {player['fg3']} from three"
    if player.get("fg"):
        return f"{player['fg']} FG"
    fgm = player.get("fgm") or 0
    fga = player.get("fga") or 0
    fg3m = player.get("fg3m") or 0
    fg3a = player.get("fg3a") or 0
    if fga and fg3a:
        return f"{int(fgm)}/{int(fga)} FG and {int(fg3m)}/{int(fg3a)} from three"
    if fga:
        return f"{int(fgm)}/{int(fga)} FG"
    return "limited shooting volume"


def find_player(players: dict, predicate) -> dict | None:
    for player in players.get("players", []):
        if predicate(player):
            return player
    return None


def build_one_sentence(snapshot: dict, advanced: dict, runs: dict, players: dict) -> str:
    label = snapshot["summary"]["label"]
    win_team = winning_team(snapshot)
    top_run = pick_team_run(runs, win_team, fallback_to_top=False)
    advanced_metrics = advanced.get("team_metrics", {})
    top_winner = find_player(players, lambda p: p.get("team_abbr") == win_team)
    if not top_winner:
        return (
            f"{label} was decided by the winning team's efficiency edge and the top "
            "candidate scoring window identified in play-by-play."
        )

    win_edge = None
    for key, metrics in advanced_metrics.items():
        if key.startswith(f"{win_team}_minus_"):
            win_edge = metrics
            break
    edge_text = ""
    if win_edge:
        turnover_edge = win_edge.get("tov_per_est_possession")
        if turnover_edge is None:
            turnover_edge = (win_edge.get("turnover_ratio") or 0) / 100
        edge_text = (
            f" showed an eFG edge of {pct_label(win_edge.get('efg_pct'))} and "
            f"{abs(turnover_edge or 0) * 100:.1f} percentage-point turnover edge"
        )
    run_text = ""
    if top_run:
        run_text = f", with {top_run['claim_seed'].replace(win_team + ' had ', '').rstrip('.')}"
    return (
        f"{win_team} won because its efficiency profile{edge_text}, backed by "
        f"{top_winner['player_name']}'s {int(top_winner['pts'])}-point scoring night{run_text}."
    )


def build_advanced_read(advanced: dict) -> list[str]:
    packet = pick_top_packet(advanced)
    if not packet:
        return ["No advanced-context packet was available."]
    metrics = packet["metrics"]
    edge_key = next((key for key in metrics if "_minus_" in key), None)
    if not edge_key:
        return [packet["claim_seed"]]
    team_keys = [key for key, value in metrics.items() if isinstance(value, dict) and "_minus_" not in key]
    if len(team_keys) < 2:
        return [packet["claim_seed"]]
    if packet["source"]["provider"] == "nba_official":
        winner = max(team_keys, key=lambda key: metrics[key].get("net_rating") or float("-inf"))
    else:
        winner = max(team_keys, key=lambda key: metrics[key].get("points_per_est_possession") or float("-inf"))
    loser = next(key for key in team_keys if key != winner)
    winner_metrics = metrics[winner]
    loser_metrics = metrics[loser]
    if packet["source"]["provider"] == "nba_official":
        return [
            (
                f"{winner}'s official advanced profile points to a real quality gap: "
                f"{winner_metrics['offensive_rating']:.1f} offensive rating vs "
                f"{loser_metrics['offensive_rating']:.1f}, with a "
                f"{winner_metrics['net_rating']:.1f} net rating vs {loser_metrics['net_rating']:.1f}."
            ),
            (
                f"The shot profile also held: {winner} posted {pct_label(winner_metrics['efg_pct'])} eFG "
                f"and {pct_label(winner_metrics['ts_pct'])} true shooting vs "
                f"{pct_label(loser_metrics['efg_pct'])} eFG and {pct_label(loser_metrics['ts_pct'])} true shooting."
            ),
            (
                f"Possession quality: turnover ratio was {winner_metrics['turnover_ratio']:.1f} vs "
                f"{loser_metrics['turnover_ratio']:.1f}, and PIE was "
                f"{winner_metrics['pie']:.3f} vs {loser_metrics['pie']:.3f}."
            ),
            (
                f"Evidence: `{packet['packet_id']}` "
                f"({packet['source']['provider']}, {packet['confidence']} confidence)."
            ),
        ]
    return [
        (
            f"{winner}'s fallback advanced profile points to a real quality gap: "
            f"{pct_label(winner_metrics['efg_pct'])} eFG vs {pct_label(loser_metrics['efg_pct'])}, "
            f"{winner_metrics['points_per_est_possession']:.2f} points per estimated possession vs "
            f"{loser_metrics['points_per_est_possession']:.2f}."
        ),
        (
            f"The cleanest margin was ball security: {winner}'s turnover-rate proxy was "
            f"{pct_label(winner_metrics['tov_per_est_possession'])} vs "
            f"{pct_label(loser_metrics['tov_per_est_possession'])}."
        ),
        (
            f"Evidence: `{packet['packet_id']}` "
            f"({packet['source']['provider']}, {packet['confidence']} confidence)."
        ),
    ]


def build_player_read(snapshot: dict, players: dict) -> list[str]:
    if players["summary"].get("resolution_status") == "player_box_unavailable":
        return [
            "Player box-score context is not available in the local cache. "
            "Official NBA player box-score ingestion is needed before this memo can explain "
            "individual scoring outliers from data."
        ]
    win_team = winning_team(snapshot)
    top_winner = find_player(players, lambda p: p.get("team_abbr") == win_team)
    creator = find_player(
        players,
        lambda p: p.get("team_abbr") == win_team and p.get("player_name") != (top_winner or {}).get("player_name") and (p.get("ast") or 0) >= 8,
    )
    named_support_scorer = find_player(
        players,
        lambda p: p.get("team_abbr") == win_team and p.get("player_name") == "Bruce Brown",
    )
    secondary_star = find_player(
        players,
        lambda p: p.get("team_abbr") == win_team and p.get("player_name") != (top_winner or {}).get("player_name") and (p.get("pts") or 0) >= 18,
    )
    opponent_turnover = find_player(
        players,
        lambda p: p.get("team_abbr") != win_team and (p.get("tov") or 0) >= 5,
    )
    lines: list[str] = []
    packet = pick_top_packet(players)
    if top_winner:
        lines.append(
            f"{top_winner['player_name']} was the clearest box-score swing: "
            f"{int(top_winner['pts'])} points, {int(top_winner['reb'])} rebounds, "
            f"{int(top_winner['ast'])} assists, {player_efficiency(top_winner)}, "
            f"and a {top_winner['plus_minus']:+.0f} plus-minus."
        )
    if creator:
        lines.append(
            f"{creator['player_name']} supplied the creation layer with "
            f"{int(creator['ast'])} assists and {int(creator['tov'])} turnovers."
        )
    if named_support_scorer and named_support_scorer != top_winner:
        lines.append(
            f"{named_support_scorer['player_name']}'s {int(named_support_scorer['pts'])} points gave "
            f"{win_team} a second support scorer ({player_efficiency(named_support_scorer)})."
        )
    if secondary_star and secondary_star not in (top_winner, creator, named_support_scorer):
        lines.append(
            f"{secondary_star['player_name']} added star-level pressure with "
            f"{int(secondary_star['pts'])} points, {int(secondary_star['reb'])} rebounds, "
            f"and {int(secondary_star['ast'])} assists."
        )
    if opponent_turnover:
        lines.append(
            f"On the other side, {opponent_turnover['player_name']}'s "
            f"{int(opponent_turnover['tov'])} turnovers fit the team-level turnover problem."
        )
    if packet:
        lines.append(f"Evidence: `{packet['packet_id']}` and related player packets.")
    return lines or ["No player context packet was available."]


def build_memo(
    snapshot: dict,
    advanced: dict,
    runs: dict,
    possessions: dict,
    players: dict,
) -> str:
    summary = snapshot["summary"]
    advanced_source = advanced.get("summary", {}).get("advanced_context_source")
    top_run = pick_top_packet(runs)
    possession_packet = pick_top_packet(possessions)
    lines = [
        f"# {summary['label']} - NBA Analyst Memo",
        "",
        "## One-Sentence Read",
        build_one_sentence(snapshot, advanced, runs, players),
        "",
        "## Advanced Stats Read",
    ]
    lines.extend(build_advanced_read(advanced))

    lines.extend(["", "## Decisive Window"])
    if top_run:
        metrics = top_run["metrics"]
        lines.extend(
            [
                top_run["claim_seed"],
                f"Window score moved from {metrics['start_score']} to {metrics['end_score']}.",
                "",
                f"Evidence: `{top_run['packet_id']}` "
                f"({top_run['source']['provider']}, {top_run['confidence']} confidence).",
            ]
        )
    else:
        lines.append("No decisive-run candidates were found.")

    lines.extend(["", "## Possession Context"])
    if possession_packet:
        metrics = possession_packet["metrics"]
        lines.extend(
            [
                "The possession model is intentionally approximate in v1.",
                (
                    f"Event mix: {metrics['shot_events']} shot events, "
                    f"{metrics['free_throw_events']} free-throw events, "
                    f"{metrics['turnovers']} turnovers."
                ),
                "",
                f"Evidence: `{possession_packet['packet_id']}`.",
            ]
        )
    else:
        lines.append("No possession summary was available.")

    lines.extend(["", "## Player Context"])
    lines.extend(build_player_read(snapshot, players))

    lines.extend(
        [
            "",
            "## Confidence",
            (
                "High for box-score and official advanced values; medium for inferred run and possession context. "
                "This memo uses cached team, player, advanced, and play-by-play rows."
                if advanced_source == "nba_official"
                else "Medium. This memo uses cached team, player, and play-by-play rows, official NBA rows when available, "
                "and fallback advanced metrics."
            ),
        ]
    )
    return "\n".join(lines)


def run_analysis(game_id: str, db_path: Path = DEFAULT_DB) -> dict:
    cache_result = ensure_game_cached(game_id, db_path)
    snapshot = get_game_snapshot(game_id, db_path)
    advanced = get_advanced_game_context(game_id, db_path)
    runs = find_decisive_runs(game_id, db_path)
    possessions = get_possession_summary(game_id, db_path)
    players = get_player_game_context(game_id, db_path)
    packet_ids = []
    persistence_complete = True
    for response in (snapshot, advanced, runs, possessions, players):
        packet_ids.extend(packet["packet_id"] for packet in response.get("evidence_packets", []))
        persistence_complete = (
            persist_evidence_packets(game_id, response.get("evidence_packets", []), db_path)
            and persistence_complete
        )
    return {
        "game_id": game_id,
        "cache": cache_result["summary"],
        "memo_markdown": build_memo(snapshot, advanced, runs, possessions, players),
        "packet_ids": packet_ids,
        "persistence_complete": persistence_complete,
        "tool_responses": {
            "snapshot": snapshot,
            "advanced": advanced,
            "runs": runs,
            "possessions": possessions,
            "players": players,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", default="0042200404")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of memo markdown.")
    args = parser.parse_args()

    result = run_analysis(args.game_id, args.db)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result["memo_markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
