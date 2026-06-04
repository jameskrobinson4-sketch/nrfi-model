"""Terminal card and JSON export."""

import json
from datetime import date
from pathlib import Path
from rich.console import Console
from rich.rule import Rule

console = Console()

TIER_COLOR = {"A": "bold green", "B": "bold yellow", "Skip": "dim"}
TIER_LABEL = {"A": "TIER A (2u)", "B": "TIER B (1u)", "Skip": "SKIP"}


def print_card(scores: list, game_date: date, min_tier: str = "SKIP") -> None:
    tier_rank = {"A": 0, "B": 1, "SKIP": 2}
    cutoff    = tier_rank.get(min_tier.upper(), 2)

    console.print()
    console.print(Rule(f"[bold]NRFI DAILY CARD — {game_date}[/bold]"))
    console.print()

    for gs in scores:
        if tier_rank.get(gs.tier.upper(), 2) > cutoff:
            continue

        color    = TIER_COLOR.get(gs.tier, "white")
        label    = TIER_LABEL.get(gs.tier, gs.tier)
        prob_pct = round(gs.p_nrfi * 100)

        console.print(
            f"[{color}][{label}][/{color}]  "
            f"[bold]{gs.away_team} @ {gs.home_team}[/bold]  {gs.game_time}"
        )
        console.print(
            f"  P(NRFI): [bold]{prob_pct}%[/bold] ±{gs.confidence_band}%  "
            f"(raw {gs.raw_score:.1f}/100)"
        )

        # ── Top of 1st: away bats vs home pitcher ─────────────────────────────
        top  = gs.top_half
        tpc  = top.pitcher.components
        console.print(
            f"\n  [bold]TOP 1st[/bold] — {gs.away_team} batting vs "
            f"[bold]{top.pitcher.pitcher_name}[/bold] "
            f"[{top.pitcher.handedness}HP]  "
            f"P(scoreless)={top.p_scoreless*100:.0f}%"
        )
        console.print(
            f"  Pitcher:  {top.pitcher.score:.0f}/100"
            + (f" | {tpc.get('rest_days')}d rest" if tpc.get('rest_days') else "")
            + f"  ({tpc.get('ip', 0):.0f} IP)"
        )
        console.print(
            f"            K9={tpc.get('k9',0):.0f}  BB9={tpc.get('bb9',0):.0f}  "
            f"HR9={tpc.get('hr9',0):.0f}  ERA={tpc.get('era',0):.0f}  "
            f"WHIP={tpc.get('whip',0):.0f}  REST={tpc.get('rest',0):.0f}"
        )
        confirmed_top = "confirmed" if top.matchup.lineup_confirmed else "estimated"
        console.print(f"  Matchup:  {top.matchup.score:.0f}/100  [{confirmed_top}]")
        for h in top.matchup.hitters:
            console.print(
                f"    {h['name']}: OBP {h['obp']:.3f}  "
                f"OPS {h.get('ops', 0):.3f}  K% {h.get('k_pct', 22.0):.1f}"
            )

        # ── Bottom of 1st: home bats vs away pitcher ──────────────────────────
        bot  = gs.bottom_half
        bpc  = bot.pitcher.components
        console.print(
            f"\n  [bold]BOT 1st[/bold] — {gs.home_team} batting vs "
            f"[bold]{bot.pitcher.pitcher_name}[/bold] "
            f"[{bot.pitcher.handedness}HP]  "
            f"P(scoreless)={bot.p_scoreless*100:.0f}%"
        )
        console.print(
            f"  Pitcher:  {bot.pitcher.score:.0f}/100"
            + (f" | {bpc.get('rest_days')}d rest" if bpc.get('rest_days') else "")
            + f"  ({bpc.get('ip', 0):.0f} IP)"
        )
        console.print(
            f"            K9={bpc.get('k9',0):.0f}  BB9={bpc.get('bb9',0):.0f}  "
            f"HR9={bpc.get('hr9',0):.0f}  ERA={bpc.get('era',0):.0f}  "
            f"WHIP={bpc.get('whip',0):.0f}  REST={bpc.get('rest',0):.0f}"
        )
        confirmed_bot = "confirmed" if bot.matchup.lineup_confirmed else "estimated"
        console.print(f"  Matchup:  {bot.matchup.score:.0f}/100  [{confirmed_bot}]")
        for h in bot.matchup.hitters:
            console.print(
                f"    {h['name']}: OBP {h['obp']:.3f}  "
                f"OPS {h.get('ops', 0):.3f}  K% {h.get('k_pct', 22.0):.1f}"
            )

        # ── Environment ───────────────────────────────────────────────────────
        env = gs.environment.components
        console.print(
            f"\n  Environment: Park {env.get('park',0):.0f}  "
            f"Weather {env.get('weather',0):.0f}  "
            f"Umpire {env.get('umpire',0):.0f}"
        )

        skip_words = {"neutral", "default", "lineup_not_confirmed",
                      "umpire_neutral_default"}
        notable = [f for f in gs.flags if not any(w in f for w in skip_words)]
        if notable:
            console.print(f"  [dim]Notes: {' | '.join(notable[:4])}[/dim]")

        console.print()

    tier_a  = sum(1 for g in scores if g.tier == "A")
    tier_b  = sum(1 for g in scores if g.tier == "B")
    skipped = sum(1 for g in scores if g.tier == "Skip")

    console.print(Rule())
    console.print(
        f"Games scored: [bold]{len(scores)}[/bold]  |  "
        f"Tier A (2u): [bold green]{tier_a}[/bold green]  |  "
        f"Tier B (1u): [bold yellow]{tier_b}[/bold yellow]  |  "
        f"Skip: [dim]{skipped}[/dim]"
    )
    console.print()


def export_json(scores: list, game_date: date) -> Path:
    out_dir = Path(__file__).parent
    path    = out_dir / f"{game_date}_picks.json"

    picks = []
    for gs in scores:
        picks.append({
            "game":            f"{gs.away_team}@{gs.home_team}",
            "time":            gs.game_time,
            "tier":            gs.tier,
            "p_nrfi_pct":     round(gs.p_nrfi * 100, 1),
            "confidence_band": gs.confidence_band,
            "raw_score":       gs.raw_score,
            "top_1st": {
                "p_scoreless":  round(gs.top_half.p_scoreless * 100, 1),
                "pitcher":      gs.top_half.pitcher.pitcher_name,
                "pitcher_hand": gs.top_half.pitcher.handedness,
                "pitcher_score": gs.top_half.pitcher.score,
                "pitcher_components": gs.top_half.pitcher.components,
                "matchup_score": gs.top_half.matchup.score,
                "lineup_confirmed": gs.top_half.matchup.lineup_confirmed,
                "hitters":      gs.top_half.matchup.hitters,
            },
            "bot_1st": {
                "p_scoreless":  round(gs.bottom_half.p_scoreless * 100, 1),
                "pitcher":      gs.bottom_half.pitcher.pitcher_name,
                "pitcher_hand": gs.bottom_half.pitcher.handedness,
                "pitcher_score": gs.bottom_half.pitcher.score,
                "pitcher_components": gs.bottom_half.pitcher.components,
                "matchup_score": gs.bottom_half.matchup.score,
                "lineup_confirmed": gs.bottom_half.matchup.lineup_confirmed,
                "hitters":      gs.bottom_half.matchup.hitters,
            },
            "environment":     {
                "score":      gs.environment.score,
                "components": gs.environment.components,
            },
            "flags":           gs.flags,
            "data_quality":    gs.data_quality,
        })

    path.write_text(json.dumps({"date": str(game_date), "picks": picks}, indent=2))
    log = __import__("utils.logger", fromlist=["get_logger"]).get_logger(__name__)
    log.info("JSON exported → %s", path)
    return path
