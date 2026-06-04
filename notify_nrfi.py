#!/usr/bin/env python3
"""
Run NRFI model and push today's card to ntfy.sh.
Scheduled at 11am, 1pm, and 3pm ET via cron.

Each run clears lineup/umpire cache so fresh data is fetched —
pitcher and batter stats stay cached since they don't change intraday.
"""

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import os

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nrfi-3d5e5fc61cbd")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
MODEL_DIR = Path(__file__).parent


def clear_stale_cache():
    """Delete lineup and umpire cache so they're re-fetched fresh each run."""
    cache_dir = MODEL_DIR / "data" / "cache" / str(date.today())
    if not cache_dir.exists():
        return 0
    cleared = 0
    for pattern in ("lineup_*.json", "umpire_*.json"):
        for f in cache_dir.glob(pattern):
            f.unlink()
            cleared += 1
    return cleared


def run_model() -> bool:
    result = subprocess.run(
        [sys.executable, "main.py", "--json"],
        cwd=MODEL_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def load_picks() -> dict:
    path = MODEL_DIR / "output" / f"{date.today()}_picks.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def lineup_status(pick: dict) -> tuple[bool, bool]:
    top_ok = pick["top_1st"].get("lineup_confirmed", False)
    bot_ok = pick["bot_1st"].get("lineup_confirmed", False)
    return top_ok, bot_ok


def lu_label(top_ok: bool, bot_ok: bool) -> str:
    if top_ok and bot_ok:
        return "✓ lineups confirmed"
    if top_ok:
        return "⚠ away only — home lineup pending"
    if bot_ok:
        return "⚠ home only — away lineup pending"
    return "⚠ both lineups pending"


def format_message(data: dict, run_label: str) -> tuple[str, str, str]:
    """Returns (title, body, priority string for ntfy)."""
    if not data:
        return f"NRFI {run_label} — Error", "Model failed to run today.", "default"

    today = data.get("date", str(date.today()))
    picks = data.get("picks", [])
    total = len(picks)

    tier_a   = [p for p in picks if p["tier"] == "A"]
    tier_b   = [p for p in picks if p["tier"] == "B"]
    playable = tier_a + tier_b

    confirmed_both  = sum(1 for p in picks if all(lineup_status(p)))
    pending_picks   = [p for p in picks if not all(lineup_status(p))]

    # ── Title ─────────────────────────────────────────────────────────────────
    if tier_a and tier_b:
        play_str = f"{len(tier_a)}A + {len(tier_b)}B"
    elif tier_a:
        play_str = f"{len(tier_a)} Tier A"
    elif tier_b:
        play_str = f"{len(tier_b)} Tier B"
    else:
        play_str = "No plays"

    title = f"NRFI {run_label}  |  {play_str}  |  {confirmed_both}/{total} lineups in"

    lines = []

    # ── Tier A/B picks ────────────────────────────────────────────────────────
    for p in playable:
        top_ok, bot_ok = lineup_status(p)
        tier_icon = "★" if p["tier"] == "A" else "▸"
        tier_tag  = "TIER A (2u)" if p["tier"] == "A" else "TIER B (1u)"
        top = p["top_1st"]
        bot = p["bot_1st"]
        env = p["environment"]["components"]

        lines.append(
            f"{tier_icon} {tier_tag} — {p['game']}  {p['time']}\n"
            f"  P(NRFI): {p['p_nrfi_pct']}% ±{p['confidence_band']}%\n"
            f"  {lu_label(top_ok, bot_ok)}\n"
            f"  TOP: {top['pitcher']} ({top['pitcher_score']:.0f})  {top['p_scoreless']}% scoreless\n"
            f"  BOT: {bot['pitcher']} ({bot['pitcher_score']:.0f})  {bot['p_scoreless']}% scoreless\n"
            f"  Park {env.get('park',50):.0f}  Wx {env.get('weather',50):.0f}  Ump {env.get('umpire',50):.0f}"
        )

    # ── No plays: show top-3 closest skips ───────────────────────────────────
    if not playable:
        lines.append("No Tier A or B picks right now.")
        top_skips = sorted(picks, key=lambda x: x["p_nrfi_pct"], reverse=True)[:3]
        if top_skips:
            lines.append("\nClosest to threshold:")
            for p in top_skips:
                top_ok, bot_ok = lineup_status(p)
                lu = "✓" if (top_ok and bot_ok) else "⚠ lineup pending"
                lines.append(f"  {p['game']}  {p['p_nrfi_pct']}%  [{lu}]")

    # ── Lineup pending summary ────────────────────────────────────────────────
    lines.append("")
    if pending_picks:
        pending_names = "  ".join(p["game"] for p in pending_picks)
        lines.append(f"⚠ Lineups still pending ({len(pending_picks)}/{total} games):")
        # Wrap into rows of 4 for readability
        games = [p["game"] for p in pending_picks]
        rows = [games[i:i+4] for i in range(0, len(games), 4)]
        for row in rows:
            lines.append("  " + "  ".join(row))
    else:
        lines.append(f"✓ All {total} lineups confirmed")

    lines.append(f"\n{total} games scored — {run_label} update")

    body     = "\n".join(lines)
    priority = "high" if tier_a else ("default" if playable else "low")
    return title, body, priority


def send_notification(title: str, body: str, priority: str):
    try:
        resp = requests.post(
            NTFY_URL,
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "baseball",
            },
            timeout=10,
        )
        resp.raise_for_status()
        print(f"[{datetime.now().strftime('%H:%M')}] Sent: {title}")
    except Exception as e:
        print(f"Notification failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    hour = datetime.now().hour
    if hour < 12:
        run_label = "11am"
    elif hour < 14:
        run_label = "1pm"
    else:
        run_label = "3pm"

    cleared = clear_stale_cache()
    print(f"[{datetime.now().strftime('%H:%M')}] {run_label} run — cleared {cleared} stale cache files")

    print(f"Running model...")
    run_model()

    data = load_picks()
    title, body, priority = format_message(data, run_label)
    print(f"Title: {title}")
    send_notification(title, body, priority)
