#!/usr/bin/env python3
"""
Run NRFI model and push per-game ntfy notifications as lineups confirm.

Runs hourly via GitHub Actions. Each run:
  - Clears lineup/umpire cache so fresh data is fetched
  - Re-scores all games
  - Sends one notification per newly qualifying game (Tier A/B, both lineups confirmed)
  - Tracks already-notified game_pks in output/{date}_notified.json
  - Silent run if nothing new to report
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nrfi-3d5e5fc61cbd")
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"
MODEL_DIR  = Path(__file__).parent


# ── Cache helpers ─────────────────────────────────────────────────────────────

def clear_stale_cache():
    cache_dir = MODEL_DIR / "data" / "cache" / str(date.today())
    if not cache_dir.exists():
        return 0
    cleared = 0
    for pattern in ("lineup_*.json", "umpire_*.json"):
        for f in cache_dir.glob(pattern):
            f.unlink()
            cleared += 1
    return cleared


# ── State tracking ────────────────────────────────────────────────────────────

def _state_path() -> Path:
    return MODEL_DIR / "output" / f"{date.today()}_notified.json"


def load_notified() -> set:
    p = _state_path()
    if p.exists():
        return set(json.loads(p.read_text()))
    return set()


def save_notified(notified: set):
    _state_path().write_text(json.dumps(sorted(notified)))


# ── Model runner ──────────────────────────────────────────────────────────────

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


# ── Notification formatting ───────────────────────────────────────────────────

def _hitter_line(hitters: list, team: str) -> str:
    """Compact last-name + OBP list: 'Torres .408 · McGonigle .398 · Dingler .346'"""
    parts = []
    for h in hitters[:3]:
        last = h["name"].split()[-1]
        parts.append(f"{last} .{int(round(h['obp'] * 1000)):03d}")
    return f"{team}: " + " · ".join(parts)


def _pitcher_line(half: dict, side_label: str, opp_team: str) -> str:
    """'▲ TOP  Keider Montero (RHP)  60/100 · 66 IP  →  61% scoreless'"""
    pc   = half["pitcher_components"]
    ip   = pc.get("ip", 0)
    hand = half["pitcher_hand"]
    return (
        f"{side_label}  {half['pitcher']} ({hand}HP)"
        f"  {half['pitcher_score']:.0f}/100 · {ip:.0f} IP"
        f"  →  {half['p_scoreless']:.0f}% scoreless"
    )


def format_pick(pick: dict) -> tuple[str, str, str]:
    """Return (title, body, priority) for a single confirmed qualifying pick."""
    tier  = pick["tier"]
    game  = pick["game"]
    time  = pick["time"]
    prob  = pick["p_nrfi_pct"]
    band  = pick["confidence_band"]
    raw   = pick["raw_score"]
    top   = pick["top_1st"]
    bot   = pick["bot_1st"]
    env   = pick["environment"]["components"]

    away, home = game.split("@")
    stake      = "2u" if tier == "A" else "1u"
    icon       = "★" if tier == "A" else "▸"

    title = f"{icon} NRFI Tier {tier} ({stake}) — {game}  {time}"

    ump_name = env.get("umpire_name", "")
    ump_str  = f"{env.get('umpire', 50):.0f}"
    if ump_name:
        ump_str += f" ({ump_name})"

    wx_flag = next(
        (f for f in pick.get("flags", []) if "mph" in f or "°F" in f or "%rh" in f),
        "",
    )

    lines = [
        f"P(NRFI): {prob}%  ±{band}%  [raw {raw:.0f}/100]",
        "",
        _pitcher_line(top, "▲ TOP", away),
        f"  {_hitter_line(top.get('hitters', []), away)}",
        "",
        _pitcher_line(bot, "▼ BOT", home),
        f"  {_hitter_line(bot.get('hitters', []), home)}",
        "",
        f"Park {env.get('park', 50):.0f}  ·  Wx {env.get('weather', 50):.0f}  ·  Ump {ump_str}",
    ]
    if wx_flag:
        lines.append(f"🌡 {wx_flag}")
    lines.append("✅ Lineups confirmed")

    body     = "\n".join(lines)
    priority = "high" if tier == "A" else "default"
    return title, body, priority


# ── ntfy sender ───────────────────────────────────────────────────────────────

def send(title: str, body: str, priority: str, tags: str = "baseball"):
    try:
        resp = requests.post(
            f"https://ntfy.sh/",
            json={
                "topic":    NTFY_TOPIC,
                "title":    title,
                "message":  body,
                "priority": {"high": 4, "default": 3, "low": 2}.get(priority, 3),
                "tags":     [tags],
            },
            timeout=10,
        )
        resp.raise_for_status()
        print(f"[{datetime.now().strftime('%H:%M')}] Sent: {title}")
    except Exception as e:
        print(f"Notification failed: {e}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ts = datetime.now().strftime("%H:%M")

    cleared = clear_stale_cache()
    print(f"[{ts}] Cleared {cleared} stale cache files")

    print(f"[{ts}] Running model...")
    if not run_model():
        print(f"[{ts}] Model failed — skipping notifications", file=sys.stderr)
        sys.exit(1)

    data = load_picks()
    if not data:
        print(f"[{ts}] No picks data — skipping", file=sys.stderr)
        sys.exit(0)

    picks    = data.get("picks", [])
    notified = load_notified()

    # Only care about Tier A/B with BOTH lineups confirmed
    qualified = [
        p for p in picks
        if p["tier"] in ("A", "B")
        and p["top_1st"].get("lineup_confirmed", False)
        and p["bot_1st"].get("lineup_confirmed", False)
    ]

    newly_qualified = [
        p for p in qualified
        if str(p["game_pk"]) not in notified
    ]

    print(
        f"[{ts}] {len(picks)} games scored · "
        f"{len(qualified)} confirmed plays · "
        f"{len(newly_qualified)} new to notify"
    )

    for pick in newly_qualified:
        title, body, priority = format_pick(pick)
        send(title, body, priority)
        notified.add(str(pick["game_pk"]))

    save_notified(notified)
